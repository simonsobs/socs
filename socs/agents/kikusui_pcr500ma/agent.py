#!/usr/bin/env python3
# Code developed with AI assistance.
import argparse
import math
import os
import time
from dataclasses import dataclass

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.kikusui_pcr500ma.drivers import (PCR500MA, VOLT_ULIM_SOFT,
                                                  PCRException)

PORT_DEFAULT = 5025

LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10
ACQ_TIMEOUT = 5
VOLT_STEP = 1.
VOLT_ALLOW = 1.2
RAMP_TIME_STEP = 7.


class PCRStateError(Exception):
    """A requested operation is not allowed in the current device state."""


@dataclass(frozen=True)
class PCRState:
    """Device readbacks and the safety rules for control operations."""

    output: bool
    volt_set: float
    measured: float

    def check_output_on(self):
        """Require a zero voltage setting before enabling the output."""
        if self.volt_set != 0:
            raise PCRStateError('Voltage setting must be zero to turn output on.')

    def check_output_off(self):
        """Require a low measured voltage before disabling the output."""
        if not math.isfinite(self.measured) or self.measured >= 0.2:
            raise PCRStateError('Measured voltage too high to turn output off.')

    def check_voltage_consistency(self):
        """Check that valid voltage readbacks agree with the setting."""
        if not (0 <= self.volt_set <= VOLT_ULIM_SOFT and self.measured >= 0):
            raise PCRStateError('Invalid voltage readback.')
        if abs(self.volt_set - self.measured) > VOLT_ALLOW:
            raise PCRStateError(f'Voltage discrepancy: setting {self.volt_set} V, measured {self.measured} V.')

    def check_voltage_step(self, next_voltage):
        """Check a proposed ramp step after checking voltage consistency."""
        if not self.output:
            raise PCRStateError('Output turned off during ramp.')
        lower = max(0, self.volt_set - VOLT_STEP)
        upper = min(VOLT_ULIM_SOFT, self.volt_set + VOLT_STEP)
        if not lower <= next_voltage <= upper:
            raise PCRStateError(f'Voltage step must stay within 0 to {VOLT_ULIM_SOFT} V and change by at most {VOLT_STEP} V.')
        if abs(next_voltage - self.measured) > VOLT_ALLOW:
            raise PCRStateError(f'Next voltage {next_voltage} V is too far from measured {self.measured} V.')


