import argparse
import time
from dataclasses import dataclass
from queue import Queue

import serial
import txaio
from twisted.internet import defer, reactor, threads

txaio.use_twisted()

from ocs import ocs_agent, site_config

import socs.agents.hwp_pcu.drivers.hwp_pcu as pcu
from socs.agents.hwp_supervisor.agent import get_op_data


class Actions:
    class BaseAction:
        def __post_init__(self):
            self.deferred = defer.Deferred()
            self.log = txaio.make_logger()

    @dataclass
    class SendCommand (BaseAction):
        command: str


def process_action(action, PCU: pcu.PCU):
    """Process an action with PCU hardware"""
    if isinstance(action, Actions.SendCommand):
        PCU.send_command(action.command)
        action.log.info(f"Command: {action.command}")


class HWPPCUAgent:
    """Agent to phase compensation improve the CHWP motor efficiency

    Args:
        agent (ocs.ocs_agent.OCSAgent): Instantiated OCSAgent class for this agent
        port (str): Path to USB device in '/dev/'
    """

    def __init__(self, agent, port, supervisor_id=None, no_data_timeout=15 * 60):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.port = port
        self.action_queue = Queue()

        self.shutdown_mode = False
        self.supervisor_id = supervisor_id
        self.no_data_timeout = no_data_timeout

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'hwppcu', record=True, agg_params=agg_params)

    @defer.inlineCallbacks
    @ocs_agent.param('command', default='off', type=str, choices=['off', 'on_1', 'on_2', 'stop'])
    def send_command(self, session, params):
        """send_command(command)

        **Task** - Send commands to the phase compensation unit.
        off: The compensation phase is zero.
        on_1: The compensation phase is +120 deg.
        on_2: The compensation phase is -120 deg.
        stop: Stop the HWP spin.

        Parameters:
            command (str): set the operation mode from 'off', 'on_1', 'on_2' or 'stop'.

        """
        action = Actions.SendCommand(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, f"Set relays for cmd={action.command}"

    def _process_actions(self, PCU: pcu.PCU):
        while not self.action_queue.empty():
            action = self.action_queue.get()
            if action.__class__.__name__ in ['SendCommand']:
                if self.shutdown_mode:
                    self.log.warn("Shutdown mode is in effect")
                    action.deferred.errback(Exception("Action cancelled by shutdown mode"))
            try:
                self.log.info(f"Running action {action}")
                res = process_action(action, PCU)
                reactor.callFromThread(action.deferred.callback, res)
            except Exception as e:
                self.log.error(f"Error processing action: {action}")
                reactor.callFromThread(action.deferred.errback, e)

    def _get_and_publish_data(self, PCU: pcu.PCU, session):
        now = time.time()
        data = {'timestamp': now,
                'block_name': 'hwppcu',
                'data': {}}
        status = PCU.get_status()

        data['data']['status'] = status
        self.agent.publish_to_feed('hwppcu', data)
        session.data = {'status': status, 'last_updated': now}

        if status in ['failed', 'undefined']:
            PCU.clear_buffer()
            self.log.warn(f'Status is {status}, cleared buffer')

    def _clear_queue(self):
        while not self.action_queue.empty():
            action = self.action_queue.get()
            action.deferred.errback(Exception("Action cancelled"))

    @defer.inlineCallbacks
    def initiate_shutdown(self, session, params):
        """initiate_shutdown()
        **Task** - Initiate the shutdown of the agent
        """
        self.log.warn("INITIATING SHUTDOWN")

        action = Actions.SendCommand(command = 'stop')
        self.action_queue.put(action)
        session.data = yield action.deferred
        self.shutdown_mode = True
        return True, "Initiated shutdown mode"

    def cancel_shutdown(self, session, params):
        """cancel_shutdown()
        **Task** - Cancels shutdown mode, allowing other tasks to update the PCU
        """
        self.shutdown_mode = False
        return True, "Cancelled shutdown mode"

    def main(self, session, params):
        """
        **Process** - Main process for PCU agent.
        """
        PCU = None

        threads.blockingCallFromThread(reactor, self._clear_queue)

        last_daq = 0
        while session.status in ['starting', 'running']:
            if PCU is None:
                try:
                    PCU = pcu.PCU(port=self.port)
                    self.log.info('Connected to PCU')
                    PCU.clear_buffer()
                    self.log.info('Cleared buffer')
                except (ConnectionRefusedError, serial.serialutil.SerialException):
                    self.log.error(
                        "Could not connect to PCU. "
                        "Retrying after 30 sec..."
                    )
                    time.sleep(30)
                    continue
            try:
                now = time.time()
                if now - last_daq > 5:
                    self._get_and_publish_data(PCU, session)
                    last_daq = now

                self._process_actions(PCU)
                session.degraded = False
                time.sleep(0.1)
            except serial.serialutil.SerialException:
                self.log.error(
                    "Decive reports readiness to read but returned no data. "
                    "Reconnect to PCU."
                )
                PCU.close()
                PCU = None
                session.degraded = True

        PCU.close()

    def _stop_main(self, session, params):
        """
        Stop acq process.
        """
        session.set_status('stopping')
        return True, 'Set main status to stopping'

    def monitor_supervisor(self, session, params):
        """monitor_supervisor()

        **Process** - This is a process that is constantly running to monitor the
        HWP supervisor and the course of action recommended by the HWP supervisor.
        If certain conditions are met, this will trigger a shutdown and force the
        PCU into the 'stop' state.
        """

        last_ok_time = time.time()

        if self.supervisor_id is None:
            return False, "No supervisor ID set"

        while session.status in ['starting', 'running']:
            res = get_op_data(self.supervisor_id, 'monitor')
            if res['status'] != 'ok':
                action = 'no_data'
            else:
                action = res['data']['actions']['pmx']

            # If action is 'ok', update last_ok_time
            if action == 'ok':
                last_ok_time = time.time()

            # If action is 'no_data', check if last_ok_time, and potentially trigger shutdown
            elif action == 'no_data':
                if (time.time() - last_ok_time) > self.no_data_timeout:
                    if not self.shutdown_mode:
                        self.agent.start('initiate_shutdown')

            # If action is 'shutdown', trigger a shutdown
            elif action == 'stop':
                if not self.shutdown_mode:
                    self.agent.start('initiate_shutdown')

            data = {
                'data': {'rotation_action': action},
                'block_name': 'rotation_action',
                'timestamp': time.time()
            }

            self.agent.publish_to_feed('rotation_action', data)
            session.data = {
                'rotation_action': action
                'time': time.time()
            }

            time.sleep(1)

        return True, 'Supervisor monitor has exited'

    def _stop_monitor_supervisor(self, session, params):
        session.set_status('stopping')
        return True, 'Stopping monitor shutdown'


def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically build documentation
    baised on this function
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', type=str, help="Path to USB node for the PCU")
    pgroup.add_argument('--supevisor-id', type=str, default=None
                        help="Instance ID for HWP Supervisor agent")
    pgroup.add_argument('--no-data-timeout', type=float, default=15 * 60, 
                        help="Time (sec) after which a 'no_data' action should "
                             "trigger a shutdown")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPPCUAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    hwppcu_agent = HWPPCUAgent(agent,
                               port=args.port, supervisor_id=args.supervisor_id,
                               no_data_timeout=args.no_data_timeout)
    agent.register_task('send_command', hwppcu_agent.send_command, blocking=False)
    agent.register_task('initiate_shutdown', hwppcu_agent.initiate_shutdown, blocking=False)
    agent.register_task('cancel_shutdown', hwppcu_agent.cancel_shutdown, blocking=False)
    agent.register_process(
        'main', hwppcu_agent.main, hwppcu_agent._stop_main, startup=True)
    agent.register_process(
        'monitor_supervisor', hwppcu_agent.monitor_supervisor,
        hwppcu_agent._stop_monitor_supevisor, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
