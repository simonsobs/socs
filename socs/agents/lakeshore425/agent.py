import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.Lakeshore import Lakeshore425 as ls

txaio.use_twisted()


class LS425Agent:
    """Agent for interfacing with a single Lakeshore 425 device.

    Args:
        agent (ocs.ocs_agent.OCSAgent): Instantiated OCSAgent class for this Agent
        port (int): Path to USB device in `/dev/`
        f_sample (float): Default sampling rate for the acq Process

    """

    def __init__(self, agent, port, f_sample=1.):

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.port = port
        self.dev = None

        self.f_sample = f_sample

        self.initialized = False
        self.take_data = False

        # Registers Temperature and Voltage feeds
        agg_params = {'frame_length': 60}
        self.agent.register_feed('mag_field',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    # Task functions.
    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_lakeshore(self, session, params):
        """init_lakeshore(auto_acquire=False)

        **Task** - Perform first time setup of the Lakeshore 425 Module.

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.

        """
        if params is None:
            params = {}

        auto_acquire = params['auto_acquire']

        if self.initialized:
            return True, "Already Initialized Module"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            self.dev = ls.LakeShore425(self.port)
            self.log.info(self.dev.get_id())
            print("Initialized Lakeshore module: {!s}".format(self.dev))

        self.initialized = True
        # Start data acquisition if requested
        if auto_acquire:
            self.agent.start('acq', params={'sampling_frequency': self.f_sample})

        return True, 'Lakeshore module initialized.'

    @ocs_agent.param('sampling_frequency', default=None, type=float)
    def acq(self, session, params):
        """acq(sampling_frequency=None)

        **Process** - Acquire data from the Lakeshore 425.

        Parameters:
            sampling_frequency (float, optional):
                Sampling frequency for data collection. Defaults to the value
                passed to `--sampling_frequency` on Agent startup

        Notes:
            The most recent data collected is stored in session data in the
            structure::

                >>> response.session['data']
                {"fields":
                    {"mag_field": {"Bfield": 270.644},
                     "timestamp": 1601924466.6130798}
                }

        """
        if params is None:
            params = {}

        f_sample = params['sampling_frequency']
        # If f_sample is None, use value passed to Agent init
        if f_sample is None:
            f_sample = self.f_sample

        sleep_time = 1 / f_sample - 0.01

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            self.take_data = True

            session.data = {"fields": {}}

            last_release = time.time()
            while self.take_data:
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire lock, currently held by {self.lock.job}.")
                        continue

                Bfield = self.dev.get_field()
                current_time = time.time()
                data = {
                    'timestamp': current_time,
                    'block_name': 'mag_field',
                    'data': {'Bfield': Bfield}
                }

                self.agent.publish_to_feed('mag_field', data)
                session.data.update({'timestamp': current_time})
                self.agent.feeds['mag_field'].flush_buffer()

                time.sleep(sleep_time)

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        """
        Stops acq process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    @ocs_agent.param('_')
    def operational_status(self, session, params):
        """operational_status()

        **Task** - Check operational status.

        """
        with self.lock.acquire_timeout(3, job='operational_status') as acquired:
            if not acquired:
                self.log.warn('Could not start operational_status because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            op_status = self.dev.get_op_status()
            self.log.info(op_status)
            return True, 'operational status: ' + op_status

    @ocs_agent.param('_')
    def zero_calibration(self, session, params):
        """zero_calibration()

        **Task** - Calibrate the zero point.

        """
        with self.lock.acquire_timeout(3, job='zero_calibration') as acquired:
            if not acquired:
                self.log.warn('Could not start zero_calibration because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            self.dev.set_zero()
            return True, 'Zero calibration is done'

    @ocs_agent.param('command', type=str)
    def any_command(self, session, params):
        """any_command(command)

        **Process** - Send serial command to Lakeshore 425

        Parameters:
            command (str): any serial command

        Examples:
            Example for calling in a client::

                >>> client.any_command(command='*IDN?')

        Notes:
            An example of the session data::

                >>> response.session['data']
                {'response': 'LSA1234'}

        """
        command = params['command']
        with self.lock.acquire_timeout(3, job='any_command') as acquired:
            if not acquired:
                self.log.warn('Could not any_command because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            print('Input command: ' + command)
            if '?' in command:
                out = self.dev.query(command)
                session.data = {'response': out}
                return True, 'any_command is finished cleanly. Results: {}'.format(out)
            else:
                self.dev.command(command)
                session.data = {'response': None}
                return True, 'any_command is finished cleanly'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', type=str,
                        help="Path to USB node for the lakeshore")
    pgroup.add_argument('--mode', type=str, choices=['init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument('--sampling-frequency', type=float,
                        help="Sampling frequency for data acquisition")
    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='Lakeshore425Agent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    kwargs = {'port': args.port}

    if args.sampling_frequency is not None:
        kwargs['f_sample'] = float(args.sampling_frequency)
    gauss = LS425Agent(agent, **kwargs)

    agent.register_task('init_lakeshore', gauss.init_lakeshore, startup=init_params)
    agent.register_task('operational_status', gauss.operational_status)
    agent.register_task('zero_calibration', gauss.zero_calibration)
    agent.register_task('any_command', gauss.any_command)
    agent.register_process('acq', gauss.acq, gauss._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
