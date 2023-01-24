import argparse
import calendar
import datetime
import struct
import time

import numpy as np
import soaculib as aculib
import soaculib.status_keys as status_keys
import twisted.web.client as tclient
from autobahn.twisted.util import sleep as dsleep
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from soaculib.twisted_backend import TwistedHttpBackend
from twisted.internet import protocol, reactor
from twisted.internet.defer import inlineCallbacks

import socs.agents.acu.drivers as sh

#: The number of free ProgramTrack positions, when stack is empty.
FULL_STACK = 10000


def timecode(acutime):
    """
    Takes the time code produced by the ACU status stream and returns
    a ctime.

    Parameters:
        acutime (float): The time recorded by the ACU status stream,
                         corresponding to the fractional day of the year
    """
    sec_of_day = (acutime - 1) * 60 * 60 * 24
    year = datetime.datetime.now().year
    gyear = calendar.timegm(time.strptime(str(year), '%Y'))
    comptime = gyear + sec_of_day
    return comptime


def uploadtime_to_ctime(ptstack_time, upload_year):
    year = int(upload_year)
    gyear = calendar.timegm(time.strptime(str(year), '%Y'))
    day_of_year = float(ptstack_time.split(',')[0]) - 1.0
    hour = float(ptstack_time.split(',')[1].split(':')[0])
    minute = float(ptstack_time.split(',')[1].split(':')[1])
    second = float(ptstack_time.split(',')[1].split(':')[2])
    comptime = gyear + day_of_year * 60 * 60 * 24 + hour * 60 * 60 + minute * 60 + second
    return comptime


def pop_first_vals(data_dict, group_size):
    new_data_dict = {}
    for key in data_dict.keys():
        if len(data_dict[key]):
            new_data_dict[key] = data_dict[key][group_size:]
        else:
            print('no more data')
    return new_data_dict


def front_group(data_dict, group_size):
    new_data_dict = {}
    for key in data_dict.keys():
        if len(data_dict[key]) > group_size:
            new_data_dict[key] = data_dict[key][:group_size]
        else:
            new_data_dict[key] = data_dict[key]
    return new_data_dict


class ACUAgent:
    """
    Agent to acquire data from an ACU and control telescope pointing with the
    ACU.

    Parameters:
        acu_config (str):
            The configuration for the ACU, as referenced in aculib.configs.
            Default value is 'guess'.

    """

    def __init__(self, agent, acu_config='guess'):
        self.lock = TimeoutLock()
        self.jobs = {
            'monitor': 'idle',
            'monitorspem': 'idle',
            'broadcast': 'idle',
            'control': 'idle',  # shared by all motion tasks/processes
            'scanspec': 'idle',
            'restartidle': 'idle',
        }

        self.acu_config = aculib.guess_config(acu_config)
        self.sleeptime = self.acu_config['motion_waittime']
        self.udp = self.acu_config['streams']['main']
        self.udp_schema = aculib.get_stream_schema(self.udp['schema'])
        self.udp_ext = self.acu_config['streams']['ext']
        self.acu8100 = self.acu_config['status']['status_name']

        # There may or may not be a special 3rd axis dataset that
        # needs to be probed.
        self.acu3rdaxis = self.acu_config['status'].get('3rdaxis_name')

        self.monitor_fields = status_keys.status_fields[self.acu_config['platform']]['status_fields']
        self.motion_limits = self.acu_config['motion_limits']

        self.log = agent.log

        # self.data provides a place to reference data from the monitors.
        # 'status' is populated by the monitor operation
        # 'broadcast' is populated by the udp_monitor operation

        self.data = {'status': {'summary': {},
                                'position_errors': {},
                                'axis_limits': {},
                                'axis_faults_errors_overages': {},
                                'axis_warnings': {},
                                'axis_failures': {},
                                'axis_state': {},
                                'osc_alarms': {},
                                'commands': {},
                                'ACU_failures_errors': {},
                                'platform_status': {},
                                'ACU_emergency': {},
                                'third_axis': {},
                                },
                     'spem': {},
                     'broadcast': {},
                     'uploads': {'Start_Azimuth': 0.0,
                                 'Start_Elevation': 0.0,
                                 'Start_Boresight': 0.0,
                                 'Command_Type': 0,
                                 'Preset_Azimuth': 0.0,
                                 'Preset_Elevation': 0.0,
                                 'Preset_Boresight': 0.0,
                                 'PtStack_Lines': 'False',
                                 'PtStack_Time': '000, 00:00:00.000000',
                                 'PtStack_Azimuth': 0.0,
                                 'PtStack_Elevation': 0.0,
                                 'PtStack_AzVelocity': 0.0,
                                 'PtStack_ElVelocity': 0.0,
                                 'PtStack_AzFlag': 0,
                                 'PtStack_ElFlag': 0},
                     'scanspec': {},
                     }

        self.agent = agent

        self.take_data = False

        # self.web_agent = tclient.Agent(reactor)
        tclient._HTTP11ClientFactory.noisy = False

        self.acu_control = aculib.AcuControl(
            acu_config, backend=TwistedHttpBackend(persistent=False))
        self.acu_read = aculib.AcuControl(
            acu_config, backend=TwistedHttpBackend(persistent=True), readonly=True)

        agent.register_process('monitor',
                               self.monitor,
                               lambda session, params: self._set_job_stop('monitor'),
                               blocking=False,
                               startup=True)
#        agent.register_process('monitor_spem',
#                               self.monitor_spem,
#                               lambda
        agent.register_process('broadcast',
                               self.broadcast,
                               lambda session, params: self._set_job_stop('broadcast'),
                               blocking=False,
                               startup=True)
        agent.register_process('generate_scan',
                               self.generate_scan,
                               lambda session, params: self._set_job_stop('control'),
                               blocking=False,
                               startup=False)
        agent.register_process('restart_idle',
                               self.restart_idle,
                               lambda session, params: self._set_job_stop('restart_idle'),
                               blocking=False,
                               startup=False)
        basic_agg_params = {'frame_length': 60}
        fullstatus_agg_params = {'frame_length': 60,
                                 'exclude_influx': True,
                                 'exclude_aggregator': False
                                 }
        influx_agg_params = {'frame_length': 60,
                             'exclude_influx': False,
                             'exclude_aggregator': True
                             }
        self.stop_times = {'az': float('nan'),
                           'el': float('nan'),
                           'bs': float('nan'),
                           }
        self.agent.register_feed('acu_status',
                                 record=True,
                                 agg_params=fullstatus_agg_params,
                                 buffer_time=1)
        self.agent.register_feed('acu_status_influx',
                                 record=True,
                                 agg_params=influx_agg_params,
                                 buffer_time=1)
        self.agent.register_feed('acu_commands_influx',
                                 record=True,
                                 agg_params=influx_agg_params,
                                 buffer_time=1)
        self.agent.register_feed('acu_udp_stream',
                                 record=True,
                                 agg_params=fullstatus_agg_params,
                                 buffer_time=1)
        self.agent.register_feed('acu_broadcast_influx',
                                 record=True,
                                 agg_params=influx_agg_params,
                                 buffer_time=1)
        self.agent.register_feed('acu_upload',
                                 record=True,
                                 agg_params=basic_agg_params,
                                 buffer_time=1)
        self.agent.register_feed('acu_error',
                                 record=True,
                                 agg_params=basic_agg_params,
                                 buffer_time=1)
        agent.register_task('go_to', self.go_to, blocking=False)
        agent.register_task('constant_velocity_scan',
                            self.constant_velocity_scan,
                            blocking=False)
        agent.register_task('fromfile_scan',
                            self.fromfile_scan,
                            blocking=False)
        agent.register_task('set_boresight',
                            self.set_boresight,
                            blocking=False)
        agent.register_task('stop_and_clear',
                            self.stop_and_clear,
                            blocking=False)
        agent.register_task('preset_stop_clear',
                            self.preset_stop_clear,
                            blocking=False)
        agent.register_task('clear_faults',
                            self.clear_faults,
                            blocking=False)

    # Operation management.  This agent has several Processes that
    # must be able to alone or simultaneously.  The state of each is
    # registered in self.jobs, protected by self.lock (though this is
    # probably not necessary as long as we don't thread).  Any logic
    # to assess conflicts should probably be in _try_set_job.

    def _set_job_stop(self, session):
        #        """
        #        Set a job status to 'stop'.
        #
        #        Parameters:
        #            job_name (str): Name of the process you are trying to stop.
        #        """
        session.set_status('stopping')
