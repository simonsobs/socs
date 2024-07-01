import argparse
import os
import shutil
import time
from pathlib import Path

import requests
import txaio
import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

# For logging
txaio.use_twisted()


class HTTPCameraAgent:
    """Grab screenshots from HTTP cameras.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    config_file : str
        Config file path relative to OCS_CONFIG_DIR

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    is_streaming : bool
        Tracks whether or not the agent is actively issuing requests to grab
        screenshots from cameras. Setting to false stops sending commands.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    """

    def __init__(self, agent, config_file):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        file_path = os.path.join(os.environ['OCS_CONFIG_DIR'], config_file)
        with open(file_path, 'r') as f:
            self.config = yaml.safe_load(f)

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('cameras',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params=None):
        """acq(test_mode=False)

        **Process** - Grab screenshots from HTTP cameras.

        Parameters
        ----------
        test_mode : bool, optional
            Run the Process loop only once. Meant only for testing.
            Default is False.

        Notes
        -----
        The most recent data collected is stored in session.data in the
        structure::

            >>> response.session['data']
            # for each camera
            {'location1': {'location': 'location1',
                         'last_attempt': 1701983575.032506,
                         'connected': True,
                         'address': '10.10.10.41'},
             'location2': ...
            }
        """
        pm = Pacemaker(1 / 60, quantize=False)

        self.is_streaming = True
        while self.is_streaming:
            # Use UTC
            timestamp = time.time()
            data = {}

            for camera in self.config['cameras']:
                data[camera['location']] = {'location': camera['location']}
                self.log.info(f"Grabbing screenshot from {camera['location']}")

                payload = {'USER': camera['user'],
                           'PWD': camera['password'],
                           'SNAPSHOT': camera['resolution']}
                url = f"http://{camera['address']}/cgi-bin/encoder"

                # Format directory and filename
                ctime = int(timestamp)
                ctime_dir = int(str(timestamp)[:5])
                Path(f"screenshots/{camera['location']}/{ctime_dir}").mkdir(parents=True, exist_ok=True)
                filename = f"screenshots/{camera['location']}/{ctime_dir}/{ctime}.jpg"
                latest_filename = f"screenshots/{camera['location']}/latest.jpg"

                # If no response from camera, update connection status and continue
                try:
                    response = requests.get(url, params=payload, stream=True, timeout=5)
                    connected = True
                except requests.exceptions.RequestException as e:
                    self.log.error(f'{e}')
                    self.log.info("Unable to get response from camera.")
                    connected = False
                    data[camera['location']]['last_attempt'] = time.time()
                    data[camera['location']]['connected'] = connected
                    continue
                camera['connected'] = True
                self.log.debug("Received screenshot from camera.")

                # Write screenshot to file and update latest file
                with open(filename, 'wb') as out_file:
                    shutil.copyfileobj(response.raw, out_file)
                self.log.debug(f"Wrote {ctime}.jpg to /{camera['location']}/{ctime_dir}.")
                shutil.copy2(filename, latest_filename)
                self.log.debug(f"Updated latest.jpg in /{camera['location']}.")
                del response

                data[camera['location']]['last_attempt'] = time.time()
                data[camera['location']]['connected'] = connected

            # Update session.data and publish to feed
            for camera in self.config['cameras']:
                data[camera['location']]['address'] = camera['address']
            session.data = data
            self.log.debug("{data}", data=session.data)

            message = {
                'block_name': 'cameras',
                'timestamp': timestamp,
                'data': {}
            }
            for camera in self.cameras:
                message['data'][camera['location'] + "_connected"] = int(connected)
            session.app.publish_to_feed('cameras', message)
            self.log.debug("{msg}", msg=message)

            if params['test_mode']:
                break
            pm.sleep()

        return True, "Finished Recording"

    def _stop_acq(self, session, params=None):
        """_stop_acq()
        **Task** - Stop task associated with acq process.
        """
        if self.is_streaming:
            session.set_status('stopping')
            self.is_streaming = False
            return True, "Stopping Recording"
        else:
            return False, "Acq is not currently running"


def add_agent_args(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--camera-addresses", type=str, help="Config file path relative to OCS_CONFIG_DIR")
    pgroup.add_argument("--mode", choices=['acq', 'test'])

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='HTTPCameraAgent',
                                  parser=parser,
                                  args=args)

    if args.mode == 'acq':
        init_params = True
    elif args.mode == 'test':
        init_params = False

    agent, runner = ocs_agent.init_site_agent(args)
    p = HTTPCameraAgent(agent,
                        config_file=args.config_file)

    agent.register_process("acq",
                           p.acq,
                           p._stop_acq,
                           startup=init_params)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