class PCR500MAAgent:
    """OCS agent class for PCR500MA current source

    Parameters
    ----------
    ip : string
        IP address
    port : int
        Port number
    """

    def __init__(self, agent, ip_addr, port=PORT_DEFAULT):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.lock_ramp = TimeoutLock()  # Lock to protect control during ramping operations
        self.take_data = False

        self._dev = PCR500MA(ip_addr=ip_addr, port=port)

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('heater_source',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('sampling_frequency', default=0.2, type=float)
    def acq(self, session, params):
        """acq(sampling_frequency=0.2)

        **Process** - Monitor power supply measurements and settings.

        Parameters
        ----------
        sampling_frequency : float, optional
            Sampling frequency in Hz, defaults to 0.2 Hz.

        Notes
        -----
        An example of the session data::

            >>> response.session['data']
            {"I_AC": 0.00475843,
             "V_AC": 0.0371215,
             "P_AC": 0.0,
             "f_AC": 60.0,
             "output": 0,
             "volt_set": 0.0,
             "timestamp": 1737367649.2595236
            }
        """
        f_sample = params.get('sampling_frequency')
        pace_maker = Pacemaker(f_sample)

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start acq because {self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            self.take_data = True
            last_release = time.time()

            while self.take_data:
                # Release lock
                if time.time() - last_release > LOCK_RELEASE_SEC:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=LOCK_RELEASE_TIMEOUT):
                        print(f'Re-acquire failed: {self.lock.job}')
                        return False, 'Could not re-acquire lock.'

                # Data acquisition
                current_time = time.time()
                data = {'timestamp': current_time, 'block_name': 'heater_source', 'data': {}}

                try:
                    i_ac = self._dev.meas_current_ac()
                    v_ac = self._dev.meas_volt_ac()
                    p_ac = self._dev.meas_power_ac()
                    f_ac = self._dev.meas_freq()
                    sw_status = self._dev.get_output()
                    volt_set = self._dev.get_volt_ac()
                    if session.degraded:
                        self.log.info('Connection re-established.')
                        session.degraded = False
                except ConnectionError:
                    self.log.error('Failed to get data from Kikusui PCR. Check network connection.')
                    session.degraded = True
                    time.sleep(1)
                    continue

                data['data']['I_AC'] = i_ac
                data['data']['V_AC'] = v_ac
                data['data']['P_AC'] = p_ac
                data['data']['f_AC'] = f_ac
                data['data']['output'] = 1 if sw_status else 0
                data['data']['volt_set'] = volt_set

                field_dict = {'I_AC': i_ac,
                              'V_AC': v_ac,
                              'P_AC': p_ac,
                              'f_AC': f_ac,
                              'output': 1 if sw_status else 0,
                              'volt_set': volt_set}

                session.data.update(field_dict)

                self.agent.publish_to_feed('heater_source', data)
                session.data.update({'timestamp': current_time})

                pace_maker.sleep()

            self.agent.feeds['heater_source'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'

    @ocs_agent.param('output', type=bool)
    @ocs_agent.param('force', default=False, type=bool)
    def set_output(self, session, params=None):
        """set_output(output, force=False)

        **Task** - Turns the output on or off.

        Parameters
        ----------
        output : bool
            True : output on
            False : output off

        force : bool, default False
            Force output on / off without checking output value.

        Notes
        -----
        This function measures the output voltage when turning off
        and checks the voltage setting when turning on by default. If the
        voltage is too high it will not change state to avoid an abrupt
        change in applied voltage.
        Set `force` option to `True` when this behavior is unwanted.
        """
        with self.lock_ramp.acquire_timeout(0, job='set_output') as control_acquired:
            if not control_acquired:
                return False, f'Control operation {self.lock_ramp.job} is already running.'
            return self._set_output(session, params)

    def _set_output(self, session, params):
        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='set_output') as acquired:
            if not acquired:
                self.log.warn('Could not start set_output because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            output_on = params['output']
            if not params['force']:
                state = self._read_voltage_state()
                try:
                    if output_on:
                        state.check_output_on()
                    else:
                        state.check_output_off()
                except PCRStateError as err:
                    return False, str(err)

            self._dev.set_output(output=output_on)

        return True, f'Set output for PCR: {params["output"]}'

    @ocs_agent.param('volt_set', type=float, check=lambda x: 0 <= x <= VOLT_ULIM_SOFT)
    @ocs_agent.param('force', default=False, type=bool)
    def set_volt_ac(self, session, params=None):
        """set_volt_ac(volt_set, force=False)

        **Task** - Set AC voltage value.

        Parameters
        ----------
        volt_set : float
            AC voltage setting in V. Values must be in range [0, 51].
        force : bool, default False
            Must be True to change the voltage immediately.
        """
        if not params['force']:
            return False, 'Use ramp_to_voltage, or pass force=True for an immediate voltage change.'

        with self.lock_ramp.acquire_timeout(0, job='set_volt_ac') as control_acquired:
            if not control_acquired:
                return False, f'Control operation {self.lock_ramp.job} is already running.'
            with self.lock.acquire_timeout(ACQ_TIMEOUT, job='set_volt_ac') as acquired:
                if not acquired:
                    return False, 'Could not acquire lock.'

                self._dev.set_volt_ac(volt=params['volt_set'])

        return True, f'Set voltage for PCR: {params["volt_set"]}'

    def _read_voltage_state(self, session=None):
        """Read fresh state with the device lock already held."""
        state = PCRState(output=self._dev.get_output(),
                         volt_set=self._dev.get_volt_ac(),
                         measured=self._dev.meas_volt_ac())
        if session is not None:
            session.data.update({'output': state.output,
                                 'volt_set': state.volt_set,
                                 'V_AC': state.measured,
                                 'timestamp': time.time()})
        return state

    def _prepare_ramp(self, session, target):
        """Prepare the output with the device lock already held.

        Return True if the zero target is reached with the output off.
        """
        if session.status == 'stopping':
            return False
        output = self._dev.get_output()
        if session.status == 'stopping' or output:
            return False

        self._dev.set_volt_ac(volt=0)
        state = self._read_voltage_state(session)
        if state.output:
            raise PCRStateError('Output turned on during ramp preparation.')
        state.check_output_on()
        if target == 0:
            return True
        if session.status == 'stopping':
            return False

        self._dev.set_output(output=True, verify=True)
        return False

    @ocs_agent.param('volt_set', type=float, check=lambda x: 0 <= x <= VOLT_ULIM_SOFT)
    def ramp_to_voltage(self, session, params=None):
        """ramp_to_voltage(volt_set)

        **Task** - Safely ramp to an AC voltage and manage the output state.

        Parameters
        ----------
        volt_set : float
            Target AC voltage in V, in the range [0, 51]. A target of zero
            ramps down and turns the output off.

        Notes
        -----
        Uses steps of at most 1 V with at least 7 seconds to settle. Fresh
        measurements must be within 1.2 V of the current and next settings.

        An inactive output is reset to zero, then enabled for nonzero
        targets only. Shutdown requires a measured voltage below 0.2 V.

        Acquisition continues; other control tasks (even forced) are
        rejected. Abort or failure leaves the last commanded state in place.
        """
        target = params['volt_set']
        session.data = {'target_voltage': target}
        with self.lock_ramp.acquire_timeout(0, job='ramp_to_voltage') as control_acquired:
            if not control_acquired:
                return False, f'Control operation {self.lock_ramp.job} is already running.'

            try:
                with self.lock.acquire_timeout(LOCK_RELEASE_TIMEOUT, job='ramp_to_voltage') as acquired:
                    if not acquired:
                        return False, 'Could not acquire lock.'
                    complete = self._prepare_ramp(session, target)
                if complete:
                    return True, 'Voltage reset to 0 V; output remains off.'

                while session.status != 'stopping':
                    with self.lock.acquire_timeout(LOCK_RELEASE_TIMEOUT, job='ramp_to_voltage') as acquired:
                        if not acquired:
                            return False, 'Could not acquire lock.'

                        state = self._read_voltage_state(session)
                        if session.status == 'stopping':
                            break

                        state.check_voltage_consistency()

                        current = state.volt_set
                        if current == target and state.output:
                            if target == 0:
                                state.check_output_off()
                                self._dev.set_output(output=False, verify=True)
                                self._read_voltage_state(session)
                            return True, f'Ramped voltage to {target} V.'

                        if target > current:
                            next_voltage = min(target, current + VOLT_STEP)
                        else:
                            next_voltage = max(target, current - VOLT_STEP)
                        state.check_voltage_step(next_voltage)
                        self._dev.set_volt_ac(volt=next_voltage, verify=True)

                    # Release the device lock while settling so acq can monitor.
                    deadline = time.monotonic() + RAMP_TIME_STEP
                    while session.status != 'stopping':
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        time.sleep(min(0.2, remaining))
            except PCRStateError as err:
                return False, str(err)
            except (ConnectionError, PCRException, ValueError) as err:
                session.degraded = True
                return False, f'Ramp stopped after a device error: {err}'

        return False, 'Voltage ramp aborted; no further changes made.'

    def _abort_ramp(self, session, params=None):
        session.set_status('stopping')
        return True, 'Requested to abort voltage ramp.'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', default=PORT_DEFAULT, type=int,
                        help='Port number for TCP communication.')
    pgroup.add_argument('--ip-address',
                        help='IP address of the device.')

    return parser


def main(args=None):
    """Boot OCS agent"""
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = site_config.add_arguments()

    parser = make_parser()
    args = site_config.parse_args(agent_class='PCR500MAAgent',
                                  parser=parser,
                                  args=args)

    agent_inst, runner = ocs_agent.init_site_agent(args)

    pcr_agent = PCR500MAAgent(agent_inst, ip_addr=args.ip_address, port=args.port)

    agent_inst.register_task(
        'set_output',
        pcr_agent.set_output
    )

    agent_inst.register_task(
        'set_volt_ac',
        pcr_agent.set_volt_ac
    )

    agent_inst.register_task(
        'ramp_to_voltage',
        pcr_agent.ramp_to_voltage,
        aborter=pcr_agent._abort_ramp
    )

    agent_inst.register_process(
        'acq',
        pcr_agent.acq,
        pcr_agent._stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