#        print('try to acquire stop')
#        # return (False, 'Could not stop')
#        with self.lock.acquire_timeout(timeout=1.0, job=job_name) as acquired:
#            if not acquired:
#                self.log.warn("Lock could not be acquired because it is"
#                              f" held by {self.lock.job}")
#                return False
#            try:
#                self.jobs[job_name] = 'stop'
#            # state = self.jobs.get(job_name, 'idle')
#            # if state == 'idle':
#            #     return False, 'Job not running.'
#            # if state == 'stop':
#            #     return False, 'Stop already requested.'
#            # self.jobs[job_name] = 'stop'
#                return True, 'Requested Process stop.'
#            except Exception as e:
#                print(str(e))

    def _set_job_done(self, job_name):
        """
        Set a job status to 'idle'.

        Parameters:
            job_name (str): Name of the task/process you are trying to idle.
        """
        with self.lock.acquire_timeout(timeout=1.0, job=job_name) as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquried because it is held"
                              f" by {self.lock.job}")
                return False
            self.jobs[job_name] = 'idle'

    #
    # The Operations
    #

    @inlineCallbacks
    def restart_idle(self, session, params):
        session.set_status('running')
        while True:
            resp = yield self.acu_control.http.Command('DataSets.CmdModeTransfer',
                                                       'RestartIdleTime')
            self.log.info('Sent RestartIdleTime')
            self.log.info(resp)
            yield dsleep(1. * 60.)
        self._set_job_done('restart_idle')
        self.log.info('Process "restart_idle" ended.')
        return True, 'Process "restart_idle" exited cleanly.'

    @inlineCallbacks
    def monitor(self, session, params):
        """monitor()

        **Process** - Refresh the cache of SATP ACU status information and
        report it on the 'acu_status_summary' and 'acu_status_full' HK feeds.

        Summary parameters are ACU-provided time code, Azimuth mode,
        Azimuth position, Azimuth velocity, Elevation mode, Elevation position,
        Elevation velocity, Boresight mode, and Boresight position.

        """

        self.jobs['monitor'] = 'run'
        session.set_status('running')
        print(self.jobs['monitor'])
        version = yield self.acu_read.http.Version()
        self.log.info(version)
        session.data = {'platform': self.acu_config['platform']}

        # Numbering as per ICD.
        mode_key = {
            'Stop': 0,
            'Preset': 1,
            'ProgramTrack': 2,
            'Rate': 3,
            'SectorScan': 4,
            'SearchSpiral': 5,
            'SurvivalMode': 6,
            'StepTrack': 7,
            'GeoSync': 8,
            'OPT': 9,
            'TLE': 10,
            'Stow': 11,
            'StarTrack': 12,
            'SunTrack': 13,
            'MoonTrack': 14,
            'I11P': 15,
            'AutoTrack/Preset': 16,
            'AutoTrack/PositionMemory': 17,
            'AutoTrack/PT': 18,
            'AutoTrack/OPT': 19,
            'AutoTrack/PT/Search': 20,
            'AutoTrack/TLE': 21,
            'AutoTrack/TLE/Search': 22,

            # Currently we do not have ICD values for these, but they
            # are included in the output of Meta.  ElSync, at least,
            # is a known third axis mode for the LAT.
            'ElSync': 100,
            'UnStow': 101,
            'MaintenanceStow': 102,
        }

        # fault_key digital values taken from ICD (correspond to byte-encoding)
        fault_key = {
            'No Fault': 0,
            'Warning': 1,
            'Fault': 2,
            'Critical': 3,
            'No Data': 4,
            'Latched Fault': 5,
            'Latched Critical Fault': 6,
        }
        pin_key = {
            # Capitalization matches strings in ACU binary, not ICD.
            'Any Moving': 0,
            'All Inserted': 1,
            'All Retracted': 2,
            'Failure': 3,
        }
        tfn_key = {'None': float('nan'),
                   'False': 0,
                   'True': 1,
                   }
        report_t = time.time()
        report_period = 20
        n_ok = 0
        min_query_period = 0.05   # Seconds
        query_t = 0
        prev_checkdata = {'ctime': time.time(),
                          'Azimuth_mode': None,
                          'Elevation_mode': None,
                          'Boresight_mode': None,
                          }

#        session.data = {'StatusResponseRate': n_ok / (query_t - report_t)}
        j = yield self.acu_read.http.Values(self.acu8100)
#        session.data = {'status': j}
        if self.acu3rdaxis:
            j2 = yield self.acu_read.http.Values(self.acu3rdaxis)
        else:
            j2 = {}
        session.data = {'StatusDetailed': j,
                        'Status3rdAxis': j2,
                        'StatusResponseRate': n_ok / (query_t - report_t)}

        while self.jobs['monitor'] == 'run':
            now = time.time()

            if now - query_t < min_query_period:
                yield dsleep(min_query_period - (now - query_t))

            query_t = time.time()
            if query_t > report_t + report_period:
                resp_rate = n_ok / (query_t - report_t)
                self.log.info('Responses ok at %.3f Hz'
                              % (resp_rate))
                report_t = query_t
                n_ok = 0
                session.data.update({'StatusResponseRate': resp_rate})

            try:
                j = yield self.acu_read.http.Values(self.acu8100)
#                session.data = {'status': j}
                if self.acu3rdaxis:
                    j2 = yield self.acu_read.http.Values(self.acu3rdaxis)
                else:
                    j2 = {}
