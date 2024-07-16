#!/usr/bin/env python
import argparse
import time

import requests
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock


class SynaccessAgent:
    """
    Agent to control and monitor Synaccess Networks PDUs.

    Args:
        ip_address(str): IP address for the device.
        username(str): Username credential to login to device.
        password(str): Password credential to login to device.
        outlet_names(list of str): List of outlet names.
        num_outlets(int): Number of outlets for device.
    """

    def __init__(self, agent, ip_address, username, password, outlet_names=None, num_outlets=5):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.ip_address = ip_address
        self.user = username
        self.passw = password

        if outlet_names is None:
            outlet_names = []
            for i in range(num_outlets):
                outlet_names.append('outlet%i' % (i + 1))
            self.outlet_names = outlet_names
        else:
            for i in range(num_outlets):
                if len(outlet_names) <= i:
                    outlet_names.append('outlet%i' % (i + 1))
            self.outlet_names = outlet_names

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'synaccess', record=True, agg_params=agg_params)

    def __get_status(self):
        req = "http://" + self.user + ":" + self.passw + "@" +\
            self.ip_address + "/cmd.cgi?$A5"
        r = requests.get(req)
        resp = r.content.decode()[:-6:-1]  # get last 5 elements, in reverse
        return resp

    @ocs_agent.param('_')
    def get_status(self, session, params=None):
        """get_status()

        **Task** - Get the status of all outlets.

        """
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

    @ocs_agent.param('outlet', type=int)
    def reboot(self, session, params=None):
        """reboot(outlet)

        **Task** - Reboot a given outlet.

        Parameters:
            outlet (int): The outlet that we are changing the state of.

        """
        with self.lock.acquire_timeout(3, job='reboot') as acquired:
            if acquired:
                req = "http://" + self.user + ":" + \
                    self.passw + "@" + self.ip_address + \
                    "/cmd.cgi?$A4" + " " + str(params['outlet'])
                requests.get(req)
                return True, 'Rebooted outlet {}'.format(params['outlet'])
            else:
                return False, "Could not acquire lock"

    @ocs_agent.param('outlet', type=int)
    @ocs_agent.param('on', type=bool)
    def set_outlet(self, session, params=None):
        """set_outlet(outlet, on)

        **Task** - Set a particular outlet on/off.

        Parameters:
            outlet (int): The outlet that we are changing the state of.
            on (bool): The new state. True for on, False for off.

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

    @ocs_agent.param('on', type=bool)
    def set_all(self, session, params=None):
        """set_all(on)

        **Task** - Set all outlets on/off.

        Parameters:
            on (bool): The new state. True for on, False for off.

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

    @ocs_agent.param('_')
    def acq(self, session, params=None):
        """acq()

        **Process** - Start data acquisition.

        Notes:
            The most recent data collected is stored in session.data in the
            structure::

                >>> response.session['data']
                {"fields":
                    {"0": {"status": 0 or 1, (0: OFF, 1:ON)
                           "name": "outlet1"},
                     "1": {"status": 0 or 1, (0: OFF, 1:ON)
                           "name": "outlet2"},
                     "2": {"status": 0 or 1, (0: OFF, 1:ON)
                           "name": "outlet3"},
                     "3": {"status": 0 or 1, (0: OFF, 1:ON)
                           "name": "outlet4"},
                     "4": {"status": 0 or 1, (0: OFF, 1:ON)
                           "name": "outlet5"},
                    }
                }

        """

        with self.lock.acquire_timeout(timeout=3, job='acq')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'Could not start status acq because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock'

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
                    status_dict['%d' % i] = {'status': status}
                    status_dict['%d' % i]['name'] = self.outlet_names[i]
                self.agent.publish_to_feed('synaccess', data)
                session.data['timestamp'] = current_time
                session.data['fields'] = status_dict

                time.sleep(1)  # DAQ interval
                # End of while loop

        self.agent.feeds['synaccess'].flush_buffer()
        return True, 'Acqusition exited cleanly'

    def stop_acq(self, session, params=None):
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
    pgroup.add_argument('--ip-address', help='IP address for the device.')
    pgroup.add_argument('--username', help='Username credential to login to device.')
    pgroup.add_argument('--password', help='Password credential to login to device.')
    pgroup.add_argument('--outlet-names', nargs='+', type=str,
                        help="List of outlet names.")
    pgroup.add_argument('--num-outlets', default=5, help='Number of outlets for the device.')
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
                       password=args.password,
                       outlet_names=args.outlet_names,
                       num_outlets=args.num_outlets)
    agent.register_process('acq', p.acq,
                           p.stop_acq, startup=True)
    agent.register_task('get_status', p.get_status, startup={})
    agent.register_task('reboot', p.reboot)
    agent.register_task('set_outlet', p.set_outlet)
    agent.register_task('set_all', p.set_all)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
