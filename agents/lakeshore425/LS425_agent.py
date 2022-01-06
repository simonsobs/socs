import time
import os
import argparse
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
import Lakeshore425 as ls 

txaio.use_twisted()

class LS425Agent:
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
    def init_lakeshore_task(self, session, params=None):
        """init_lakeshore_task(params=None)
        Perform first time setup of the Lakeshore 425 Module.
        Args:
            params (dict): Parameters dictionary for passing parameters to task.
        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.
        """

        if params is None:
            params = {}

        auto_acquire = params.get('auto_acquire', False)

        if self.initialized:
            return True, "Already Initialized Module"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('starting')

            self.dev = ls.LakeShore425(self.port)
            self.log.info(self.dev.get_id())
            print("Initialized Lakeshore module: {!s}".format(self.dev))

        self.initialized = True
        # Start data acquisition if requested
        if auto_acquire:
            self.agent.start('acq')

        return True, 'Lakeshore module initialized.'

    def start_acq(self, session, params=None):
        """acq(sampling_frequency=1.)
        **Process** - Acquire data from the Lakeshore 425.
        Parameters:
            sampling_frequency (float):
                Sampling frequency for data collection. Defaults to 1.0 Hz
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

        f_sample = params.get('sampling_frequency')
        # If f_sample is None, use value passed to Agent init
        if f_sample is None:
            f_sample = self.f_sample

        sleep_time = 1/f_sample - 0.01

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True

            session.data = {"fields": {}}

            while self.take_data:
                Bfield = self.dev.get_field()
                current_time = time.time()
                data = {
                    'timestamp': current_time,
                    'block_name': 'mag_field',
                    'data': {'Bfield':Bfield}
                }

                self.agent.publish_to_feed('mag_field', data)
                session.data.update({'timestamp': current_time})
                self.agent.feeds['mag_field'].flush_buffer()

                time.sleep(sleep_time)

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    def operational_status(self, session, params=None):
        """
        check operational status.
        """
        with self.lock.acquire_timeout(0, job = 'any_command') as acquired:
            if not acquired:
                self.log.warn('Could not any_command because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            op_status = self.dev.get_op_status()
            self.log.info(op_status)
            return True, 'operational status: '+op_status

    def zero_calibration(self, session, params=None):
        """
        calibrate zero point.
        """
        with self.lock.acquire_timeout(0, job = 'any_command') as acquired:
            if not acquired:
                self.log.warn('Could not any_command because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            self.dev.set_zero()
            return True, 'Zero calibration is done'

    @ocs_agent.param('command', type=str)
    def any_command(self, session, params=None):
        """
        any_command(command='*IDN?')
        **Process** - Send serial command to Lakeshore 425
        Parameters:
            command (str): any serial command
        """
        command = params['command']
        with self.lock.acquire_timeout(0, job = 'any_command') as acquired:
            if not acquired:
                self.log.warn('Could not any_command because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            print('Input command: ' + command)
            if '?' in command:
                out = self.dev.query(command)
                return True, 'any_command is finished cleanly. Results: {}'.format(out)
            else:
                self.dev.command(command)
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

def main():
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='Lakeshore425Agent', parser=parser)

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

    agent.register_task('init_lakeshore', gauss.init_lakeshore_task, startup=init_params)
    agent.register_task('operational_status', gauss.operational_status)
    agent.register_task('zero_calibration', gauss.zero_calibration)
    agent.register_task('any_command', gauss.any_command)
    agent.register_process('acq', gauss.start_acq, gauss.stop_acq)

    runner.run(agent, auto_reconnect=True)

if __name__ == '__main__':
    main()
