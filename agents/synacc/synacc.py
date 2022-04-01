#!/usr/bin/env python
import os
import requests
import argparse

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
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
        self.lock = TimeoutLock()
        self.ip_address = ip_address
        self.user = username
        self.passw = password

    def get_status(self, session, params=None):
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                req = "http://" + self.user + ":" + self.passw + "@" +\
                    self.ip_address+"/cmd.cgi?$A5"
                r = requests.get(req)
                resp = str(r.content)[6:11][::-1]
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
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                req = "http://"+self.user + ":" + \
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
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                if params['on']:
                    on = "1"
                else:
                    on = "0"
                req = "http://" + self.user + ":" + self.passw + "@" + \
                    self.ip_address+"/cmd.cgi?$A3" + " " + \
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
        with self.lock.acquire_timeout(1) as acquired:
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


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='SynAccAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    p = SynaccessAgent(agent,
                       ip_address=args.ip_address,
                       username=args.username,
                       password=args.password)
    agent.register_task('get_status', p.get_status, startup={})
    agent.register_task('reboot', p.reboot)
    agent.register_task('set_outlet', p.set_outlet)
    agent.register_task('set_all', p.set_all)

    runner.run(agent, auto_reconnect=True)
