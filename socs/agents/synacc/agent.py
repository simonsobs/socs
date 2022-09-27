#!/usr/bin/env python
import argparse
import time

import requests
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock


class SynaccessAgent:
    def __init__(self, agent, ip_address, username, password):
        """
        Initializes the class variables

        Args:
            ip_address(str): IP Address for the agent.
            username(str): username credential to login to strip
            password(str): password credential to login to strip
        """
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.ip_address = ip_address
        self.user = username
        self.passw = password

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'synaccess', record=True, agg_params=agg_params)

    def __get_status(self):
        req = "http://" + self.user + ":" + self.passw + "@" +\
            self.ip_address + "/cmd.cgi?$A5"
        r = requests.get(req)
        resp = r.content.decode()[:-6:-1]  # get last 5 elements, in reverse
        return resp

    def get_status(self, session, params=None):
        with self.lock.acquire_timeout(3, job='get_status') as acquired:
            if acquired:
                resp = self.__get_status()
                ret_str = []
                for x in resp:
                    if x == '1':
                        ret_str.append('on')
                    else:
                        ret_str.append('off')
                return True, 'status outlet [1,2,3,4,5] is {}'.format(ret_str)
            else:
                return False, "Could not acquire lock"

    def reboot(self, session, params=None):
        with self.lock.acquire_timeout(3, job='reboot') as acquired:
            if acquired:
                req = "http://" + self.user + ":" + \
                    self.passw + "@" + self.ip_address + \
                    "/cmd.cgi?$A4" + " " + str(params['outlet'])
                requests.get(req)
                return True, 'Rebooted outlet {}'.format(params['outlet'])
            else:
                return False, "Could not acquire lock"

    def set_outlet(self, session, params=None):
        """
        Sets a particular outlet to on/off

        Args:
            outlet (int): the outlet that we are changing the state of
            on (bool): the new state
        """
        with self.lock.acquire_timeout(3, job='set_outlet') as acquired:
            if acquired:
                if params['on']:
                    on = "1"
                else:
                    on = "0"
                req = "http://" + self.user + ":" + self.passw + "@" + \
                    self.ip_address + "/cmd.cgi?$A3" + " " + \
                    str(params['outlet']) + " " + on
                requests.get(req)
                return True, 'Set outlet {} to {}'.\
                    format(params['outlet'], params['on'])
            else:
                return False, "Could not acquire lock"

    def set_all(self, session, params=None):
        """

        Sets all outlets to on/off

        Args:
            on (bool): the new state

        """
        with self.lock.acquire_timeout(3, job='set_all') as acquired:
            if acquired:
                on = "0"
                if params['on']:
                    on = "1"
                req = "http://" + self.user + ":" + self.passw + "@" +\
                    self.ip_address + "/cmd.cgi?$A7" + " " + on
                requests.get(req)
                return True, 'Set all outlets to {}'.format(params['on'])
            else:
                return False, "Could not acquire lock"

    def status_acq(self, session, params=None):
        """status_acq()

        **Process** - Method to start data acquisition process.

        Notes:
            The most recent data collected is stored in session.data in the
            structure::

                >>> response.session['data']
                {"fields":
                    {synaccess:
                        {0: 0 or 1, (0: OFF, 1:ON)
                         1: 0 or 1, (0: OFF, 1:ON)
                         2: 0 or 1, (0: OFF, 1:ON)
                         3: 0 or 1, (0: OFF, 1:ON)
                         4: 0 or 1, (0: OFF, 1:ON)
                        }
                    }
                }

        """

        with self.lock.acquire_timeout(timeout=3, job='status_acq')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'Could not start status acq because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock'

            session.set_status('running')

            self.take_data = True
            last_release = time.time()
            session.data = {'fields': {}}
            while self.take_data:
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(
                            'Could not re-acquire lock now held by {}.'
                            .format(self.lock.job))
                        return False, 'Could not re-acquire lock (timeout)'

                current_time = time.time()
                data = {'timestamp': current_time,
                        'block_name': 'synaccess_status',
                        'data': {}}

                status_dict = {}
                resp = self.__get_status()
                for i, x in enumerate(resp):
                    if x == '1':
                        status = 1
                    else:
                        status = 0
                    data['data']['synaccess_%d' % i] = status
                    status_dict['%d' % i] = status
                self.agent.publish_to_feed('synaccess', data)
                field_dict = {'synaccess': status_dict}
                session.data['timestamp'] = current_time
                session.data['fields'] = field_dict

                time.sleep(1)  # DAQ interval
                # End of while loop

        self.agent.feeds['synaccess'].flush_buffer()
        return True, 'Acqusition exited cleanly'

    def stop_status_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data'

        return False, 'acq is not currently running'


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--username')
    pgroup.add_argument('--password')
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='SynaccessAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    p = SynaccessAgent(agent,
                       ip_address=args.ip_address,
                       username=args.username,
                       password=args.password)
    agent.register_process('status_acq', p.status_acq,
                           p.stop_status_acq, startup=True)
    agent.register_task('get_status', p.get_status, startup={})
    agent.register_task('reboot', p.reboot)
    agent.register_task('set_outlet', p.set_outlet)
    agent.register_task('set_all', p.set_all)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