#                    session.data.update(j2)
                session.data.update({'StatusDetailed': j, 'Status3rdAxis': j2})
                n_ok += 1
               # print(session.data)
            except Exception as e:
                # Need more error handling here...
                errormsg = {'aculib_error_message': str(e)}
                self.log.error(str(e))
                acu_error = {'timestamp': time.time(),
                             'block_name': 'ACU_error',
                             'data': errormsg
                             }
                self.agent.publish_to_feed('acu_error', acu_error)
                yield dsleep(1)
                continue
            for k, v in session.data.items():
                if type(v) != float:
                    for (key, value) in v.items():
                        for category in self.monitor_fields:
                            if key in self.monitor_fields[category]:
                                if isinstance(value, bool):
                                    self.data['status'][category][self.monitor_fields[category][key]] = int(value)
                                elif isinstance(value, int) or isinstance(value, float):
                                    self.data['status'][category][self.monitor_fields[category][key]] = value
                                elif value is None:
                                    self.data['status'][category][self.monitor_fields[category][key]] = float('nan')
                                else:
                                    self.data['status'][category][self.monitor_fields[category][key]] = str(value)
            self.data['status']['summary']['ctime'] =\
                timecode(self.data['status']['summary']['Time'])
            if self.data['status']['platform_status']['Remote_mode'] == 0:
                self.log.warn('ACU in local mode!')
            if self.data['status']['summary']['ctime'] == prev_checkdata['ctime']:
                self.log.warn('ACU time has not changed from previous data point!')
            for axis_mode in ['Azimuth_mode', 'Elevation_mode', 'Boresight_mode']:
                if self.data['status']['summary'][axis_mode] != prev_checkdata[axis_mode]:
                    self.log.info(axis_mode + ' has changed to ' + self.data['status']['summary'][axis_mode])

            # influx_status refers to all other self.data['status'] keys. Do not add
            # more keys to any self.data['status'] categories beyond this point
            influx_status = {}
            for category in self.data['status']:
                if category != 'commands':
                    for statkey, statval in self.data['status'][category].items():
                        if isinstance(statval, float):
                            influx_status[statkey + '_influx'] = statval
                        elif isinstance(statval, str):
                            if statval == 'None':
                                influx_status[statkey + '_influx'] = float('nan')
                            elif statval in ['True', 'False']:
                                influx_status[statkey + '_influx'] = tfn_key[statval]
                            elif statval in mode_key:
                                influx_status[statkey + '_influx'] = mode_key[statval]
                            elif statval in fault_key:
                                influx_status[statkey + '_influx'] = fault_key[statval]
                            elif statval in pin_key:
                                influx_status[statkey + '_influx'] = pin_key[statval]
                            else:
                                raise ValueError('Could not convert value for %s="%s"' %
                                                 (statkey, statval))
                        elif isinstance(statval, int):
                            if statkey in ['Year', 'Free_upload_positions']:
                                influx_status[statkey + '_influx'] = float(statval)
                            else:
                                influx_status[statkey + '_influx'] = int(statval)
                elif category == 'commands':
                    if str(self.data['status']['commands']['Azimuth_commanded_position']) != 'nan':
                        acucommand_az = {'timestamp': self.data['status']['summary']['ctime'],
                                         'block_name': 'ACU_commanded_positions_az',
                                         'data': {'Azimuth_commanded_position_influx': self.data['status']['commands']['Azimuth_commanded_position']}
                                         }
                        self.agent.publish_to_feed('acu_commands_influx', acucommand_az)
                    if str(self.data['status']['commands']['Elevation_commanded_position']) != 'nan':
                        acucommand_el = {'timestamp': self.data['status']['summary']['ctime'],
                                         'block_name': 'ACU_commanded_positions_el',
                                         'data': {'Elevation_commanded_position_influx': self.data['status']['commands']['Elevation_commanded_position']}
                                         }
                        self.agent.publish_to_feed('acu_commands_influx', acucommand_el)
                    if self.acu_config['platform'] == 'satp':
                        if str(self.data['status']['commands']['Boresight_commanded_position']) != 'nan':
                            acucommand_bs = {'timestamp': self.data['status']['summary']['ctime'],
                                             'block_name': 'ACU_commanded_positions_boresight',
                                             'data': {'Boresight_commanded_position_influx': self.data['status']['commands']['Boresight_commanded_position']}
                                             }
                            self.agent.publish_to_feed('acu_commands_influx', acucommand_bs)
            if self.data['uploads']['PtStack_Time'] == '000, 00:00:00.000000':
                self.data['uploads']['PtStack_ctime'] = self.data['status']['summary']['ctime']

            acustatus_summary = {'timestamp':
                                 self.data['status']['summary']['ctime'],
                                 'block_name': 'ACU_summary_output',
                                 'data': self.data['status']['summary']
                                 }
            acustatus_axisfaults = {'timestamp': self.data['status']['summary']['ctime'],
                                    'block_name': 'ACU_axis_faults',
                                    'data': self.data['status']['axis_faults_errors_overages']
                                    }
            acustatus_poserrors = {'timestamp': self.data['status']['summary']['ctime'],
                                   'block_name': 'ACU_position_errors',
                                   'data': self.data['status']['position_errors']
                                   }
            acustatus_axislims = {'timestamp': self.data['status']['summary']['ctime'],
                                  'block_name': 'ACU_axis_limits',
                                  'data': self.data['status']['axis_limits']
                                  }
            acustatus_axiswarn = {'timestamp': self.data['status']['summary']['ctime'],
                                  'block_name': 'ACU_axis_warnings',
                                  'data': self.data['status']['axis_warnings']
                                  }
            acustatus_axisfail = {'timestamp': self.data['status']['summary']['ctime'],
                                  'block_name': 'ACU_axis_failures',
                                  'data': self.data['status']['axis_failures']
                                  }
            acustatus_axisstate = {'timestamp': self.data['status']['summary']['ctime'],
                                   'block_name': 'ACU_axis_state',
                                   'data': self.data['status']['axis_state']
                                   }
            acustatus_oscalarm = {'timestamp': self.data['status']['summary']['ctime'],
                                  'block_name': 'ACU_oscillation_alarm',
                                  'data': self.data['status']['osc_alarms']
                                  }
            acustatus_commands = {'timestamp': self.data['status']['summary']['ctime'],
                                  'block_name': 'ACU_command_status',
                                  'data': self.data['status']['commands']
                                  }
            acustatus_acufails = {'timestamp': self.data['status']['summary']['ctime'],
                                  'block_name': 'ACU_general_errors',
                                  'data': self.data['status']['ACU_failures_errors']
                                  }
            acustatus_platform = {'timestamp': self.data['status']['summary']['ctime'],
                                  'block_name': 'ACU_platform_status',
                                  'data': self.data['status']['platform_status']
                                  }
            acustatus_emergency = {'timestamp': self.data['status']['summary']['ctime'],
                                   'block_name': 'ACU_emergency',
                                   'data': self.data['status']['ACU_emergency']
                                   }
            acustatus_influx = {'timestamp':
                                self.data['status']['summary']['ctime'],
                                'block_name': 'ACU_status_INFLUX',
                                'data': influx_status
                                }
            status_blocks = [acustatus_summary, acustatus_axisfaults, acustatus_poserrors,
                             acustatus_axislims, acustatus_axiswarn, acustatus_axisfail,
                             acustatus_axisstate, acustatus_oscalarm, acustatus_commands,
                             acustatus_acufails, acustatus_platform, acustatus_emergency]
            for block in status_blocks:
                self.agent.publish_to_feed('acu_status', block)
            self.agent.publish_to_feed('acu_status_influx', acustatus_influx, from_reactor=True)

            prev_checkdata = {'ctime': self.data['status']['summary']['ctime'],
                              'Azimuth_mode': self.data['status']['summary']['Azimuth_mode'],
                              'Elevation_mode': self.data['status']['summary']['Elevation_mode'],
                              'Boresight_mode': self.data['status']['summary']['Boresight_mode'],
                              }
        # self._set_job_stop('monitor')
        # yield dsleep(1)
        # self._set_job_done('monitor')
        return True, 'Acquisition exited cleanly.'

    @inlineCallbacks
    def broadcast(self, session, params):
        """broadcast()

        **Process** - Read UDP data from the port specified by self.acu_config,
        decode it, and publish to an HK feed.

        """
        self.jobs['broadcast'] = 'run'
        session.set_status('running')
        FMT = self.udp_schema['format']
        FMT_LEN = struct.calcsize(FMT)
        UDP_PORT = self.udp['port']
        udp_data = []
        fields = self.udp_schema['fields']

        class MonitorUDP(protocol.DatagramProtocol):

            def datagramReceived(self, data, src_addr):
                host, port = src_addr
                offset = 0
                while len(data) - offset >= FMT_LEN:
                    d = struct.unpack(FMT, data[offset:offset + FMT_LEN])
                    udp_data.append(d)
                    offset += FMT_LEN
        handler = reactor.listenUDP(int(UDP_PORT), MonitorUDP())
        while self.jobs['broadcast'] == 'run':
            if udp_data:
                process_data = udp_data[:200]
                udp_data = udp_data[200:]
                year = datetime.datetime.now().year
                gyear = calendar.timegm(time.strptime(str(year), '%Y'))
                if len(process_data):
                    sample_rate = (len(process_data)
                                   / ((process_data[-1][0] - process_data[0][0]) * 86400
                                   + process_data[-1][1] - process_data[0][1]))
                else:
                    sample_rate = 0.0
                latest_az = process_data[2]
                latest_el = process_data[3]
                latest_az_raw = process_data[4]
                latest_el_raw = process_data[5]
                session.data = {'sample_rate': sample_rate,
                                'latest_az': latest_az,
                                'latest_el': latest_el,
                                'latest_az_raw': latest_az_raw,
                                'latest_el_raw': latest_el_raw
                                }
                bcast_first = {}
                pd0 = process_data[0]
                pd0_gday = (pd0[0] - 1) * 86400
                pd0_sec = pd0[1]
                pd0_data_ctime = gyear + pd0_gday + pd0_sec
                bcast_first['Time_bcast_influx'] = pd0_data_ctime
                for i in range(2, len(pd0)):
                    bcast_first[fields[i].replace(' ', '_') + '_bcast_influx'] = pd0[i]
                acu_broadcast_influx = {'timestamp': bcast_first['Time_bcast_influx'],
                                        'block_name': 'ACU_position_bcast_influx',
                                        'data': bcast_first,
                                        }
                self.agent.publish_to_feed('acu_broadcast_influx', acu_broadcast_influx, from_reactor=True)
                for d in process_data:
                    gday = (d[0] - 1) * 86400
                    sec = d[1]
                    data_ctime = gyear + gday + sec
                    self.data['broadcast']['Time'] = data_ctime
                    for i in range(2, len(d)):
                        self.data['broadcast'][fields[i].replace(' ', '_')] = d[i]
                    acu_udp_stream = {'timestamp': self.data['broadcast']['Time'],
                                      'block_name': 'ACU_broadcast',
                                      'data': self.data['broadcast']
                                      }
                    # print(acu_udp_stream)
                    self.agent.publish_to_feed('acu_udp_stream',
                                               acu_udp_stream, from_reactor=True)
            else:
                yield dsleep(1)
            yield dsleep(0.005)

        handler.stopListening()
        self._set_job_done('broadcast')
        return True, 'Acquisition exited cleanly.'

    @inlineCallbacks
    def _check_daq_streams(self, stream):
        if self.jobs[stream] != 'run':
            self.log.warn("Process '%s' is not running" % stream)
            job_check = False
        else:
            job_check = True

        time_points = []
        while len(time_points) < 2:
            if stream == 'broadcast':
                new_time = self.data['broadcast']['Time']
            elif stream == 'monitor':
                new_time = self.data['status']['summary']['ctime']
            time_points.append(new_time)
            yield dsleep(0.5)
        if time_points[1] == time_points[0]:
            self.log.warn('%s points may be stale, check stream.' % stream)
        return job_check

    @ocs_agent.param('az', type=float)
    @ocs_agent.param('el', type=float)
    @ocs_agent.param('wait', default=1., type=float)
    @ocs_agent.param('end_stop', default=False, type=bool)
    @ocs_agent.param('rounding', default=1, type=int)
    @ocs_agent.param('azonly', default=False, type=bool)
    @inlineCallbacks
    def go_to(self, session, params):
        """go_to(az=None, el=None, wait=1., end_stop=False, rounding=1)

        **Task** - Move the telescope to a particular point (azimuth,
        elevation) in Preset mode. When motion has ended and the telescope
        reaches the preset point, it returns to Stop mode and ends.

        Parameters:
            az (float): destination angle for the azimuthal axis
            el (float): destination angle for the elevation axis
            wait (float): amount of time to wait for motion to end
            end_stop (bool): put the telescope in Stop mode at the end of
                the motion
            rounding (int): number of decimal places to round to

        """

        session.set_status('running')
        bcast_check = yield self._check_daq_streams('broadcast')
        monitor_check = yield self._check_daq_streams('monitor')
        if not bcast_check or not monitor_check:
            self._set_job_done('control')
            return False, 'Cannot complete go_to with process not running.'

        az = params['az']
        el = params['el']
        azonly = params['azonly']
        if az < self.motion_limits['azimuth']['lower'] or az > self.motion_limits['azimuth']['upper']:
            raise ocs_agent.ParamError("Azimuth out of range! Must be "
                                       + f"{self.motion_limits['azimuth']['lower']} < az "
                                       + f"< {self.motion_limits['azimuth']['upper']}")
        if el < self.motion_limits['elevation']['lower'] or el > self.motion_limits['elevation']['upper']:
            raise ocs_agent.ParamError("Elevation out of range! Must be "
                                       + f"{self.motion_limits['elevation']['lower']} < el "
                                       + f"< {self.motion_limits['elevation']['upper']}")
        end_stop = params['end_stop']
        wait_for_motion = params['wait']
        round_int = params['rounding']
        if self.data['status']['platform_status']['Remote_mode'] == 0:
            self.log.warn('ACU in local mode, cannot perform motion with OCS.')
            self._set_job_done('control')
            return False, 'ACU not in remote mode.'
        self.log.info('Azimuth commanded position: ' + str(az))
        self.log.info('Elevation commanded position: ' + str(el))
        current_az = round(self.data['status']['summary']['Azimuth_current_position'], 2)  # round(self.data['broadcast']['Corrected_Azimuth'], 4)
        current_el = round(self.data['status']['summary']['Elevation_current_position'], 2)  # round(self.data['broadcast']['Corrected_Elevation'], 4)
        self.data['uploads']['Start_Azimuth'] = current_az
        self.data['uploads']['Start_Elevation'] = current_el
        self.data['uploads']['Command_Type'] = 1
        self.data['uploads']['Preset_Azimuth'] = az
        self.data['uploads']['Preset_Elevation'] = el

     #   acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
     #                 'block_name': 'ACU_upload',
     #                 'data': self.data['uploads']
     #                 }
     #   self.agent.publish_to_feed('acu_upload', acu_upload)

        # Check whether the telescope is already at the point
        self.log.info('Setting mode to Preset')
        if azonly:
            acu_msg = yield self.acu_control.azmode('Preset')
        else:
            acu_msg = yield self.acu_control.mode('Preset')
        if acu_msg not in [b'OK, Command executed.', b'OK, Command send.']:
            self.log.error(acu_msg)
            self._set_job_done('control')
            return False, 'Could not change mode'
        if round(current_az, round_int) == az and \
                round(current_el, round_int) == el:
            yield self.acu_control.go_to(az, el, wait=0.1)
            self.log.info('Already at commanded position.')
            self._set_job_done('control')
            return True, 'Preset at commanded position'
        # yield self.acu.stop()
        # yield self.acu_control.mode('Stop')
        # self.log.info('Stopped')
        yield dsleep(2)
        self.log.info('Sending go_to command')
        acu_msg = yield self.acu_control.go_to(az, el, wait=0.1)
        if acu_msg not in [b'OK, Command executed.', b'OK, Command send.']:
            self.log.error(acu_msg)
            self._set_job_done('control')
            return False, 'Could not send go_to command'
        yield dsleep(0.3)
        mdata = self.data['status']['summary']
        # Wait for telescope to start moving
        self.log.info('Moving to commanded position')
        wait_for_motion_start = time.time()
        elapsed_wait_for_motion = 0.0
        while mdata['Azimuth_current_velocity'] == 0.0 and\
                mdata['Elevation_current_velocity'] == 0.0:
            if elapsed_wait_for_motion < 30.:
                yield dsleep(wait_for_motion)
                elapsed_wait_for_motion = time.time() - wait_for_motion_start
                mdata = self.data['status']['summary']
            else:
                if round(mdata['Azimuth_current_position'] - az, round_int) == 0. and \
                        round(mdata['Elevation_current_position'] - el, round_int) == 0.:
                    if end_stop:
                        yield self.acu_control.stop()
                        self.log.info('Az and el in Stop mode')
                    self._set_job_done('control')
                    return True, 'Pointing completed'
                else:
                    yield self.acu_control.stop()
                    self._set_job_done('control')
                    return False, 'Motion never occurred! Stop activated'
            yield dsleep(wait_for_motion)
            mdata = self.data['status']['summary']
        moving = True
        while moving:
          #      acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
          #                    'block_name': 'ACU_upload',
          #                    'data': self.data['uploads']
          #                    }
          #      self.agent.publish_to_feed('acu_upload', acu_upload)
            mdata = self.data['status']['summary']
            remote = self.data['status']['platform_status']['Remote_mode']
            if remote == 0:
                self.log.warn('ACU no longer in remote mode!')
            if azonly:
                if mdata['Azimuth_mode'] != 'Preset':
                    self.log.info('Mode has changed from Preset, abort motion')
                    return False, 'Motion aborted'
            else:
                if mdata['Azimuth_mode'] != 'Preset' or mdata['Elevation_mode'] != 'Preset':
                    # yield self.acu_control.stop()
                    self.log.info('Mode has changed from Preset, abort motion')
                    return False, 'Motion aborted'
            ve = round(mdata['Elevation_current_velocity'], 2)
            va = round(mdata['Azimuth_current_velocity'], 2)
            if (ve != 0.0) or (va != 0.0):
                moving = True
                mdata = self.data['status']['summary']
                if azonly:
                    if mdata['Azimuth_mode'] != 'Preset':
                        self.log.info('Mode has changed from Preset, abort motion')
                        return False, 'Motion aborted'
                else:
                    if mdata['Azimuth_mode'] != 'Preset' or mdata['Elevation_mode'] != 'Preset':
                        self.log.info('Mode has changed from Preset, abort motion')
                        return False, 'Motion aborted'
                yield dsleep(wait_for_motion)
            else:
                moving = False
                mdata = self.data['status']['summary']
                if azonly:
                    if mdata['Azimuth_mode'] != 'Preset':
                        self.log.info('Mode has changed from Preset, abort motion')
                        return False, 'Motion aborted'
                else:
                    if mdata['Azimuth_mode'] != 'Preset' or mdata['Elevation_mode'] != 'Preset':
                        # yield self.acu_control.stop()
                        self.log.info('Mode has changed from Preset, abort motion')
                        return False, 'Motion aborted'
                pe = round(mdata['Elevation_current_position'], round_int)
                pa = round(mdata['Azimuth_current_position'], round_int)
                if pe != el or pa != az:
                    yield self.acu_control.stop()
                    self.log.warn('Stopped before reaching commanded point!')
                    return False, 'Something went wrong!'
        if end_stop:
