import argparse
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

# For logging
txaio.use_twisted()


class SiteCameraAgent:
    """Grab screenshots from ACTi site cameras.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    camera_addresses : list
        List of IP addresses (as strings) of cameras.
    user : str
        Username of cameras.
    password : str
        Password of cameras.

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    is_streaming : bool
        Tracks whether or not the agent is actively issuing SNMP GET commands
        to the UPS. Setting to false stops sending commands.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    """

    def __init__(self, agent, camera_addresses, user, password):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        self.cameras = []
        for camera in camera_addresses:
            self.cameras.append({'address': camera,
                                 'connected': True})
        self.user = user
        self.password = password

        self.lastGet = 0

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('cameras',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params=None):
        """acq()

        **Process** - Fetch values from the UPS via SNMP.

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
            {'camera1_last_attempt': 1701983575.032506,
             'camera1_connected': True,
             'camera1_address': '10.10.10.41'}
        """

        session.set_status('running')
        self.is_streaming = True
        count = 0
        while self.is_streaming:
            current_time = time.time()
            # Check if 60 seconds has passed before getting screenshot
            if (current_time - self.lastGet) < 60:
                continue

            # Use UTC
            timestamp = datetime.now(timezone.utc).replace(tzinfo=timezone.utc).timestamp()
            data = {
                'block_name': 'cameras',
                'timestamp': timestamp,
                'data': {}
            }

            count += 1
            for i, camera in enumerate(self.cameras):
                self.log.info(f"Grabbing screenshot from {camera['address']}")
                payload = {'USER': self.user,
                           'PWD': self.password,
                           'SNAPSHOT': 'N640x480,100',
                           'DUMMY': count}
                url = f"http://{camera['address']}/cgi-bin/encoder"

                Path(f"screenshots/{camera['address']}").mkdir(parents=True, exist_ok=True)
                date = datetime.now(timezone.utc)
                date_string = date.strftime("%Y_%m_%d@%H%M%S")
                filename = f"screenshots/{camera['address']}/{date_string}.jpg"
                latest_filename = f"screenshots/{camera['address']}/latest.jpg"

                # If no response from camera, update connection status and continue
                try:
                    response = requests.get(url, params=payload, stream=True, timeout=5)
                except requests.exceptions.RequestException as e:
                    self.log.error(f'{e}')
                    self.log.info("Unable to get response from camera.")
                    self.cameras[i]['connected'] = False
                    data['data'][f"camera{i+1}_last_attempt"] = date.replace(tzinfo=timezone.utc).timestamp()
                    data['data'][f"camera{i+1}_connected"] = self.cameras[i]['connected']
                    continue
                self.cameras[i]['connected'] = True
                self.log.debug("Received screenshot from camera.")

                # Write screenshot to file and update latest file
                with open(filename, 'wb') as out_file:
                    shutil.copyfileobj(response.raw, out_file)
                shutil.copy2(filename, latest_filename)
                del response
                self.log.debug(f"Wrote {date_string}.jpg to /{camera['address']}.")

                data['data'][f"camera{i+1}_last_attempt"] = date.replace(tzinfo=timezone.utc).timestamp()
                data['data'][f"camera{i+1}_connected"] = self.cameras[i]['connected']

            # Update session.data and publish to feed
            session.data = data['data']
            session.app.publish_to_feed('cameras', data)
            for camera in self.cameras:
                session.data.update({f"camera{i+1}_address": camera['address']})
            self.log.debug("{data}", data=session.data)

            self.lastGet = time.time()

            if params['test_mode']:
                break

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
    pgroup.add_argument("--camera-addresses", nargs='+', type=str, help="List of camera IP addresses.")
    pgroup.add_argument("--user", help="Username of camera.")
    pgroup.add_argument("--password", help="Password of camera.")
    pgroup.add_argument("--mode", choices=['acq', 'test'])

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='SiteCameraAgent',
                                  parser=parser,
                                  args=args)

    if args.mode == 'acq':
        init_params = True
    elif args.mode == 'test':
        init_params = False

    agent, runner = ocs_agent.init_site_agent(args)
    p = SiteCameraAgent(agent,
                        camera_addresses=args.camera_addresses,
                        user=args.user,
                        password=args.password,)

    agent.register_process("acq",
                           p.acq,
                           p._stop_acq,
                           startup=init_params, blocking=False)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
