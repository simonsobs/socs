
import argparse
import time
from ocs import ocs_agent, site_config

from socs.agents.hwp_rotation.agent import RotationAgent
from socs.agents.hwp_encoder.agent import HWPBBBAgent
from socs.agents.hwp_supervisor.agent import HWPSupervisorAgent
from socs.agents.hwp_gripper.agent import GripperAgent

class HWPAgent:
    """
    Agent for grouping together all of the HWP functionality. This combines
    all HWP actions into a single agent, and allows for the creation of
    operations that command HWP subsystems without communicating over crossbar.
    """
    def __init__(self, agent, args):
        self.agent = agent

        self.rotation = RotationAgent(
            agent, args.kikusui_ip, args.kikusui_port, args.pid_ip,
            args.pid_port, args.pid_verbosity
        )
        self.encoder = HWPBBBAgent(agent, port=args.encoder_port)
        self.gripper = GripperAgent(agent, args.mcu_ip, args.pru_port, args.control_port)
        self.supervisor = HWPSupervisorAgent(agent, args.supervisor_cfg)

    def shutdown(self, session, params):
        """shutdown()

        **Task** - Shutdown the HWP system
        """
                # make into params?
        WAIT_TIME = 30
        MAX_WAIT = 40
        total_wait = 0  # minutes

        session.set_status('running')

        # perform shutdown operations
        # stop the rotation of hwp
        self.agent.start('set_off', params={})

        # wait for X minutes
        time.sleep(WAIT_TIME * 60)
        total_wait += WAIT_TIME

        # confirm hwp is stopped
        hwp_freq = self.encoder.hwp_freq
        last_updated = self.encoder.ct

        # check for valid/recent encoder data
        if hwp_freq == -1:
            return False, 'approx_hwp_freq = -1, hwp freq unknown, aborting...'
        if time.time() - last_updated > 60:
            return False, 'encoder data is stale, unknown hwp state'

        # wait a few more minutes if hwp hasn't stopped
        while total_wait < MAX_WAIT:
            if self.encoder.hwp_freq == 0:
                break

            time.sleep(1 * 60)
            total_wait += 1

        # failed to stop, don't grip
        if self.encoder.hwp_freq > 0:
            return False, 'HWP failed to shutdown, still rotating after ' + \
                f'{MAX_WAIT} minutes'

        # grip the hwp in safe position
        params = {'mode': 'PUSH', 'actuator': 0, 'distance': 5}
        self.agent.start('grip_move', params=params)
        self.agent.wait('grip_move')

        params['actuator'] = 1
        self.agent.start('grip_move', params=params)
        self.agent.wait('grip_move')

        params['actuator'] = 2
        self.agent.start('grip_move', params=params)
        self.agent.wait('grip_move')

        return True, 'HWP shutdown procedure completed'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent
    pgroup = parser.add_argument_group('Rotation Agent Options')
    pgroup.add_argument('--kikusui-ip')
    pgroup.add_argument('--kikusui-port')
    pgroup.add_argument('--pid-ip')
    pgroup.add_argument('--pid-port')
    pgroup.add_argument('--verbose', '-v', action='count', default=0,
                        help='PID Controller verbosity level.')
    pgroup.add_argument('--rotation-mode', type=str, default='iv_acq',
                        choices=['idle', 'init', 'iv_acq'],
                        help="Starting operation for the Agent.")

    pgroup = parser.add_argument_group('Encoder Agent Options')
    pgroup.add_argument('--encoder-port', type=int, default=8080)

    pgroup = parser.add_argument_group('Supervisor Agent Options')
    pgroup.add_argument('--supervisor-cfg', type=str,
                        help="Path to supervisor configuration file, relative to OCS_CONFIG_DIR.")
    pgroup.add_argument('--supervisor-mode', type=str, default='monitor',
                        choices=['idle', 'monitor'],
                        help="Starting action for the Agent.")

    pgroup = parser.add_argument_group('Rotation Agent Options')
    pgroup.add_argument('--mcu_ip')
    pgroup.add_argument('--pru_port')
    pgroup.add_argument('--control_port')

    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPAgent', parser=parser)
    agent, runner = ocs_agent.init_site_agent(args)
    hwp_agent = HWPAgent(agent, args)

    # HWP Rotation operations
    rot_init_params = False
    if args.rotation_mode == 'init':
        rot_init_params = {'auto_acquire': False}
    elif args.rotation_mode == 'iv_acq':
        rot_init_params = {'auto_acquire': True}
    agent.register_process(
        'rot_iv_acq', hwp_agent.rotation.iv_acq, hwp_agent.rotation.stop_iv_acq
    )
    agent.register_task(
        'init_connection', hwp_agent.rotation.init_connection,
        startup=rot_init_params
    )
    agent.register_task('tune_stop', hwp_agent.rotation.tune_stop)
    agent.register_task('tune_freq', hwp_agent.rotation.tune_freq)
    agent.register_task('declare_freq', hwp_agent.rotation.declare_freq)
    agent.register_task('set_pid', hwp_agent.rotation.set_pid)
    agent.register_task('get_freq', hwp_agent.rotation.get_freq)
    agent.register_task('get_direction', hwp_agent.rotation.get_direction)
    agent.register_task('set_direction', hwp_agent.rotation.set_direction)
    agent.register_task('set_scale', hwp_agent.rotation.set_scale)
    agent.register_task('set_on', hwp_agent.rotation.set_on)
    agent.register_task('set_off', hwp_agent.rotation.set_off)
    agent.register_task('set_v', hwp_agent.rotation.set_v)
    agent.register_task('set_v_lim', hwp_agent.rotation.set_v_lim)
    agent.register_task('use_ext', hwp_agent.rotation.use_ext)
    agent.register_task('ign_ext', hwp_agent.rotation.ign_ext)

    # HWP Encoder operations
    agent.register_process(
        'encoder_acq', hwp_agent.encoder.acq, hwp_agent.encoder._stop_acq,
        startup=True
    )

    # HWP Gripper operations
    agent.register_task('grip_on', hwp_agent.gripper.grip_on)
    agent.register_task('grip_off', hwp_agent.gripper.grip_off)
    agent.register_task('grip_brake', hwp_agent.gripper.grip_brake)
    agent.register_task('grip_move', hwp_agent.gripper.grip_move)
    agent.register_task('grip_home', hwp_agent.gripper.grip_home)
    agent.register_task('grip_inp', hwp_agent.gripper.grip_inp)
    agent.register_task('grip_alarm', hwp_agent.gripper.grip_alarm)
    agent.register_task('grip_reset', hwp_agent.gripper.grip_reset)
    agent.register_task('grip_act', hwp_agent.gripper.grip_act)
    agent.register_task('grip_mode', hwp_agent.gripper.grip_mode)
    agent.register_task('grip_force', hwp_agent.gripper.grip_force)

    agent.register_process(
        'monitor', hwp_agent.supervisor.monitor,
        hwp_agent.supervisor._stop_monitor, startup=args.supervisor_mode
    )

    agent.register_task('shutdown', hwp_agent.shutdown)

    runner.run(agent)