#            yield self.acu_control.stop()
            yield self.acu_control.mode('Stop')
            self.log.info('Stop mode activated')
        self.data['uploads']['Start_Azimuth'] = 0.0
        self.data['uploads']['Start_Elevation'] = 0.0
        self.data['uploads']['Command_Type'] = 0
        self.data['uploads']['Preset_Azimuth'] = 0.0
        self.data['uploads']['Preset_Elevation'] = 0.0
       # acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
       #               'block_name': 'ACU_upload',
       #               'data': self.data['uploads']
       #               }
       # self.agent.publish_to_feed('acu_upload', acu_upload, from_reactor=True)
        self._set_job_done('control')
        return True, 'Pointing completed'

    @inlineCallbacks
    def set_boresight(self, session, params):
        """set_boresight(b=None, end_stop=False)

        **Task** - Move the telescope to a particular third-axis angle.

        Parameters:
            b (float): destination angle for boresight rotation
            end_stop (bool): put axes in Stop mode after motion

        """

        session.set_status('running')
        monitor_check = yield self._check_daq_streams('monitor')
        if not monitor_check:
            self._set_job_done('control')
            return False, 'Cannot complete set_boresight with process not running.'
        else:
            self.log.info('monitor_check completed')

        if self.acu_config['platform'] == 'satp':
            status_block = 'summary'
            position_name = 'Boresight_current_position'
            mode_name = 'Boresight_mode'
        elif self.acu_config['platform'] == 'ccat':
            status_block = 'third_axis'
            position_name = 'Axis3_current_position'
            mode_name = 'Axis3_mode'

        bs_destination = params.get('b')
        lower_limit = self.motion_limits['boresight']['lower']
        upper_limit = self.motion_limits['boresight']['upper']
        if bs_destination < lower_limit or bs_destination > upper_limit:
            self.log.warn('Commanded boresight position out of range!')
            self._set_job_done('control')
            return False, 'Commanded boresight position out of range.'

