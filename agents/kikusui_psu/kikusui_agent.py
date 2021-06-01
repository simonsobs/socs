import sys, os, argparse, time

this_dir = os.path.dirname(__file__)
sys.path.append(
        os.path.join(this_dir, 'src'))

import pmx as pm
import command as cm

from ocs import ocs_agent, site_config, client_t
from ocs.ocs_twisted import TimeoutLock

class KikusuiAgent:
    def __init__(self, agent, kikusui_ip, kikusui_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.take_data = False
        self.switching = False # True while a command is sent to KIKSUI.
        self.switching2= False # True while IV is gotten.
        self.kikusui_ip = kikusui_ip
        self.kikusui_port = int(kikusui_port)

        agg_params = {'frame_length': 60}
        self.agent.register_feed('kikusui_psu', record = True, agg_params = agg_params)

        try :
            self.PMX = pm.PMX(tcp_ip = self.kikusui_ip, tcp_port = self.kikusui_port, timeout = 0.5)
        except Exception as e:
            self.log.warn('Could not connect to serial converter! | Error = "%s"' % e)
            self.PMX = None
            pass

        if not self.PMX is None : self.cmd = cm.Command(self.PMX)
        else :                    self.cmd = None
        pass

    def __check_connect(self):
        if self.PMX is None :
            msg = 'No connection to the KIKUSUI power supply. | Error = "PMX is None"'
            self.log.warn(msg)
            return False, msg
        else :
            msg, ret = self.PMX.check_connect()
            if not ret :
                msg = 'No connection to the KIKUSUI power supply. | Error = "%s"' %  msg
                self.log.warn(msg)
                return False, msg
            pass
        return True, 'Connection is OK.'


    def __reconnect(self):
        self.log.warn('Trying to reconnect...')
        # reconnect
        try :
            if self.PMX : del self.PMX
            if self.cmd : del self.cmd
            self.PMX = pm.PMX(tcp_ip = self.kikusui_ip, tcp_port = self.kikusui_port, timeout = 0.5)
        except Exception as e:
            msg = 'Could not reconnect to the KIKUSUI power supply! | Error: %s' % e
            self.log.warn(msg)
            self.PMX = None
            self.cmd = None
            return False, msg
        # reinitialize cmd
        self.cmd = cm.Command(self.PMX)
        ret, msg = self.__check_connect()
        if ret :
            msg = 'Successfully reconnected to the KIKUSUI power supply!'
            self.log.info(msg)
            return True, msg
        else :
            msg = 'Failed to reconnect to the KIKUSUI power supply!'
            self.log.warn(msg)
            if self.PMX : del self.PMX
            if self.cmd : del self.cmd
            self.PMX = None
            self.cmd = None
            return False, msg

 
    def set_on(self, session, params = None):
        with self.lock.acquire_timeout(0, job = 'set_on') as acquired:
            if not acquired:
                self.log.warn('Could not set on because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            self.cmd.user_input('on')
            self.switching = False

        return True, 'Set Kikusui on'

    def set_off(self, session, params = None):
        with self.lock.acquire_timeout(0, job = 'set_off') as acquired:
            if not acquired:
                self.log.warn('Could not set off because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            self.cmd.user_input('off')
            self.switching = False

        return True, 'Set Kikusui off'

    def set_c(self, session, params = None):
        if params == None:
            params = {'current': 0}

        with self.lock.acquire_timeout(0, job = 'set_c') as acquired:
            if not acquired:
                self.log.warn('Could not set c because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            self.cmd.user_input('C {}'.format(params['current']))
            self.switching = False

        return True, 'Set Kikusui voltage to {} A'.format(params['current'])


    def set_v(self, session, params = None):
        if params == None:
            params = {'volt': 0}

        with self.lock.acquire_timeout(0, job = 'set_v') as acquired:
            if not acquired:
                self.log.warn('Could not set v because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            self.cmd.user_input('V {}'.format(params['volt']))
            self.switching = False

        return True, 'Set Kikusui voltage to {} V'.format(params['volt'])

    def get_vc(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'get_vc') as acquired:
            if not acquired:
                self.log.warn('Could not get c,v because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            # check connection
            ret, msg = self.__check_connect()
            if not ret :
                return False, msg 

            v_val = None
            c_val = None
            s_val = None
            msg   = 'Error'
            s_msg = 'Error'
            for i in range(100) :
                if (not self.switching) and (not self.switching2) :
                    self.switching = True
                    msg, v_val, c_val = self.cmd.user_input('VC?')
                    s_msg, s_val      = self.cmd.user_input('O?')
                    self.switching = False
                    break
                time.sleep(0.1)
                pass

        self.log.info('Get voltage/current message: {}'.format(msg));
        self.log.info('Get status message: {}'.format(s_msg));
        return True, 'Get Kikusui voltage / current: {} V / {} A [status={}]'.format(v_val,c_val,s_val)

    def start_IV_acq(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'IV_acq') as acquired:
            if not acquired:
                self.log.warn('Could not start IV acq because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            session.set_status('running')
        
        self.take_data = True

        while self.take_data:
            data = {'timestamp': time.time(), 'block_name': 'Kikusui_IV', 'data': {}}
            
            if not self.switching:
                self.switching2 = True;
                # check connection
                ret, msg = self.__check_connect()
                if not ret :
                    msg = 'Could not connect to the KIKUSUI power supply!'
                    v_val, i_val, vs_val, is_val = 0., 0., 0., 0.
                    s_val = -1 # -1 means Not connected.
                    # try to reconnect
                    #ret, msg = self.__reconnect()
                else :
                    v_msg, v_val = self.cmd.user_input('V?')
                    i_msg, i_val = self.cmd.user_input('C?')
                    vs_msg,vs_val= self.cmd.user_input('VS?')
                    is_msg,is_val= self.cmd.user_input('CS?')
                    s_msg, s_val = self.cmd.user_input('O?')
                    pass
                self.switching2 = False;
                data['data']['kikusui_volt'] = v_val
                data['data']['kikusui_curr'] = i_val
                data['data']['kikusui_voltset'] = vs_val
                data['data']['kikusui_currset'] = is_val
                data['data']['kikusui_status'] = s_val
                self.agent.publish_to_feed('kikusui_psu', data)
            else:
                #data['data']['kikusui_volt'] = 0
                #data['data']['kikusui_curr'] = 0
                #data['data']['kikusui_status'] = 0
                pass

            time.sleep(1) # DAQ interval
            pass # End of while loop

        self.agent.feeds['kikusui_feed'].flush_buffer()
        return True, 'Acqusition exited cleanly'

    def stop_IV_acq(self, session, params = None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data'

        return False, 'acq is not currently running'

def make_parser(parser = None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--kikusui-ip')
    pgroup.add_argument('--kikusui-port')
    return parser

if __name__ == '__main__':
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    args = parser.parse_args()

    site_config.reparse_args(args, 'KikusuiAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    kikusui_agent = KikusuiAgent(agent, kikusui_ip = args.kikusui_ip, 
                                          kikusui_port = args.kikusui_port)
    agent.register_process('IV_acq', kikusui_agent.start_IV_acq,
                           kikusui_agent.stop_IV_acq, startup = True)
    agent.register_task('set_on', kikusui_agent.set_on)
    agent.register_task('set_off', kikusui_agent.set_off)
    agent.register_task('set_c', kikusui_agent.set_c)
    agent.register_task('set_v', kikusui_agent.set_v)
    agent.register_task('get_vc',kikusui_agent.get_vc)

    runner.run(agent, auto_reconnect = True)

