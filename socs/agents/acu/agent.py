import argparse
import calendar
import datetime
import struct
import time
from enum import Enum

import numpy as np
import soaculib as aculib
import soaculib.status_keys as status_keys
import twisted.web.client as tclient
from autobahn.twisted.util import sleep as dsleep
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from soaculib.twisted_backend import TwistedHttpBackend
from twisted.internet import protocol, reactor
from twisted.internet.defer import DeferredList, inlineCallbacks

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
        # Separate locks for exclusive access to az/el, and boresight motions.
        self.azel_lock = TimeoutLock()
        self.boresight_lock = TimeoutLock()

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

        tclient._HTTP11ClientFactory.noisy = False

        self.acu_control = aculib.AcuControl(
            acu_config, backend=TwistedHttpBackend(persistent=False))
        self.acu_read = aculib.AcuControl(
            acu_config, backend=TwistedHttpBackend(persistent=True), readonly=True)

        agent.register_process('monitor',
                               self.monitor,
                               self._simple_process_stop,
                               blocking=False,
                               startup=True)
#        agent.register_process('monitor_spem',
#                               self.monitor_spem,
#                               lambda
        agent.register_process('broadcast',
                               self.broadcast,
                               self._simple_process_stop,
                               blocking=False,
                               startup=True)
        agent.register_process('generate_scan',
                               self.generate_scan,
                               self._simple_process_stop,
                               blocking=False,
                               startup=False)
        agent.register_process('restart_idle',
                               self.restart_idle,
                               self._simple_process_stop,
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
        agent.register_task('go_to',
                            self.go_to,
                            blocking=False,
                            aborter=self._simple_task_abort)
        agent.register_task('constant_velocity_scan',
                            self.constant_velocity_scan,
                            blocking=False,
                            aborter=self._abort_motion_op_azel)
        agent.register_task('fromfile_scan',
                            self.fromfile_scan,
                            blocking=False,
                            aborter=self._abort_motion_op_azel)
        agent.register_task('set_boresight',
                            self.set_boresight,
                            blocking=False,
                            aborter=self._simple_task_abort)
        agent.register_task('stop_and_clear',
                            self.stop_and_clear,
                            blocking=False)
        agent.register_task('preset_stop_clear_azel',
                            self.preset_stop_clear_azel,
                            blocking=False)
        agent.register_task('preset_stop_clear_boresight',
                            self.preset_stop_clear_boresight,
                            blocking=False)
        agent.register_task('clear_faults',
                            self.clear_faults,
                            blocking=False)

    @inlineCallbacks
    def _simple_task_abort(self, session, params):
        # Trigger a task abort by updating state to "stopping"
        yield session.set_status('stopping')

    @inlineCallbacks
    def _simple_process_stop(self, session, params):
        # Trigger a process stop by updating state to "stopping"
        yield session.set_status('stopping')

    @inlineCallbacks
    def _abort_motion_op_azel(self, session, params):
        if session.status == 'running':
            session.set_status('stopping')
            yield dsleep(0.1)
            print(session.status)
        self.agent.start('preset_stop_clear_azel', params)
        yield

    @inlineCallbacks
    def restart_idle(self, session, params):
        session.set_status('running')
        while session.status in ['running']:
            resp = yield self.acu_control.http.Command('DataSets.CmdModeTransfer',
                                                       'RestartIdleTime')
            self.log.info('Sent RestartIdleTime')
            self.log.info(resp)
            yield dsleep(1. * 60.)
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

        session.set_status('running')
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

        j = yield self.acu_read.http.Values(self.acu8100)
        if self.acu3rdaxis:
            j2 = yield self.acu_read.http.Values(self.acu3rdaxis)
        else:
            j2 = {}
        session.data = {'StatusDetailed': j,
                        'Status3rdAxis': j2,
                        'StatusResponseRate': n_ok / (query_t - report_t)}

        was_remote = False

        while session.status in ['running']:
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
                if self.acu3rdaxis:
                    j2 = yield self.acu_read.http.Values(self.acu3rdaxis)
                else:
                    j2 = {}
                session.data.update({'StatusDetailed': j, 'Status3rdAxis': j2})
                n_ok += 1
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
                if not isinstance(v, float):
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
                if was_remote:
                    was_remote = False
                    self.log.warn('ACU in local mode!')
            elif not was_remote:
                was_remote = True
                self.log.warn('ACU now in remote mode.')
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
        return True, 'Acquisition exited cleanly.'

    @inlineCallbacks
    def broadcast(self, session, params):
        """broadcast()

        **Process** - Read UDP data from the port specified by self.acu_config,
        decode it, and publish to an HK feed.

        """
        session.set_status('running')
        FMT = self.udp_schema['format']
        FMT_LEN = struct.calcsize(FMT)
        UDP_PORT = self.udp['port']
        udp_data = []
        fields = self.udp_schema['fields']
        session.data = {}

        class MonitorUDP(protocol.DatagramProtocol):
            def datagramReceived(self, data, src_addr):
                host, port = src_addr
                offset = 0
                while len(data) - offset >= FMT_LEN:
                    d = struct.unpack(FMT, data[offset:offset + FMT_LEN])
                    udp_data.append(d)
                    offset += FMT_LEN

        handler = reactor.listenUDP(int(UDP_PORT), MonitorUDP())
        influx_data = {}
        influx_data['Time_bcast_influx'] = []
        for i in range(2, len(fields)):
            influx_data[fields[i].replace(' ', '_') + '_bcast_influx'] = []

        active = True
        last_packet_time = time.time()

        while session.status in ['running']:
            now = time.time()
            if len(udp_data) >= 200:
                if not active:
                    self.log.info('UDP packets are being received.')
                    active = True
                last_packet_time = now

                process_data = udp_data[:200]
                udp_data = udp_data[200:]
                year = datetime.datetime.now().year
                gyear = calendar.timegm(time.strptime(str(year), '%Y'))
                # if len(process_data):
                #     sample_rate = (len(process_data)
                #                    / ((process_data[-1][0] - process_data[0][0]) * 86400
                #                    + process_data[-1][1] - process_data[0][1]))
                # else:
                #     sample_rate = 0.0
                for d in process_data:
                    gday = (d[0] - 1) * 86400
                    sec = d[1]
                    data_ctime = gyear + gday + sec
                    self.data['broadcast']['Time'] = data_ctime
                    influx_data['Time_bcast_influx'].append(data_ctime)
                    for i in range(2, len(d)):
                        self.data['broadcast'][fields[i].replace(' ', '_')] = d[i]
                        influx_data[fields[i].replace(' ', '_') + '_bcast_influx'].append(d[i])
                    acu_udp_stream = {'timestamp': self.data['broadcast']['Time'],
                                      'block_name': 'ACU_broadcast',
                                      'data': self.data['broadcast']
                                      }
                    self.agent.publish_to_feed('acu_udp_stream',
                                               acu_udp_stream, from_reactor=True)
                influx_means = {}
                for key in influx_data.keys():
                    influx_means[key] = np.mean(influx_data[key])
                    influx_data[key] = []
                acu_broadcast_influx = {'timestamp': influx_means['Time_bcast_influx'],
                                        'block_name': 'ACU_bcast_influx',
                                        'data': influx_means,
                                        }
                self.agent.publish_to_feed('acu_broadcast_influx', acu_broadcast_influx, from_reactor=True)
                sd = {}
                for ky in influx_means:
                    sd[ky.split('_bcast_influx')[0]] = influx_means[ky]
                session.data.update(sd)
            else:
                if active and now - last_packet_time > 3:
                    self.log.info('No UDP packets are being received.')
                    active = False
                yield dsleep(1)
            yield dsleep(0.005)

        handler.stopListening()
        return True, 'Acquisition exited cleanly.'

    @inlineCallbacks
    def _check_daq_streams(self, stream):
        yield
        session = self.agent.sessions[stream]
        if session.status != 'running':
            self.log.warn("Process '%s' is not running" % stream)
            return False
        if stream == 'broadcast':
            timestamp = self.data['broadcast'].get('Time')
        else:
            timestamp = self.data['status']['summary'].get('ctime')
        if timestamp is None:
            self.log.warn('%s daq stream has no data yet.' % stream)
            return False
        delta = time.time() - timestamp
        if delta > 2:
            self.log.warn(f'{stream} daq stream has old data ({delta} seconds)')
            return False
        return True

    @inlineCallbacks
    def _check_ready_motion(self, session):
        bcast_check = yield self._check_daq_streams('broadcast')
        monitor_check = yield self._check_daq_streams('monitor')
        if not bcast_check or not monitor_check:
            return False, 'Cannot complete motion because of problem with data acq processes.'

        if self.data['status']['platform_status']['Remote_mode'] == 0:
            self.log.warn('ACU in local mode, cannot perform motion with OCS.')
            return False, 'ACU not in remote mode.'

        return True, 'Agent state ok for motion.'

    def _get_limit_func(self, axis):
        """Construct a function limit(x) that will enforce that x is within
        the configured limits for axis.  Returns the funcion and the
        tuple of limits (lower, upper).

        """
        limits = self.motion_limits[axis.lower()]
        limits = limits['lower'], limits['upper']

        def limit_func(target):
            return max(min(target, limits[1]), limits[0])
        return limit_func, limits

    @inlineCallbacks
    def _go_to_axis(self, session, axis, target):
        """Execute a movement, using "Preset" mode, on a specific axis.

        Args:
          session: session object variable of the parent operation.
          axis (str): one of 'Azimuth', 'Elevation', 'Boresight'.
          target (float): target position.

        Returns:
          ok (bool): True if the motion completed successfully and
            arrived at target position.
          msg (str): success/error message.

        """
        # Step time in event loop.
        TICK_TIME = 0.1

        # Time for which to sample distance for "still" and "moving"
        # conditions.
        PROFILE_TIME = 1.

        # When aborting, how many seconds to use to project a good
        # stopping position (d = v*t)
        ABORT_TIME = 2.

        # Threshold (deg) for declaring that we've reached
        # destination.
        THERE_YET = 0.01

        # How long to wait after initiation for signs of motion,
        # before giving up.  This is normally within 2 or 3 seconds
        # (SATP), but in "cold" cases where siren needs to sound, this
        # can be as long as 12 seconds.
        MAX_STARTUP_TIME = 13.

        # Velocity to assume when computing maximum time a move should take (to bail
        # out in unforeseen circumstances).
        UNREASONABLE_VEL = 0.5

        # Positive acknowledgment of AcuControl.go_to
        OK_RESPONSE = b'OK, Command executed.'

        # Enum for the motion states
        State = Enum(f'{axis}State',
                     ['INIT', 'WAIT_MOVING', 'WAIT_STILL', 'FAIL', 'DONE'])

        # Specialization for different axis types.
        if axis in ['Azimuth', 'Elevation']:
            def get_pos():
                return self.data['status']['summary'][f'{axis}_current_position']

            def get_vel():
                return self.data['status']['summary'][f'{axis}_current_velocity']

            def get_mode():
                return self.data['status']['summary'][f'{axis}_mode']

            if axis == 'Azimuth':
                @inlineCallbacks
                def goto(target):
                    result = yield self.acu_control.go_to(az=target)
                    return result
            else:
                @inlineCallbacks
                def goto(target):
                    result = yield self.acu_control.go_to(el=target)
                    return result

        elif axis in ['Boresight']:
            def get_pos():
                return self.data['status']['summary'][f'{axis}_current_position']

            def get_vel():
                return 0.

            def get_mode():
                return self.data['status']['summary'][f'{axis}_mode']

            @inlineCallbacks
            def goto(target):
                result = yield self.acu_control.go_3rd_axis(target)
                return result
        else:
            return False, f"No configuration for axis={axis}"

        limit_func, _ = self._get_limit_func(axis)

        # History of recent distances from target.
        history = []

        def get_history(t):
            # Returns (ok, hist) where hist is roughly the past t
            # seconds of position data and ok is whether or not
            # that much history was actually available.
            n = int(t // TICK_TIME) + 1
            return (n <= len(history)), history[-n:]

        last_state = None
        state = State.INIT
        start_time = None
        motion_aborted = False
        assumption_fail = False
        motion_completed = False
        give_up_time = None
        has_never_moved = True

        while session.status in ['starting', 'running', 'stopping']:
            # Time ...
            now = time.time()
            if start_time is None:
                start_time = now
            time_since_start = now - start_time
            motion_expected = time_since_start > MAX_STARTUP_TIME

            # Space ...
            current_pos, current_vel = get_pos(), get_vel()
            distance = abs(target - current_pos)
            history.append(distance)
            if give_up_time is None:
                give_up_time = now + distance / UNREASONABLE_VEL \
                    + MAX_STARTUP_TIME + 2 * PROFILE_TIME

            # Do we seem to be moving / not moving?
            ok, _d = get_history(PROFILE_TIME)
            still = ok and (np.std(_d) < 0.01)
            moving = ok and (np.std(_d) >= 0.01)
            has_never_moved = (has_never_moved and not moving)

            near_destination = distance < THERE_YET
            mode_ok = (get_mode() == 'Preset')

            # Log only on state changes
            if state != last_state:
                self.log.info(f'{axis}.state={state.name:<11} '
                              f'dt={now-start_time:.3f} '
                              f'dist={distance:.3f}')
                last_state = state

            # Handle task abort
            if session.status == 'stopping' and not motion_aborted:
                target = limit_func(current_pos + current_vel * ABORT_TIME)
                state = State.INIT
                motion_aborted = True

            # Turn "too long" into an immediate exit.
            if now > give_up_time:
                self.log.error('Motion did not complete in a timely fashion; exiting.')
                assumption_fail = True
                break

            # Main state machine
            if state == State.INIT:
                # Set target position and change mode to Preset.
                result = yield goto(target)
                if result == OK_RESPONSE:
                    state = State.WAIT_MOVING
                else:
                    self.log.error(f'ACU rejected go_to with message: {result}')
                    state = State.FAIL
                # Reset the clock for tracking "still" / "moving".
                history = []
                start_time = time.time()

            elif state == State.WAIT_MOVING:
                # Position and mode change requested, now wait for
                # either mode change or clear failure of motion.
                if mode_ok:
                    state = state.WAIT_STILL
                elif still and motion_expected:
                    self.log.error(f'Motion did not start within {MAX_STARTUP_TIME:.1f} s.')
                    state = state.FAIL

            elif state == State.WAIT_STILL:
                # Once moving, watch for end of motion.
                if not mode_ok:
                    self.log.error('Unexpected axis mode transition; exiting.')
                    state = State.FAIL
                elif still:
                    if near_destination:
                        state = State.DONE
                    elif has_never_moved and motion_expected:
                        # The settling time, near a soft limit, can be
                        # a bit long ... so only timeout on
                        # motion_expected if we've never moved at all.
                        self.log.error(f'Motion did not start within {MAX_STARTUP_TIME:.1f} s.')
                        state = State.FAIL

            elif state == State.FAIL:
                # Move did not complete as planned.
                assumption_fail = True
                break

            elif state == State.DONE:
                # We seem to have arrived at destination.
                motion_completed = True
                break

            # Keep only ~20 seconds of history ...
            _, history = get_history(20.)

            yield dsleep(TICK_TIME)

        success = motion_completed and not (motion_aborted or assumption_fail)

        if success:
            msg = 'Move complete.'
        elif motion_aborted:
            msg = 'Move aborted!'
        else:
            msg = 'Irregularity during motion!'
        return success, msg

    @ocs_agent.param('az', type=float)
    @ocs_agent.param('el', type=float)
    @ocs_agent.param('wait', default=None, type=float)  # temporary for ocs-web
    @ocs_agent.param('end_stop', default=False, type=bool)
    @inlineCallbacks
    def go_to(self, session, params):
        """go_to(az=None, el=None, end_stop=False)

        **Task** - Move the telescope to a particular point (azimuth,
        elevation) in Preset mode. When motion has ended and the telescope
        reaches the preset point, it returns to Stop mode and ends.

        Parameters:
            az (float): destination angle for the azimuthal axis
            el (float): destination angle for the elevation axis
            end_stop (bool): put the telescope in Stop mode at the end of
                the motion

        """
        with self.azel_lock.acquire_timeout(0, job='go_to') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.azel_lock.job} is running."

            ok, msg = yield self._check_ready_motion(session)
            if not ok:
                return False, msg

            target_az = params['az']
            target_el = params['el']

            for axis, target in {'azimuth': target_az, 'elevation': target_el}.items():
                limit_func, limits = self._get_limit_func(axis)
                if target != limit_func(target):
                    raise ocs_agent.ParamError(
                        f'{axis}={target} not in accepted range, '
                        f'[{limits[0]}, {limits[1]}].')

            self.log.info(f'Commanded position: az={target_az}, el={target_el}')
            session.set_status('running')

            moves = yield DeferredList([
                self._go_to_axis(session, 'Azimuth', target_az),
                self._go_to_axis(session, 'Elevation', target_el),
            ])
            all_ok, msgs = True, []
            for _ok, result in moves:
                if _ok:
                    all_ok = all_ok and result[0]
                    msgs.append(result[1])
                else:
                    all_ok = False
                    msgs.append(f'Crash! {result}')

            if all_ok:
                msg = msgs[0]
            else:
                msg = f'az: {msgs[0]} el: {msgs[1]}'

            if all_ok and params['end_stop']:
                yield self.acu_control.mode('Stop')

        return all_ok, msg

    @ocs_agent.param('b', type=float)
    @ocs_agent.param('end_stop', default=False, type=bool)
    @inlineCallbacks
    def set_boresight(self, session, params):
        """set_boresight(b=None, end_stop=False)

        **Task** - Move the telescope to a particular third-axis angle.

        Parameters:
            b (float): destination angle for boresight rotation
            end_stop (bool): put axes in Stop mode after motion

        """
        with self.boresight_lock.acquire_timeout(0, job='set_boresight') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.boresight_lock.job} is running."

            ok, msg = yield self._check_ready_motion(session)
            if not ok:
                return False, msg

            target = params['b']

            for axis, target in {'boresight': target}.items():
                limit_func, limits = self._get_limit_func(axis)
                if target != limit_func(target):
                    raise ocs_agent.ParamError(
                        f'{axis}={target} not in accepted range, '
                        f'[{limits[0]}, {limits[1]}].')

            self.log.info(f'Commanded position: boresight={target}')
            session.set_status('running')

            ok, msg = yield self._go_to_axis(session, 'Boresight', target)

            if ok and params['end_stop']:
                yield self.acu_control.http.Command('DataSets.CmdModeTransfer',
                                                    'Set3rdAxisMode', 'Stop')

        return ok, msg

    @inlineCallbacks
    def preset_stop_clear_azel(self, session, params):

        session.set_status('running')
        current_data = self.data['status']['summary']
        current_vel = {'Az': current_data['Azimuth_current_velocity'],
                       'El': current_data['Elevation_current_velocity']}
        print(current_vel)

        current_pos = {'Az': current_data['Azimuth_current_position'],
                       'El': current_data['Elevation_current_position']}
        print(current_pos)
        new_az = current_pos['Az'] + (3 * np.sign(current_vel['Az']) * current_vel)
        if new_az >= self.motion_limits['azimuth']['upper']:
            new_az = self.motion_limits['azimuth']['upper']
        if new_az <= self.motion_limits['azimuth']['lower']:
            new_az = self.motion_limits['azimuth']['lower']
        new_pos = {'Az': new_az,
                   'El': current_pos['El']}
        print(new_pos)
        self.log.info('Az and El changed to Preset')
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
        return True, 'Job completed'

    @inlineCallbacks
    def preset_stop_clear_boresight(self, session, params):
        if self.acu_config['platform'] == 'satp':
            axis = 'Boresight'
        else:
            axis = 'Axis3'
        current_data = self.data['status']['summary']

        current_pos = current_data[axis + '_current_position']
        new_pos = current_pos
        self.log.info('Boresight now set to ' + str(new_pos))
        self.log.info(axis + ' changed to Preset')
        yield self.acu_control.go_3rd_axis(new_pos)
        current_pos = self.data['status']['summary'][axis + '_current_position']
        while round(current_pos - new_pos, 1) != 0.:
            yield dsleep(0.5)
            current_pos = self.data['status']['summary'][axis + '_current_position']
        yield dsleep(2)  # give the platform time to settle in position
        yield self.acu_control.http.Command('DataSets.CmdModeTransfer', 'Set3rdAxisMode', 'Stop')
        yield dsleep(2)
        yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                            'Clear Stack')
        self.log.info('Cleared stack (first attempt)')
        yield dsleep(5)
        yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                            'Clear Stack')
        self.log.info('Cleared stack (second attempt)')
        return True, 'Job completed'

    @inlineCallbacks
    def clear_faults(self, session, params):
        """clear_faults()

        **Task** - Clear any axis faults.

        """

        session.set_status('running')
        yield self.acu_control.clear_faults()
        session.set_status('stopping')
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
                self.log.info('Stop called (iteration %i)' % (i + 1))
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
            return False, 'Could not set axes to Stop mode'
        j = 0
        while j < 5:
            free_stack = self.data['status']['summary']['Free_upload_positions']
            if free_stack < FULL_STACK:
                yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                                    'Clear Stack')
                self.log.info('Clear Stack called (iteration %i)' % (j + 1))
                yield dsleep(0.1)
                j += 1
            else:
                self.log.info('Stack cleared')
                j = 5
        free_stack = self.data['status']['summary']['Free_upload_positions']
        if free_stack < FULL_STACK:
            self.log.warn('Stack not fully cleared!')
            return False, 'Could not clear stack'

        session.set_status('stopping')
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
        session.set_status('running')
        filename = params.get('filename')
        simulator = params.get('simulator')
        times, azs, els, vas, ves, azflags, elflags = sh.from_file(filename)
        if min(azs) <= self.motion_limits['azimuth']['lower'] or max(azs) >= self.motion_limits['azimuth']['upper']:
            session.set_status('stopping')
            return False, 'Azimuth location out of range!'
        if min(els) <= self.motion_limits['elevation']['lower'] or max(els) >= self.motion_limits['elevation']['upper']:
            session.set_status('stopping')
            return False, 'Elevation location out of range!'
        while session.status == 'running':
            yield self._run_specified_scan(session, times, azs, els, vas, ves, azflags, elflags, azonly=False, simulator=simulator)
        session.set_status('stopping')
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
        session.set_status('running')
        if abs(acc) > self.motion_limits['acc']:
            raise ocs_agent.ParamError('Acceleration too great!')
        if min(azpts) <= self.motion_limits['azimuth']['lower'] or max(azpts) >= self.motion_limits['azimuth']['upper']:
            raise ocs_agent.ParamError('Azimuth location out of range!')
        if el <= self.motion_limits['elevation']['lower'] or el >= self.motion_limits['elevation']['upper']:
            raise ocs_agent.ParamError('Elevation location out of range!')
        times, azs, els, vas, ves, azflags, elflags = sh.constant_velocity_scanpoints(azpts, el, azvel, acc, ntimes)
        while session.status == 'running':
            yield self._run_specified_scan(session, times, azs, els, vas, ves, azflags, elflags, azonly, simulator)
        session.set_status('stopping')
        return True, 'Track completed.'

    @inlineCallbacks
    def _run_specified_scan(self, session, times, azs, els, vas, ves, azflags, elflags, azonly, simulator):

        session.set_status('running')
        while session.status == 'running':
            bcast_check = yield self._check_daq_streams('broadcast')
            monitor_check = yield self._check_daq_streams('monitor')
            if not bcast_check or not monitor_check:
                session.set_status('stopping')
                return False, 'Cannot complete scan with process not running.'

        if self.data['status']['platform_status']['Remote_mode'] == 0:
            self.log.warn('ACU in local mode, cannot perform motion with OCS.')
            return False, 'ACU not in remote mode.'

        UPLOAD_GROUP_SIZE = 120
        UPLOAD_THRESHOLD = FULL_STACK - 100

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
        # current_az = self.data['broadcast']['Corrected_Azimuth']
        # current_el = self.data['broadcast']['Corrected_Elevation']
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
        bcast_check = yield self._check_daq_streams('broadcast')
        monitor_check = yield self._check_daq_streams('monitor')
        if not bcast_check or not monitor_check:
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
            return False, 'ACU not in remote mode.'

        # if 'az_start' in scan_params:
        #     if scan_params['az_start'] in ('mid_inc', 'mid_dec'):
        #         init = 'mid'
        #     else:
        #         init = 'end'
        # throw = az_endpoint2 - az_endpoint1

        # plan, info = sh.plan_scan(az_end1=az_endpoint1, el=el_endpoint1,
        #                          throw=throw, v_az=az_speed,
        #                          a_az=acc, init=init)
        # print(plan)
        # print(info)

        if 'step_time' in scan_params:
            step_time = scan_params['step_time']
        else:
            step_time = 1.0
        scan_upload_len_pts = scan_upload_len / step_time

        # go_to_params = {'az': plan['az_startpoint'],
        #                'el': plan['el'],
        #                'azonly': False,
        #                'end_stop': False,
        #                'wait': 1,
        #                'rounding': 2}

        yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                            'Clear Stack')

        # self.log.info('Running go_to in generate_scan')
        # yield self.go_to(session=session, params=go_to_params)
        # self.agent.start('go_to', go_to_params)
        # self.log.info('Finished go_to, generating scan points')

        g = sh.generate_constant_velocity_scan(az_endpoint1=az_endpoint1,
                                               az_endpoint2=az_endpoint2,
                                               az_speed=az_speed, acc=acc,
                                               el_endpoint1=el_endpoint1,
                                               el_endpoint2=el_endpoint2,
                                               el_speed=el_speed,
                                               # ramp_up=plan['ramp_up'],
                                               **scan_params)
        with self.azel_lock.acquire_timeout(0, job='generate_scan') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.azel_lock.job} is running."
            session.set_status('running')
            while session.status == 'running':
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
                #             self.data['uploads']['PtStack_AzVelocity'] = float(upload_lines[u].split(';')[3])
                #             self.data['uploads']['PtStack_ElVelocity'] = float(upload_lines[u].split(';')[4])
                #             self.data['uploads']['PtStack_AzFlag'] = int(upload_lines[u].split(';')[5])
                #             self.data['uploads']['PtStack_ElFlag'] = int(upload_lines[u].split(';')[6].strip())
                #             self.data['uploads']['PtStack_ctime'] = uploadtime_to_ctime(self.data['uploads']['PtStack_Time'], int(self.data['status']['summary']['Year']))
                #             acu_upload = {'timestamp': self.data['uploads']['PtStack_ctime'],
                #                           'block_name': 'ACU_upload',
                #                           'data': self.data['uploads']}
                #             self.agent.publish_to_feed('acu_upload', acu_upload, from_reactor=True)
                        text = ''.join(upload_lines)
                        current_lines = current_lines[group_size:]
                        free_positions = self.data['status']['summary']['Free_upload_positions']
                        while free_positions < 10000 - 10:  # - scan_upload_len_pts:
                            yield dsleep(0.1)
                            free_positions = self.data['status']['summary']['Free_upload_positions']
    #                    print(text)
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
                break  # so why am I in a loop?
            # Go to Stop mode?
            # yield self.acu_control.stop()

            # Clear the stack, but wait a bit or it can cause a fault.
            # Yes, sometimes you have to wait a very long time ...
            yield dsleep(10)
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
        session.set_status('stopping')
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