#        self.log.info('Boresight current position is ' + str(self.data['status']['summary']['Boresight_current_position']))
        self.log.info('Boresight position will be set to ' + str(bs_destination))
        if self.data['status']['platform_status']['Remote_mode'] == 0:
            self.log.warn('ACU in local mode, cannot perform motion with OCS.')
            self._set_job_done('control')
            return False, 'ACU not in remote mode.'
        else:
            self.log.info('Verified ACU in remote mode')
        # yield self.acu_control.stop()
        yield dsleep(0.5)
#        self.data['uploads']['Start_Boresight'] = self.data['status'][status_block][position_name]
#        self.data['uploads']['Command_Type'] = 1
#        self.data['uploads']['Preset_Boresight'] = bs_destination
#        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
#                      'block_name': 'ACU_upload',
#                      'data': self.data['uploads']
#                      }
#        self.agent.publish_to_feed('acu_upload', acu_upload)
        self.log.info('Starting boresight motion')
        yield self.acu_control.go_3rd_axis(bs_destination)
        yield dsleep(0.2)
        current_position = self.data['status'][status_block][position_name]
        while round(current_position - bs_destination, 2) != 0:
            bs_mode = self.data['status'][status_block][mode_name]
            if bs_mode == 'Preset':
                yield dsleep(0.1)
#                acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
#                              'block_name': 'ACU_upload',
#                              'data': self.data['uploads']
#                              }
#                self.agent.publish_to_feed('acu_upload', acu_upload)
                current_position = self.data['status'][status_block][position_name]
                print(current_position)
            else:
                self.log.warn('Boresight mode has changed from Preset!')
                self._set_job_done('control')
                return False, '3rd axis mode changed from Preset, check errors/faults.'
        if params.get('end_stop'):
            yield self.acu_control.http.Command('DataSets.CmdModeTransfer', 'Set3rdAxisMode', 'Stop')
