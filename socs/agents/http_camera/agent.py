import argparse
import json
import os
import shutil
import time
from pathlib import Path

import requests
import txaio
import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock
# Disable unverified HTTPS warnings (https://urllib3.readthedocs.io/en/latest/advanced-usage.html#ssl-warnings)
from urllib3.exceptions import InsecureRequestWarning, ReadTimeoutError

requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

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

    def __init__(self, agent, config_file, renew_token=2700):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        file_path = os.path.join(os.environ['OCS_CONFIG_DIR'], config_file)
        with open(file_path, 'r') as f:
            self.config = yaml.safe_load(f)

        self.renew_token = renew_token

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
            pm.sleep()
            # Use UTC
            timestamp = time.time()
            data = {}

            for camera in self.config['cameras']:
                data[camera['location']] = {'location': camera['location']}
                self.log.info(f"Grabbing screenshot from {camera['location']}")

                if camera['brand'] == 'reolink':
                    token = camera.get('token', None)
                    token_ts = camera.get('token_ts', 0)
                    # Token lease time is 1hr.
                    expired = (timestamp - token_ts) > self.renew_token
                    if token is None or expired:
                        login_url = f"https://{camera['address']}/api.cgi?cmd=Login"
                        login_payload = [{"cmd": "Login",
                                          "param": {"User":
                                                    {"Version": 0,
                                                     "userName": camera['user'],
                                                     "password": camera['password']}}}]
                        try:
                            resp = requests.post(login_url, data=json.dumps(login_payload), verify=False)
                        except (requests.exceptions.ConnectionError, requests.exceptions.RequestException, ReadTimeoutError) as e:
                            self.log.error(f'{e}')
                            self.log.info("Unable to get response from camera.")
                            data[camera['location']]['last_attempt'] = time.time()
                            data[camera['location']]['connected'] = False
                            continue
                        rdata = resp.json()
                        value = rdata[0].get('value', None)
                        if value is None:
                            self.log.info("Unable to get token. Max number of tokens used.")
                            data[camera['location']]['last_attempt'] = time.time()
                            data[camera['location']]['connected'] = False
                            continue
                        camera['token'] = value['Token']['name']
                        camera['token_ts'] = timestamp

                    payload = {'cmd': "Snap",
                               'channel': "0",
                               'rs': "flsYJfZgM6RTB_os",
                               'token': camera['token']}
                    url = f"https://{camera['address']}/cgi-bin/api.cgi"
                elif camera['brand'] == 'acti':
                    payload = {'USER': camera['user'],
                               'PWD': camera['password'],
                               'SNAPSHOT': camera.get('resolution', 'N640x480,100')}
                    url = f"http://{camera['address']}/cgi-bin/encoder"
                else:
                    self.log.info(f"{camera['brand']} is an unsupported camera brand. Skipping this config block.")
                    self.config['cameras'].remove(camera)
                    continue

                # Format directory and filename
                ctime = int(timestamp)
                ctime_dir = int(str(timestamp)[:5])
                Path(f"screenshots/{camera['location']}/{ctime_dir}").mkdir(parents=True, exist_ok=True)
                filename = f"screenshots/{camera['location']}/{ctime_dir}/{ctime}.jpg"
                latest_filename = f"screenshots/{camera['location']}/latest.jpg"

                # If no response from camera, update connection status and continue
                try:
                    if camera['brand'] == 'reolink':
                        response = requests.get(url, params=payload, stream=True, timeout=5, verify=False)
                    elif camera['brand'] == 'acti':
                        response = requests.get(url, params=payload, stream=True, timeout=5)
                except (requests.exceptions.ConnectionError, requests.exceptions.RequestException, ReadTimeoutError) as e:
                    self.log.error(f'{e}')
                    self.log.info("Unable to get response from camera.")
                    data[camera['location']]['last_attempt'] = time.time()
                    data[camera['location']]['connected'] = False
                    continue
                self.log.debug("Received screenshot from camera.")

                # Write screenshot to file and update latest file
                try:
                    with open(filename, 'wb') as out_file:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                out_file.write(chunk)
                        out_file.flush()
                        os.fsync(out_file.fileno())
                    self.log.debug(f"Wrote {ctime}.jpg to /{camera['location']}/{ctime_dir}.")
                except (requests.exceptions.ConnectionError, requests.exceptions.RequestException, ReadTimeoutError) as e:
                    self.log.error(f'{e}')
                    self.log.info("Timeout occurred while writing to file.")
                    data[camera['location']]['last_attempt'] = time.time()
                    data[camera['location']]['connected'] = False
                    continue
                except Exception as e:
                    self.log.error(f'{e}')
                    self.log.info("Unexpected error occurred while writing to file.")
                    data[camera['location']]['last_attempt'] = time.time()
                    data[camera['location']]['connected'] = False
                    continue
                finally:
                    response.close()
                shutil.copy2(filename, latest_filename)
                self.log.debug(f"Updated latest.jpg in /{camera['location']}.")

                data[camera['location']]['last_attempt'] = time.time()
                data[camera['location']]['connected'] = True

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
            for camera in self.config['cameras']:
                message['data'][camera['location'] + "_connected"] = int(data[camera['location']]['connected'])
            session.app.publish_to_feed('cameras', message)
            self.log.debug("{msg}", msg=message)

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
    pgroup.add_argument("--config-file", type=str, help="Config file path relative to OCS_CONFIG_DIR")
    pgroup.add_argument("--mode", choices=['acq', 'test'])
    pgroup.add_argument("--renew-token", type=int, default=2700,
                        help="Renew API token after this amount of seconds. Used for Reolink cameras.")

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
                        config_file=args.config_file,
                        renew_token=args.renew_token)

    agent.register_process("acq",
                           p.acq,
                           p._stop_acq,
                           startup=init_params)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