#        self.data['uploads']['Start_Boresight'] = 0.0
#        self.data['uploads']['Command_Type'] = 0
#        self.data['uploads']['Preset_Boresight'] = 0.0
#        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
#                      'block_name': 'ACU_upload',
#                      'data': self.data['uploads']
#                      }
#        self.agent.publish_to_feed('acu_upload', acu_upload)
        self._set_job_done('control')
        return True, 'Moved to new 3rd axis position'

    @inlineCallbacks
    def preset_stop_clear(self, session, params):

        session.set_status('running')
        current_data = self.data['status']['summary']
        current_vel = current_data['Azimuth_current_velocity']
        current_pos = {'Az': current_data['Azimuth_current_position'],
                       'El': current_data['Elevation_current_position']}
        new_pos = {'Az': current_pos['Az'] + np.sign(current_vel) * current_vel,
                   'El': current_pos['El']}
        self.log.info('Changed to Preset')
        yield self.acu_control.go_to(new_pos['Az'], new_pos['El'])
        while round(current_pos['Az'] - new_pos['Az'], 1) != 0.:
            yield dsleep(0.5)
            current_data = self.data['status']['summary']
            current_pos = {'Az': current_data['Azimuth_current_position'],
                           'El': current_data['Elevation_current_position']}
        yield dsleep(2)  # give the platform time to settle in position
        yield self.acu_control.stop()
        self.log.info('Stopped')
        yield dsleep(2)
        yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                            'Clear Stack')
        self.log.info('Cleared stack (first attempt)')
        yield dsleep(5)
        yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                            'Clear Stack')
        self.log.info('Cleared stack (second attempt)')
        self._set_job_done('control')
        return True, 'Job completed'

    @inlineCallbacks
    def clear_faults(self, session, params):
        """clear_faults()

        **Task** - Clear any axis faults.

        """

        session.set_status('running')
        yield self.acu_control.clear_faults()
        self._set_job_done('control')
        return True, 'Job completed.'

    @inlineCallbacks
    def stop_and_clear(self, session, params):
        """stop_and_clear()

        **Task** - Change the azimuth and elevation modes to Stop and clear
        points uploaded to the stack.

        """

        session.set_status('running')
        i = 0
        while i < 5:
            modes = [self.data['status']['summary']['Azimuth_mode'],
                     self.data['status']['summary']['Elevation_mode'],
                     ]
            if self.acu_config['platform'] == 'satp':
                modes.append(self.data['status']['summary']['Boresight_mode'])
            elif self.acu_config['platform'] in ['ccat', 'lat']:
                modes.append(self.data['status']['third_axis']['Axis3_mode'])
            if modes != ['Stop', 'Stop', 'Stop']:
                yield self.acu_control.stop()
                self.log.info('Stop called (iteration %i)' %(i+1))
                yield dsleep(0.1)
                i += 1
            else:
                self.log.info('All axes in Stop mode')
                i = 5
        modes = [self.data['status']['summary']['Azimuth_mode'],
                 self.data['status']['summary']['Elevation_mode'],
                 ]
        if self.acu_config['platform'] == 'satp':
            modes.append(self.data['status']['summary']['Boresight_mode'])
        elif self.acu_config['platform'] in ['ccat', 'lat']:
            modes.append(self.data['status']['third_axis']['Axis3_mode'])
        if modes != ['Stop', 'Stop', 'Stop']:
            self.log.error('Axes could not be set to Stop!')
            self._set_job_done('control')
            return False, 'Could not set axes to Stop mode'
        j = 0
        while j < 5:
            free_stack = self.data['status']['summary']['Free_upload_positions']
            if free_stack < FULL_STACK:
                yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                                    'Clear Stack')
                self.log.info('Clear Stack called (iteration %i)' %(j+1))
                yield dsleep(0.1)
                j += 1
            else:
                self.log.info('Stack cleared')
                j = 5
        free_stack = self.data['status']['summary']['Free_upload_positions']
        if free_stack < FULL_STACK:
            self.log.warn('Stack not fully cleared!')
            self._set_job_done('control')
            return False, 'Could not clear stack'
#        self.log.info('Cleared stack.')
        self._set_job_done('control')
        return True, 'Job completed'

    @inlineCallbacks
    def fromfile_scan(self, session, params=None):
        """fromfile_scan(filename=None, simulator=None)

        **Task** - Upload and execute a scan pattern from numpy file.

        Parameters:
            filename (str): full path to desired numpy file. File contains
                an array of three lists ([list(times), list(azimuths),
                list(elevations)]).  Times begin from 0.0.
            simulator (bool): toggle for using the ACU simulator.
        """
        filename = params.get('filename')
        simulator = params.get('simulator')
        times, azs, els, vas, ves, azflags, elflags = sh.from_file(filename)
        if min(azs) <= self.motion_limits['azimuth']['lower'] or max(azs) >= self.motion_limits['azimuth']['upper']:
            return False, 'Azimuth location out of range!'
        if min(els) <= self.motion_limits['elevation']['lower'] or max(els) >= self.motion_limits['elevation']['upper']:
            return False, 'Elevation location out of range!'
        yield self._run_specified_scan(session, times, azs, els, vas, ves, azflags, elflags, azonly=False, simulator=simulator)
        yield True, 'Track completed'

#    @ocs_agent.param('azpts', type=tuple)
#    @ocs_agent.param('el', type=float)
#    @ocs_agent.param('azvel', type=float)
#    @ocs_agent.param('acc', type=float)
#    @ocs_agent.param('ntimes', type=int)
#    @ocs_agent.param('azonly', type=bool)
#    @ocs_agent.param('simulator', default=False, type=bool)
    @inlineCallbacks
    def constant_velocity_scan(self, session, params=None):
        """constant_velocity_scan(azpts=None, el=None, azvel=None, acc=None, \
                                  ntimes=None, azonly=None, simulator=False)

        **Task** - Run a constant velocity scan.

        Parameters:
            azpts (tuple): spatial endpoints of the azimuth scan
            el (float): elevation (constant) throughout the scan
            azvel (float): velocity of the azimuth axis
            acc (float): acceleration of the turnaround
            ntimes (int): number of times the platform traverses
                between azimuth endpoints
            azonly (bool): option for scans with azimuth motion and
                elevation in Stop
            simulator (bool): toggle option for ACU simulator

        """
        azpts = params['azpts']
        el = params['el']
        azvel = params['azvel']
        acc = params['acc']
        ntimes = params['ntimes']
        azonly = params['azonly']
        simulator = params['simulator']
        if abs(acc) > self.motion_limits['acc']:
            raise ocs_agent.ParamError('Acceleration too great!')
        if min(azpts) <= self.motion_limits['azimuth']['lower'] or max(azpts) >= self.motion_limits['azimuth']['upper']:
            raise ocs_agent.ParamError('Azimuth location out of range!')
        if el <= self.motion_limits['elevation']['lower'] or el >= self.motion_limits['elevation']['upper']:
            raise ocs_agent.ParamError('Elevation location out of range!')
        times, azs, els, vas, ves, azflags, elflags = sh.constant_velocity_scanpoints(azpts, el, azvel, acc, ntimes)
        yield self._run_specified_scan(session, times, azs, els, vas, ves, azflags, elflags, azonly, simulator)
        return True, 'Track completed.'

    @inlineCallbacks
    def _run_specified_scan(self, session, times, azs, els, vas, ves, azflags, elflags, azonly, simulator):

        session.set_status('running')
        bcast_check = yield self._check_daq_streams('broadcast')
        monitor_check = yield self._check_daq_streams('monitor')
        if not bcast_check or not monitor_check:
            self._set_job_done('control')
            return False, 'Cannot complete scan with process not running.'

        if self.data['status']['platform_status']['Remote_mode'] == 0:
            self.log.warn('ACU in local mode, cannot perform motion with OCS.')
            self._set_job_done('control')
            return False, 'ACU not in remote mode.'

        UPLOAD_GROUP_SIZE = 120
        UPLOAD_THRESHOLD = FULL_STACK - 100

        # start_az = azs[0]
        # start_el = els[0]
        end_az = azs[-1]
        end_el = els[-1]

#        self.data['uploads']['Start_Azimuth'] = start_az
#        self.data['uploads']['Start_Elevation'] = start_el
#        self.data['uploads']['Command_Type'] = 2

#        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
#                      'block_name': 'ACU_upload',
#                      'data': self.data['uploads']
#                      }
#        self.agent.publish_to_feed('acu_upload', acu_upload)

        # Follow the scan in ProgramTrack mode, then switch to Stop mode
        all_lines = sh.ptstack_format(times, azs, els, vas, ves, azflags, elflags)
        self.log.info('all_lines generated')
        self.data['uploads']['PtStack_Lines'] = 'True'
        if azonly:
            yield self.acu_control.azmode('ProgramTrack')
        else:
            yield self.acu_control.mode('ProgramTrack')
        self.log.info('mode is now ProgramTrack')
        if simulator:
            group_size = len(all_lines)
        else:
            group_size = UPLOAD_GROUP_SIZE
        spec = {'times': times,
                'azs': azs,
                'els': els,
                'vas': vas,
                'ves': ves,
                'azflags': azflags,
                'elflags': elflags,
                }
        while len(all_lines):
            upload_lines = all_lines[:group_size]
            all_lines = all_lines[group_size:]
            # upload_vals = front_group(spec, group_size)
            spec = pop_first_vals(spec, group_size)

#            for u in range(len(upload_vals['azs'])):
#                self.data['uploads']['PtStack_Time'] = upload_lines[u].split(';')[0]
#                self.data['uploads']['PtStack_Azimuth'] = upload_vals['azs'][u]
#                self.data['uploads']['PtStack_Elevation'] = upload_vals['els'][u]
#                self.data['uploads']['PtStack_AzVelocity'] = upload_vals['vas'][u]
#                self.data['uploads']['PtStack_ElVelocity'] = upload_vals['ves'][u]
#                self.data['uploads']['PtStack_AzFlag'] = upload_vals['azflags'][u]
#                self.data['uploads']['PtStack_ElFlag'] = upload_vals['elflags'][u]
#                self.data['uploads']['PtStack_ctime'] = uploadtime_to_ctime(self.data['uploads']['PtStack_Time'], int(self.data['status']['summary']['Year']))
#                acu_upload = {'timestamp': self.data['uploads']['PtStack_ctime'],
#                              'block_name': 'ACU_upload',
#                              'data': self.data['uploads']
#                              }
#                self.agent.publish_to_feed('acu_upload', acu_upload, from_reactor=True)
            text = ''.join(upload_lines)
            yield dsleep(0.05)
            free_positions = self.data['status']['summary']['Free_upload_positions']
            while free_positions < UPLOAD_THRESHOLD:
                free_positions = self.data['status']['summary']['Free_upload_positions']
                az_mode = self.data['status']['summary']['Azimuth_mode']
                yield dsleep(0.05)
                if az_mode == 'Stop':
                    self.log.warn('Scan aborted!')
                    return False, 'Mode changed to Stop'
                elif az_mode != 'ProgramTrack':
                    self.log.warn(f'Unexpected azimuth mode: "{az_mode}"!')
                    return False, f'Mode changed to {az_mode}'
            yield self.acu_control.http.UploadPtStack(text)
            self.log.info('Uploaded a group')
        self.log.info('No more lines to upload')
        free_positions = self.data['status']['summary']['Free_upload_positions']
        while free_positions < FULL_STACK - 1:
            yield dsleep(0.1)
            modes = (self.data['status']['summary']['Azimuth_mode'],
                     self.data['status']['summary']['Elevation_mode'])
            if azonly:
                if modes[0] != 'ProgramTrack':
                    return False, 'Azimuth mode no longer ProgramTrack!!'
            else:
                if modes != ('ProgramTrack', 'ProgramTrack'):
                    return False, 'Fault triggered (not ProgramTrack)!'
            free_positions = self.data['status']['summary']['Free_upload_positions']
        self.log.info('No more points in the queue')
#        current_az = self.data['broadcast']['Corrected_Azimuth']
#        current_el = self.data['broadcast']['Corrected_Elevation']
        current_az = self.data['status']['summary']['Azimuth_current_position']
        current_el = self.data['status']['summary']['Elevation_current_position']
        while round(current_az - end_az, 1) != 0.:
            self.log.info('Waiting to settle at azimuth position')
            yield dsleep(0.1)
            current_az = self.data['status']['summary']['Azimuth_current_position']
           # current_az = self.data['broadcast']['Corrected_Azimuth']
        if not azonly:
            while round(current_el - end_el, 1) != 0.:
                self.log.info('Waiting to settle at elevation position')
                yield dsleep(0.1)
                current_el = self.data['broadcast']['Corrected_Elevation']
        yield dsleep(self.sleeptime)
        yield self.acu_control.stop()
        # self.data['uploads']['Start_Azimuth'] = 0.0
        # self.data['uploads']['Start_Elevation'] = 0.0
        # self.data['uploads']['Command_Type'] = 0
        # self.data['uploads']['PtStack_Lines'] = 'False'
        # self.data['uploads']['PtStack_Time'] = '000, 00:00:00.000000'
        # self.data['uploads']['PtStack_Azimuth'] = 0.0
        # self.data['uploads']['PtStack_Elevation'] = 0.0
        # self.data['uploads']['PtStack_AzVelocity'] = 0.0
        # self.data['uploads']['PtStack_ElVelocity'] = 0.0
        # self.data['uploads']['PtStack_AzFlag'] = 0
        # self.data['uploads']['PtStack_ElFlag'] = 0
        # acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
        #               'block_name': 'ACU_upload',
        #               'data': self.data['uploads']
        #               }
        # self.agent.publish_to_feed('acu_upload', acu_upload)
        self._set_job_done('control')
        return True

    @inlineCallbacks
    def generate_scan(self, session, params):
        """generate_scan(az_endpoint1=None, az_endpoint2=None, az_speed=None, \
                         acc=None, el_endpoint1=None, el_endpoint2=None, \
                         el_speed=None, \
                         num_scans=None, num_batches=None, start_time=None, \
                         wait_to_start=None, step_time=None, batch_size=None, \
                         az_start=None)

        **Process** - Scan generator, currently only works for
        constant-velocity az scans with fixed elevation.

        Parameters:
            az_endpoint1 (float): first endpoint of a linear azimuth scan
            az_endpoint2 (float): second endpoint of a linear azimuth scan
            az_speed (float): azimuth speed for constant-velocity scan
            acc (float): turnaround acceleration for a constant-velocity scan
            el_endpoint1 (float): first endpoint of elevation motion
            el_endpoint2 (float): second endpoint of elevation motion. For dev,
                currently both el endpoints should be equal
            el_speed (float): speed of motion for a scan with changing
                elevation. For dev, currently set to 0.0
            num_scans (int or None): if not None, limits the scan
                to the specified number of constant velocity legs.
            num_batches (int or None): sets the number of batches for the
                generator to create. Default value is None (interpreted as infinite
                batches).
            start_time (float or None): a ctime at which to start the scan.
                Default is None, interpreted as now
            wait_to_start (float): number of seconds to wait before starting a
                scan. Default is 3 seconds
            step_time (float): time between points on the constant-velocity
                parts of the motion. Default is 0.1 s. Minimum 0.05 s
            batch_size (int): number of values to produce in each iteration.
                Default is 500. Batch size is reset to the length of one leg of the
                motion if num_batches is not None.
            ramp_up (float or None): make the first scan leg longer, by
                this number of degrees, on the starting end.  This is used
                to help the servo match the first leg velocity smoothly
                before it has to start worrying about the first
                turn-around.
            az_start (str): part of the scan to start at. Options are:
                'az_endpoint1', 'az_endpoint2', 'mid_inc' (start in the middle of
                the scan and start with increasing azimuth), 'mid_dec' (start in
                the middle of the scan and start with decreasing azimuth).
            scan_upload_length (float): number of seconds for each set of uploaded
                points. Default value is 10.0.
        """
        session.set_status('running')
        bcast_check = yield self._check_daq_streams('broadcast')
        monitor_check = yield self._check_daq_streams('monitor')
        if not bcast_check or not monitor_check:
            self._set_job_done('control')
            return False, 'Cannot complete go_to with process not running.'

        az_endpoint1 = params.get('az_endpoint1')
        az_endpoint2 = params.get('az_endpoint2')
        az_speed = params.get('az_speed')
        acc = params.get('acc')
        el_endpoint1 = params.get('el_endpoint1')
        azonly = params.get('azonly', True)
        scan_upload_len = params.get('scan_upload_length', 10.0)
        scan_params = {k: params.get(k) for k in [
            'num_scans', 'num_batches', 'start_time',
            'wait_to_start', 'step_time', 'batch_size', 'ramp_up', 'az_start']
            if params.get(k) is not None}
        el_endpoint2 = params.get('el_endpoint2', el_endpoint1)
        el_speed = params.get('el_speed', 0.0)

        if self.data['status']['platform_status']['Remote_mode'] == 0:
            self.log.warn('ACU in local mode, cannot perform motion with OCS.')
            self._set_job_done('control')
            return False, 'ACU not in remote mode.'

        if 'az_start' in scan_params:
            if scan_params['az_start'] in ('mid_inc', 'mid_dec'):
                init = 'mid'
            else:
                init = 'end'
        throw = az_endpoint2 - az_endpoint1

        plan, info = sh.plan_scan(az_end1=az_endpoint1, el=el_endpoint1,
                                  throw=throw, v_az=az_speed,
                                  a_az=acc, init=init)

        print(plan)
        print(info)

    #    self.log.info('Scan params are' + str(scan_params))
        if 'step_time' in scan_params:
            step_time = scan_params['step_time']
        else:
            step_time = 1.0
        scan_upload_len_pts = scan_upload_len / step_time
        print(scan_upload_len_pts)

        go_to_params = {'az': plan['az_startpoint'],
                        'el': plan['el'],
                        'azonly': False,
                        'end_stop': False,
                        'wait': 1,
                        'rounding': 2}

        yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                            'Clear Stack')

        self.log.info('Running go_to in generate_scan')
        yield self.go_to(session=session, params=go_to_params)
        self.log.info('Finished go_to, generating scan points')

        g = sh.generate_constant_velocity_scan(az_endpoint1=az_endpoint1,
                                               az_endpoint2=az_endpoint2,
                                               az_speed=az_speed, acc=acc,
                                               el_endpoint1=el_endpoint1,
                                               el_endpoint2=el_endpoint2,
                                               el_speed=el_speed, ramp_up=plan['ramp_up'],
                                               **scan_params)
        if azonly:
            yield self.acu_control.azmode('ProgramTrack')
        else:
            yield self.acu_control.mode('ProgramTrack')

        self.data['uploads']['Command_Type'] = 2
        yield dsleep(0.5)
        current_modes = {'Az': self.data['status']['summary']['Azimuth_mode'],
                         'El': self.data['status']['summary']['Elevation_mode'],
                         'Remote': self.data['status']['platform_status']['Remote_mode']}
        while current_modes['Az'] == 'ProgramTrack':
            if current_modes['Remote'] == 0:
                self.log.warn('ACU no longer in remote mode')
            try:
                lines = next(g)
            except StopIteration:
                break

            current_lines = lines
            group_size = int(scan_upload_len_pts)
            while len(current_lines):
                current_modes = {'Az': self.data['status']['summary']['Azimuth_mode'],
                                 'El': self.data['status']['summary']['Elevation_mode'],
                                 'Remote': self.data['status']['platform_status']['Remote_mode']}
                upload_lines = current_lines[:group_size]
                # for u in range(len(upload_lines)):
                #     self.data['uploads']['PtStack_Time'] = upload_lines[u].split(';')[0]
                #     self.data['uploads']['PtStack_Azimuth'] = float(upload_lines[u].split(';')[1])
                #     self.data['uploads']['PtStack_Elevation'] = float(upload_lines[u].split(';')[2])
                #     self.data['uploads']['PtStack_AzVelocity'] = float(upload_lines[u].split(';')[3])
                #     self.data['uploads']['PtStack_ElVelocity'] = float(upload_lines[u].split(';')[4])
                #     self.data['uploads']['PtStack_AzFlag'] = int(upload_lines[u].split(';')[5])
                #     self.data['uploads']['PtStack_ElFlag'] = int(upload_lines[u].split(';')[6].strip())
                #     self.data['uploads']['PtStack_ctime'] = uploadtime_to_ctime(self.data['uploads']['PtStack_Time'], int(self.data['status']['summary']['Year']))
                #     acu_upload = {'timestamp': self.data['uploads']['PtStack_ctime'],
                #                   'block_name': 'ACU_upload',
                #                   'data': self.data['uploads']}
                #     self.agent.publish_to_feed('acu_upload', acu_upload, from_reactor=True)
                text = ''.join(upload_lines)
                current_lines = current_lines[group_size:]
                free_positions = self.data['status']['summary']['Free_upload_positions']
                while free_positions < 10000 - 10:# - scan_upload_len_pts:
                    yield dsleep(0.1)
                    free_positions = self.data['status']['summary']['Free_upload_positions']
                print(text)
                yield self.acu_control.http.UploadPtStack(text)

        self.log.info('All points uploaded, waiting for stack to clear.')

        # Wait at least 1 second before reading the free positions, to
        # make sure its updated.
        free_positions = 0
        while free_positions < FULL_STACK - 1:
            yield dsleep(1)
            free_positions = self.data['status']['summary']['Free_upload_positions']
            self.log.info(f'There are {FULL_STACK - free_positions} track points remaining.')
            # todo: Should also watch for mode change, here, to exit cleanly...

        self.log.info('The track should now be completed.')
        # Go to Stop mode?
        # yield self.acu_control.stop()

        # Clear the stack, but wait a bit or it can cause a fault.
        yield dsleep(1)
        yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                            'Clear Stack')

        # self.data['uploads']['Start_Azimuth'] = 0.0
        # self.data['uploads']['Start_Elevation'] = 0.0
        # self.data['uploads']['Command_Type'] = 0
        # self.data['uploads']['PtStack_Lines'] = 'False'
        # self.data['uploads']['PtStack_Time'] = '000, 00:00:00.000000'
        # self.data['uploads']['PtStack_Azimuth'] = 0.0
        # self.data['uploads']['PtStack_Elevation'] = 0.0
        # self.data['uploads']['PtStack_AzVelocity'] = 0.0
        # self.data['uploads']['PtStack_ElVelocity'] = 0.0
        # self.data['uploads']['PtStack_AzFlag'] = 0
        # self.data['uploads']['PtStack_ElFlag'] = 0
        # acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
        #               'block_name': 'ACU_upload',
        #               'data': self.data['uploads']
        #               }
        # self.agent.publish_to_feed('acu_upload', acu_upload)
        self._set_job_done('control')
        return True, 'Track ended cleanly'


def add_agent_args(parser_in=None):
    if parser_in is None:
        parser_in = argparse.ArgumentParser()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--acu_config")
    return parser_in


def main(args=None):
    parser = add_agent_args()
    args = site_config.parse_args(agent_class='ACUAgent',
                                  parser=parser,
                                  args=args)
    print(args)
#    print('args.acu_config = '+str(args.acu_config))
    agent, runner = ocs_agent.init_site_agent(args)
    _ = ACUAgent(agent, args.acu_config)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
