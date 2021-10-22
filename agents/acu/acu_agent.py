import time
import numpy as np
import struct
import datetime
import calendar
import soaculib as aculib
import scan_helpers as sh
from soaculib.twisted_backend import TwistedHttpBackend
import argparse
import soaculib.status_keys as status_keys
#import pickle
from twisted.internet import reactor, protocol
from twisted.internet.defer import inlineCallbacks
import twisted.web.client as tclient
from autobahn.twisted.util import sleep as dsleep
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock


def timecode(acutime):
    """
    Takes the time code produced by the ACU status stream and returns
    a ctime.

    Args:
        acutime (float): The time recorded by the ACU status stream,
                         corresponding to the fractional day of the year
    """
    sec_of_day = (acutime-1)*60*60*24
    year = datetime.datetime.now().year
    gyear = calendar.timegm(time.strptime(str(year), '%Y'))
    comptime = gyear+sec_of_day
    return comptime

def uploadtime_to_ctime(ptstack_time, upload_year):
    year = int(upload_year)
    gyear = calendar.timegm(time.strptime(str(year), '%Y'))
    day_of_year = float(ptstack_time.split(',')[0]) - 1.0
    hour = float(ptstack_time.split(',')[1].split(':')[0])
    minute = float(ptstack_time.split(',')[1].split(':')[1])
    second = float(ptstack_time.split(',')[1].split(':')[2])
    comptime = gyear + day_of_year*60*60*24 + hour*60*60 + minute*60 + second
    return comptime


class ACUAgent:

    """
    Agent to acquire data from an ACU and control telescope pointing with the
    ACU.

    Args:
        acu_config (str):
            The configuration for the ACU, as referenced in aculib.configs.
            Default value is 'guess'.
    """
    def __init__(self, agent, acu_config='guess'):
        self.lock = TimeoutLock()
        self.jobs = {
            'monitor': 'idle',
            'broadcast': 'idle',
            'control': 'idle',  # shared by all motion tasks/processes
            'scanspec': 'idle',
            }

        self.acu_config = aculib.guess_config(acu_config)
        self.base_url = self.acu_config['base_url']
        self.readonly_url = self.acu_config['readonly_url']
        self.sleeptime = self.acu_config['motion_waittime']
        self.udp = self.acu_config['streams']['main']
        self.udp_schema = aculib.get_stream_schema(self.udp['schema'])
        self.udp_ext = self.acu_config['streams']['ext']
        self.acu8100 = self.acu_config['status']['status_name']
        self.monitor_fields = status_keys.status_fields[self.acu_config['platform']]['status_fields']

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
                                },
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

        pool = tclient.HTTPConnectionPool(reactor)
        self.web_agent = tclient.Agent(reactor, pool=pool)
        tclient._HTTP11ClientFactory.noisy = False

        self.acu = aculib.AcuControl(
            'guess', backend=TwistedHttpBackend(self.web_agent))
        agent.register_process('monitor',
                               self.start_monitor,
                               lambda: self.set_job_stop('monitor'),
                               blocking=False,
                               startup=True)
        agent.register_process('broadcast',
                               self.start_udp_monitor,
                               lambda: self.set_job_stop('broadcast'),
                               blocking=False,
                               startup=True)
        agent.register_process('generate_scan',
                               self.generate_scan,
                               lambda: self.set_job_stop('generate_scan'),
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
        self.agent.register_feed('acu_status_summary',
                                 record=True,
                              #   agg_params=basic_agg_params,
                                 agg_params=fullstatus_agg_params,
                                 buffer_time=1)
        self.agent.register_feed('acu_status_axis_faults',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_position_errs',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_axis_limits',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_axis_warnings',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_axis_failures',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_axis_state',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_osc_alarms',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_commands',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_general_errs',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_platform',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_emergency',
                                  record=True,
                                  agg_params=fullstatus_agg_params,
                                  buffer_time=1)
        self.agent.register_feed('acu_status_influx',
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
        agent.register_task('run_specified_scan',
                            self.run_specified_scan,
                            blocking=False)
        agent.register_task('set_boresight',
                            self.set_boresight,
                            blocking=False)
        agent.register_task('stop_and_clear',
                            self.stop_and_clear,
                            blocking=False)
        agent.register_task('spec_scan_linear_turnaround',
                            self.spec_scan_linear_turnaround,
                            blocking=False)
        agent.register_task('spec_scan_fromfile',
                            self.spec_scan_fromfile,
                            blocking=False)
        agent.register_task('find_az_stop_point',
                            self.find_az_stop_point,
                            blocking=False)
        agent.register_task('find_el_stop_point',
                            self.find_el_stop_point,
                            blocking=False)

    # Operation management.  This agent has several Processes that
    # must be able to alone or simultaneously.  The state of each is
    # registered in self.jobs, protected by self.lock (though this is
    # probably not necessary as long as we don't thread).  Any logic
    # to assess conflicts should probably be in try_set_job.

    def try_set_job(self, job_name):
        """
        Set a job status to 'run'.

        Args:
            job_name (str): Name of the task/process you are trying to start.
        """
        with self.lock.acquire_timeout(timeout=1.0, job=job_name) as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it is held"
                              f" by {self.lock.job}")
                return False
            # Set running.
            self.jobs[job_name] = 'run'
            return (True, 'ok')

    def set_job_stop(self, job_name):
        """
        Set a job status to 'stop'.

        Args:
            job_name (str): Name of the process you are trying to stop.
        """
        with self.lock.acquire_timeout(timeout=1.0, job=job_name) as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it is"
                              f" held by {self.lock.job}")
                return False
            self.jobs[job_name] = 'stop'
#            state = self.jobs.get(job_name, 'idle')
#            if state == 'idle':
#                return False, 'Job not running.'
#            if state == 'stop':
#                return False, 'Stop already requested.'
#            self.jobs[job_name] = 'stop'
            return True, 'Requested Process stop.'

    def set_job_done(self, job_name):
        """
        Set a job status to 'idle'.

        Args:
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
    def start_monitor(self, session, params=None):
        """PROCESS "monitor".

        This process refreshes the cache of SATP ACU status information,
        and reports it on HK feeds 'acu_status_summary' and 'acu_status_full'.

        Summary parameters are ACU-provided time code, Azimuth mode,
        Azimuth position, Azimuth velocity, Elevation mode, Elevation position,
        Elevation velocity, Boresight mode, and Boresight position.

        """
        ok, msg = self.try_set_job('monitor')
        if not ok:
            return ok, msg

        session.set_status('running')

        mode_key = {'Stop': 0,
                    'Preset': 1,
                    'ProgramTrack': 2,
                    'Stow': 3,
                    'SurvivalMode': 4,
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
        while self.jobs['monitor'] == 'run':
            now = time.time()

            if now > report_t + report_period:
                self.log.info('Responses ok at %.3f Hz'
                              % (n_ok / (now - report_t)))
                report_t = now
                n_ok = 0

            if now - query_t < min_query_period:
                yield dsleep(-(now - query_t-min_query_period))

            query_t = time.time()
            try:
                j = yield self.acu.http.Values(self.acu8100)
                n_ok += 1
                session.data = j
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

            for (key, value) in session.data.items():
                for category in self.monitor_fields:
                    if key in self.monitor_fields[category]:
                        if type(value) == bool:
                            self.data['status'][category][self.monitor_fields[category][key]] = int(value)
                        elif type(value) == int or type(value) == float:
                            self.data['status'][category][self.monitor_fields[category][key]] = value
                        elif value == None:
                            self.data['status'][category][self.monitor_fields[category][key]] = float(0.0)#'None'
                        else:
                            self.data['status'][category][self.monitor_fields[category][key]] = str(value)
            self.data['status']['summary']['ctime'] =\
                timecode(self.data['status']['summary']['Time'])

            # influx_status refers to all other self.data['status'] keys. Do not add
            # more keys to any self.data['status'] categories beyond this point
            influx_status = {}
            for category in self.data['status']:
                for statkey in self.data['status'][category].keys():
                    if type(self.data['status'][category][statkey]) == float:
                        if self.data['status'][category][statkey] == float('nan'):
                            influx_status[statkey + '_influx'] = 0.0
                        else:
                            influx_status[statkey + '_influx'] = self.data['status'][category][statkey]
                    elif type(self.data['status'][category][statkey]) == str:
                        if self.data['status'][category][statkey] in ['None', 'True', 'False']:
                            influx_status[statkey + '_influx'] = tfn_key[self.data['status'][category][statkey]]
                        else:
                            influx_status[statkey + '_influx'] = mode_key[self.data['status'][category][statkey]]
                    elif type(self.data['status'][category][statkey]) == int:
                        if statkey in ['Year', 'Free_upload_positions']:
                            influx_status[statkey + '_influx'] = float(self.data['status'][category][statkey])
                        else:
                            influx_status[statkey + '_influx'] = int(self.data['status'][category][statkey])
                    else:
                        print(statkey)

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
#            acustatus_commands = {'timestamp': self.data['status']['summary']['ctime'],
#                                  'block_name': 'ACU_command_status',
#                                  'data': self.data['status']['commands']
#                                  }
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
            self.agent.publish_to_feed('acu_status_summary', acustatus_summary)
            self.agent.publish_to_feed('acu_status_axis_faults', acustatus_axisfaults)
            self.agent.publish_to_feed('acu_status_position_errs', acustatus_poserrors)
            self.agent.publish_to_feed('acu_status_axis_limits', acustatus_axislims)
            self.agent.publish_to_feed('acu_status_axis_warnings', acustatus_axiswarn)
            self.agent.publish_to_feed('acu_status_axis_failures', acustatus_axisfail)
            self.agent.publish_to_feed('acu_status_axis_state', acustatus_axisstate)
            self.agent.publish_to_feed('acu_status_osc_alarms', acustatus_oscalarm)
#            self.agent.publish_to_feed('acu_status_commands', acustatus_commands)
            self.agent.publish_to_feed('acu_status_general_errs', acustatus_acufails)
            self.agent.publish_to_feed('acu_status_platform', acustatus_platform)
            self.agent.publish_to_feed('acu_status_emergency', acustatus_emergency)
#            influx_status={'fake_data':1.0}
            try:
                self.agent.publish_to_feed('acu_status_influx', acustatus_influx, from_reactor=True)
            #    print(acustatus_influx)
            except:
#                print(acustatus_influx)
                print('failed')
        self.set_job_done('monitor')
        return True, 'Acquisition exited cleanly.'

    @inlineCallbacks
    def start_udp_monitor(self, session, params=None):
        """PROCESS broadcast

        This process reads UDP data from the port specified by self.acu_config,
        decodes it, and publishes to an HK feed.

        """
        ok, msg = self.try_set_job('broadcast')
        if not ok:
            return ok, msg
        session.set_status('running')
        FMT = self.udp_schema['format']#'<idddddddddddd'
        FMT_LEN = struct.calcsize(FMT)
        UDP_PORT = self.udp['port'] #self.acu_config['PositionBroadcast_target'].split(':')[1]
        udp_data = []
        fields = self.udp_schema['fields']
        class MonitorUDP(protocol.DatagramProtocol):

            def datagramReceived(self, data, src_addr):
                host, port = src_addr
                offset = 0
                while len(data) - offset >= FMT_LEN:
                    d = struct.unpack(FMT, data[offset:offset+FMT_LEN])
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
                    sample_rate = (len(process_data) /
                                  ((process_data[-1][0]-process_data[0][0])*86400
                                  + process_data[-1][1]-process_data[0][1]))
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
                pd0 = process_data[0]
                pd0_gday = (pd0[0]-1) * 86400
                pd0_sec = pd0[1]
                pd0_data_ctime = gyear + pd0_gday + pd0_sec
                pd0_azimuth_corrected = pd0[2]
                pd0_azimuth_raw = pd0[5]
                pd0_elevation_corrected = pd0[3]
                pd0_elevation_raw = pd0[6]
                bcast_first = {'Time_bcast_influx': pd0_data_ctime,
                               'Azimuth_Corrected_bcast_influx': pd0_azimuth_corrected,
                               'Azimuth_Raw_bcast_influx': pd0_azimuth_raw,
                               'Elevation_Corrected_bcast_influx': pd0_elevation_corrected,
                               'Elevation_Raw_bcast_influx': pd0_elevation_raw,
                               }
                acu_broadcast_influx = {'timestamp': bcast_first['Time_bcast_influx'],
                                        'block_name': 'ACU_position_bcast_influx',
                                        'data': bcast_first,
                                        }
                self.agent.publish_to_feed('acu_broadcast_influx', acu_broadcast_influx)
                for d in process_data:
                    gday = (d[0]-1) * 86400
                    sec = d[1]
                    data_ctime = gyear + gday + sec
                    self.data['broadcast']['Time'] = data_ctime
                    for i in range(2, len(d)):
                        self.data['broadcast'][fields[i].replace(' ', '_')] = d[i]
#                    azimuth_corrected = d[2]
#                    azimuth_raw = d[5]
#                    elevation_corrected = d[3]
#                    elevation_raw = d[6]
#                    boresight_corrected = d[4]
#                    boresight_raw = d[7]
#                    azimuth_motor_1 = d[8]
#                    azimuth_motor_2 = d[9]
#                    elevation_motor_1 = d[10]
#                    boresight_motor_1 = d[11]
#                    boresight_motor_2 = d[12]
#                    self.data['broadcast'] = {'Time': data_ctime,
#                                              'Azimuth_Corrected': azimuth_corrected,
#                                              'Azimuth_Raw': azimuth_raw,
#                                              'Elevation_Corrected': elevation_corrected,
#                                              'Elevation_Raw': elevation_raw,
#                                              'Boresight_Corrected': boresight_corrected,
#                                              'Boresight_Raw': boresight_raw,
#                                              'Azimuth_Motor_1': azimuth_motor_1,
#                                              'Azimuth_Motor_2': azimuth_motor_2,
#                                              'Elevation_Motor_1': elevation_motor_1,
#                                              'Boresight_Motor_1': boresight_motor_1,
#                                              'Boresight_Motor_2': boresight_motor_2,
#                                              }
                    acu_udp_stream = {'timestamp': self.data['broadcast']['Time'],
                                      'block_name': 'ACU_broadcast',
                                      'data': self.data['broadcast']
                                      }
                    self.agent.publish_to_feed('acu_udp_stream',
                                               acu_udp_stream)
            else:
                yield dsleep(1)
            yield dsleep(0.005)

        handler.stopListening()
        self.set_job_done('broadcast')
        return True, 'Acquisition exited cleanly.'

    @inlineCallbacks
    def find_az_stop_point(self, session, params=None):
        ok, msg = self.try_set_job('control')
        if not ok:
            return ok, msg
        az = params.get('az')
        wait_for_motion = params.get('wait', 1)
        current_az = round(self.data['broadcast']['Corrected_Azimuth'], 4)
        current_el = round(self.data['broadcast']['Corrected_Elevation'], 4)

        # Check whether the telescope is already at the point
        self.log.info('Checking current position')
        if current_az == az:
            self.log.info('Already positioned at %.2f'
                          % (current_az))
            self.set_job_done('control')
            return False, 'Could not find stop times.'
        # find az stop time
        yield self.acu.stop()
        self.log.info('Stopped')
        yield dsleep(0.1)
        last20az = []
        yield self.acu.go_to(az, current_el)
        motion_start = time.time()
        mdata = self.data['status']['summary']
        # Wait for telescope to start moving
        self.log.info('Moving to commanded position')
        while mdata['Azimuth_current_velocity'] == 0.0:
            yield dsleep(wait_for_motion)
            mdata = self.data['status']['summary']
        moving = True
        while moving:
            mdata = self.data['status']['summary']
            current_az = mdata['Azimuth_current_position']
            if len(last20az) < 20:
                last20az.append(current_az)
                yield dsleep(0.005)
            else:
                while round(current_az, 4) != az:
                    yield dsleep(0.005)
                    mdata = self.data['status']['summary']
                    current_az = mdata['Azimuth_current_position']
                reached_az = time.time()
                last20az = last20az[1:]
                last20az.append(current_az)
                avel = np.gradient(last20az)
                absavg = np.mean(abs(avel))
                if absavg < 0.0001:
                    moving = False
                else:
                    moving = True
        motion_end = time.time()
        yield self.acu.stop()
        determine_stop = motion_end - reached_az
        self.stop_times['az'] = determine_stop
        print('az_stop: ' + str(determine_stop))
        self.set_job_done('control')
        return True, 'Azimuth stop time determined.'

    @inlineCallbacks
    def find_el_stop_point(self, session, params=None):
        ok, msg = self.try_set_job('control')
        if not ok:
            return ok, msg
        el = params.get('el')
        wait_for_motion = params.get('wait', 1)
        current_az = round(self.data['broadcast']['Corrected_Azimuth'], 4)
        current_el = round(self.data['broadcast']['Corrected_Elevation'], 4)

        # Check whether the telescope is already at the point
        self.log.info('Checking current position')
        if current_el == el:
            self.log.info('Already positioned at %.2f'
                          % (current_el))
            self.set_job_done('control')
            return False, 'Could not find stop time.'
        # find az stop time
        yield self.acu.stop()
        self.log.info('Stopped')
        yield dsleep(0.1)
        last20el = []
        yield self.acu.go_to(current_az, el)
        motion_start = time.time()
        mdata = self.data['status']['summary']
        # Wait for telescope to start moving
        self.log.info('Moving to commanded position')
        while mdata['Elevation_current_velocity'] == 0.0:
            yield dsleep(wait_for_motion)
            mdata = self.data['status']['summary']
        moving = True
        while moving:
            mdata = self.data['status']['summary']
            current_el = mdata['Elevation_current_position']
            if len(last20el) < 20:
                last20el.append(current_el)
                yield dsleep(0.005)
            else:
                while round(current_el, 4) != el:
                    yield dsleep(0.005)
                    mdata = self.data['status']['summary']
                    current_el = mdata['Elevation_current_position']
                reached_el = time.time()
                last20el = last20el[1:]
                last20el.append(current_el)
                evel = np.gradient(last20el)
                absavg = np.mean(abs(evel))
                if absavg < 0.0001:
                    moving = False
                else:
                    moving = True
        motion_end = time.time()
        yield self.acu.stop()
        determine_stop = motion_end - reached_el
        self.stop_times['el'] = determine_stop
        print('el_stop: ' + str(determine_stop))
        self.set_job_done('control')
        return True, 'Elevation stop time determined.' 

    @inlineCallbacks
    def go_to(self, session, params=None):
        """ TASK "go_to"

        Moves the telescope to a particular point (azimuth, elevation)
        in Preset mode. When motion has ended and the telescope reaches
        the preset point, it returns to Stop mode and ends.

        Params:
            az (float): destination angle for the azimuthal axis
            el (float): destination angle for the elevation axis
            wait (float): amount of time to wait for motion to end
        """
        ok, msg = self.try_set_job('control')
        if not ok:
            return ok, msg
        az = params.get('az')
        el = params.get('el')
        wait_for_motion = params.get('wait', 1)
        current_az = round(self.data['broadcast']['Corrected_Azimuth'], 4)
        current_el = round(self.data['broadcast']['Corrected_Elevation'], 4)
        self.data['uploads']['Start_Azimuth'] = current_az
        self.data['uploads']['Start_Elevation'] = current_el
        self.data['uploads']['Command_Type'] = 1
        self.data['uploads']['Preset_Azimuth'] = az
        self.data['uploads']['Preset_Elevation'] = el

        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload)

        # Check whether the telescope is already at the point
        self.log.info('Checking current position')
        if current_az == az and current_el == el:
            self.log.info('Already positioned at %.2f, %.2f'
                          % (current_az, current_el))
            self.set_job_done('control')
            return True, 'Pointing completed'
        yield self.acu.stop()
        self.log.info('Stopped')
        yield dsleep(0.1)
        yield self.acu.go_to(az, el)
        mdata = self.data['status']['summary']
        # Wait for telescope to start moving
        self.log.info('Moving to commanded position')
        while mdata['Azimuth_current_velocity'] == 0.0 and\
                mdata['Elevation_current_velocity'] == 0.0:
            yield dsleep(wait_for_motion)
            mdata = self.data['status']['summary']
        moving = True
        while moving:
            acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
            self.agent.publish_to_feed('acu_upload', acu_upload)
            mdata = self.data['status']['summary']
            ve = round(mdata['Elevation_current_velocity'], 2)
            va = round(mdata['Azimuth_current_velocity'], 2)
            if (ve != 0.0) or (va != 0.0):
                moving = True
                yield dsleep(wait_for_motion)
            else:
                moving = False
                mdata = self.data['status']['summary']
                pe = round(mdata['Elevation_current_position'], 2)
                pa = round(mdata['Azimuth_current_position'], 2)
                if pe != el or pa != az:
                    yield self.acu.stop()
                    self.log.warn('Stopped before reaching commanded point!')
                    return False, 'Something went wrong!'
                modes = (mdata['Azimuth_mode'], mdata['Elevation_mode'])
                if modes != ('Preset', 'Preset'):
                    return False, 'Fault triggered!'

        yield self.acu.stop()
        self.data['uploads']['Start_Azimuth'] = 0.0
        self.data['uploads']['Start_Elevation'] = 0.0
        self.data['uploads']['Command_Type'] = 0
        self.data['uploads']['Preset_Azimuth'] = 0.0
        self.data['uploads']['Preset_Elevation'] = 0.0
        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload)
        self.set_job_done('control')
        return True, 'Pointing completed'

    @inlineCallbacks
    def set_boresight(self, session, params=None):
        """TASK set_boresight

        Moves the telescope to a particular third-axis angle.

        Params:
            b (float): destination angle for boresight rotation
        """
        ok, msg = self.try_set_job('control')
        if not ok:
            return ok, msg
        bs_destination = params.get('b')
        yield self.acu.stop()
        yield dsleep(5)
        self.data['uploads']['Start_Boresight'] = self.data['status']['summary']['Boresight_current_position']
        self.data['uploads']['Command_Type'] = 1
        self.data['uploads']['Preset_Boresight'] = bs_destination
        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload)
        yield self.acu.go_3rd_axis(bs_destination)
        current_position = self.data['status']['summary']\
            ['Boresight_current_position']
        while current_position != bs_destination:
            yield dsleep(1)
            acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                          'block_name': 'ACU_upload',
                          'data': self.data['uploads']
                          }
            self.agent.publish_to_feed('acu_upload', acu_upload)
            current_position = self.data['status']['summary']\
                ['Boresight_current_position']
        yield self.acu.stop()
        self.data['uploads']['Start_Boresight'] = 0.0
        self.data['uploads']['Command_Type'] = 0
        self.data['uploads']['Preset_Boresight'] = 0.0
        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload)
        self.set_job_done('control')
        return True, 'Moved to new 3rd axis position'

    @inlineCallbacks
    def stop_and_clear(self, session, params=None):
        """TASK stop_and_clear

        Changes the azimuth and elevation modes to Stop and clears
        points uploaded to the stack.

        """
        ok, msg = self.try_set_job('control')
        if not ok:
            self.set_job_done('control')
            yield dsleep(0.1)
            self.try_set_job('control')
        self.log.info('try_set_job ok')
        yield self.acu.stop()
        self.log.info('Stop called')
        yield dsleep(5)
        yield self.acu.http.Command('DataSets.CmdTimePositionTransfer',
                                    'Clear Stack')
        yield dsleep(0.1)
        self.log.info('Cleared stack.')
        self.set_job_done('control')
        return True, 'Job completed'

    @inlineCallbacks
    def spec_scan_fromfile(self, session, params=None):
        filename = params.get('filename')
        times, azs, els, vas, ves, azflags, elflags = sh.from_file(filename)
        self.data['scanspec'] = {'times': times,
                                 'azs': azs,
                                 'els': els,
                                 'vas': vas,
                                 'ves': ves,
                                 'azflags': azflags,
                                 'elflags': elflags
                                 }
        self.log.info('Scan from file specified')
        yield True, 'Scan from file specified'

    @inlineCallbacks
    def spec_scan_linear_turnaround(self, session, params=None):
        azpts = params.get('azpts')
        el = params.get('el')
        azvel = params.get('azvel')
        acc = params.get('acc')
        ntimes = params.get('ntimes')
        times, azs, els, vas, ves, azflags, elflags = sh.linear_turnaround_scanpoints(azpts, el, azvel, acc, ntimes)
        self.data['scanspec'] = {'times': times,
                                 'azs': azs,
                                 'els': els,
                                 'vas': vas,
                                 'ves': ves,
                                 'azflags': azflags,
                                 'elflags': elflags
                                 }
        print('SPECED')
        self.log.info('Scan linear turnaround scan specified')
        return True, 'Scan linear turnaround scan specified'

    @inlineCallbacks
    def run_specified_scan(self, session, params=None):
        """TASK run_specified_scan

        Upload and execute a scan pattern. The pattern may be specified by a
        numpy file, parameters for a linear scan in one direction, or a linear
        scan with a turnaround.

        Params:
            scantype (str): the type of scan information you are uploading.
                            Options are 'from_file', 'linear_1dir', or
                            'linear_turnaround'.
        Optional params:
            filename (str): full path to desired numpy file. File contains an
                            array of three lists ([list(times), list(azimuths),
                            list(elevations)]). Times begin from 0.0. Applies
                            to scantype 'from_file'.
            azpts (tuple): spatial endpoints of the azimuth scan. Applies to
                           scantype 'linear_1dir' (2 values) and
                           'linear_turnaround' (3 values).
            el (float): elevation for a linear velocity azimuth scan. Applies
                        to scantype 'linear_1dir' and 'linear_turnaround'.
            azvel (float): velocity of the azimuth axis in a linear velocity
                           azimuth scan. Applies to scantype 'linear_1dir' and
                           'linear_turnaround'.
            acc (float): acceleration of the turnaround for a linear velocity
                         scan with a turnaround. Applies to scantype
                         'linear_turnaround'.
            ntimes (int): number of times the platform traverses between
                          azimuth endpoints for a 'linear_turnaround' scan.
        """
        ok, msg = self.try_set_job('control')
        if not ok:
            return ok, msg
        self.log.info('try_set_job ok')

        # Move to the starting position for the scan and then switch to Stop
        # mode
        scantype = params.get('scantype')
        times = self.data['scanspec']['times']
        azs = self.data['scanspec']['azs']
        els = self.data['scanspec']['els']
        vas = self.data['scanspec']['vas']
        ves = self.data['scanspec']['ves']
        azflags = self.data['scanspec']['azflags']
        elflags = self.data['scanspec']['elflags']
 
        start_az = azs[0]
        start_el = els[0]

        self.data['uploads']['Start_Azimuth'] = start_az
        self.data['uploads']['Start_Elevation'] = start_el
        self.data['uploads']['Command_Type'] = 2

        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload)

        # Follow the scan in ProgramTrack mode, then switch to Stop mode
        all_lines = sh.ptstack_format(times, azs, els, vas, ves, azflags,
                                       elflags)
  #      with open('/home/simons/code/vertex-acu-agent/test_clients/'+str(time.time())+'_test.pkl','wb') as f:
  #          pickle.dump(all_lines, f)
  #      f.close()
        self.log.info('all_lines generated')
        self.data['uploads']['PtStack_Lines'] = 'True'
        yield self.acu.mode('ProgramTrack')
        self.log.info('mode is now ProgramTrack')
        group_size = 120
        while len(all_lines):
            upload_lines = all_lines[:group_size]
            upload_vals = {'azs': azs[:group_size],
                           'els': els[:group_size],
                           'vas': vas[:group_size],
                           'ves': ves[:group_size],
                           'azflags': azflags[:group_size],
                           'elflags': elflags[:group_size]
                           }
            for u in range(len(upload_vals['azs'])):
                self.data['uploads']['PtStack_Time'] = upload_lines[u].split(';')[0]
                self.data['uploads']['PtStack_Azimuth'] = upload_vals['azs'][u]
                self.data['uploads']['PtStack_Elevation'] = upload_vals['els'][u]
                self.data['uploads']['PtStack_AzVelocity'] = upload_vals['vas'][u]
                self.data['uploads']['PtStack_ElVelocity'] = upload_vals['ves'][u]
                self.data['uploads']['PtStack_AzFlag'] = upload_vals['azflags'][u]
                self.data['uploads']['PtStack_ElFlag'] = upload_vals['elflags'][u]
                self.data['uploads']['PtStack_ctime'] = uploadtime_to_ctime(self.data['uploads']['PtStack_Time'], int(self.data['status']['summary']['Year']))
                acu_upload = {'timestamp': self.data['uploads']['PtStack_ctime'],
                              'block_name': 'ACU_upload',
                              'data': self.data['uploads']
                              }
                print(acu_upload)
 #               print(self.data['uploads']['PtStack_Time'])
 #               print(time.time())
                self.agent.publish_to_feed('acu_upload', acu_upload)
            text = ''.join(upload_lines)
            all_lines = all_lines[group_size:]
            free_positions = self.data['status']['summary']\
                ['Free_upload_positions']
            while free_positions < 9899:
                free_positions = self.data['status']['summary']\
                    ['Free_upload_positions']
                yield dsleep(0.1)
            yield self.acu.http.UploadPtStack(text)
            #print(upload_lines)
            #for u in upload_lines:
# TODO: switch over to pre-line formatting
#                self.data['uploads']['PtStack_Time'] = u.split(';')[0]
#                self.data['uploads']['PtStack_Azimuth'] = float(u.split(';')[1])
#                self.data['uploads']['PtStack_Elevation'] = float(u.split(';')[2])
#                self.data['uploads']['PtStack_AzVelocity'] = float(u.split(';')[3])
#                self.data['uploads']['PtStack_ElVelocity'] = float(u.split(';')[4])
#                self.data['uploads']['PtStack_AzFlag'] = int(u.split(';')[5])
#                self.data['uploads']['PtStack_ElFlag'] = int(u.split(';')[6])
#                yield dsleep (0.2)
#                print(upload_publish_dict)
#                acu_upload = {'timestamp': self.data['broadcast']['Time'],
#                              'block_name': 'ACU_upload',
#                              'data': upload_publish_dict
#                              }
#                self.agent.publish_to_feed('acu_upload', acu_upload)
            self.log.info('Uploaded a group')
        self.log.info('No more lines to upload')
        current_az = round(self.data['broadcast']['Corrected_Azimuth'], 4)
        current_el = round(self.data['broadcast']['Corrected_Elevation'], 4)
        while current_az != azs[-1] or current_el != els[-1]:
            yield dsleep(0.1)
            modes = (self.data['status']['summary']['Azimuth_mode'],
                     self.data['status']['summary']['Elevation_mode'])
            if modes != ('ProgramTrack', 'ProgramTrack'):
                return False, 'Fault triggered (not ProgramTrack)!'
            current_az = round(self.data['broadcast']['Corrected_Azimuth'], 4)
            current_el = round(self.data['broadcast']['Corrected_Elevation'],
                               4)
        yield dsleep(self.sleeptime)
        yield self.acu.stop()
        self.data['uploads']['Start_Azimuth'] = 0.0
        self.data['uploads']['Start_Elevation'] = 0.0
        self.data['uploads']['Command_Type'] = 0
        self.data['uploads']['PtStack_Lines'] = 'False'
        self.data['uploads']['PtStack_Time'] = '000, 00:00:00.000000'
        self.data['uploads']['PtStack_Azimuth'] = 0.0
        self.data['uploads']['PtStack_Elevation'] = 0.0
        self.data['uploads']['PtStack_AzVelocity'] = 0.0
        self.data['uploads']['PtStack_ElVelocity'] = 0.0
        self.data['uploads']['PtStack_AzFlag'] = 0
        self.data['uploads']['PtStack_ElFlag'] = 0
        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload)
        self.set_job_done('control')
        return True, 'Track completed.'

    @inlineCallbacks
    def generate_scan(self, session, params=None):
        """
        Scan generator, currently only works for constant-velocity az scans
        with fixed elevation.

        Args:
            scantype (str): type of scan you are generating. For dev, preset to
                'linear'.
            stop_iter (float): how many times the generator should generate a
                new set of points before forced to stop
            az_endpoint1 (float): first endpoint of a linear azimuth scan
            az_endpoint2 (float): second endpoint of a linear azimuth scan
            az_speed (float): azimuth speed for constant-velocity scan
            acc (float): turnaround acceleration for a constant-velocity scan
            el_endpoint1 (float): first endpoint of elevation motion
            el_endpoint2 (float): second endpoint of elevation motion. For dev,
                currently both el endpoints should be equal
            el_speed (float): speed of motion for a scan with changing
                elevation. For dev, currently set to 0.0

        """
        ok, msg = self.try_set_job('control')
        if not ok:
            return ok, msg
        self.log.info('try_set_job ok')
#        scantype = params.get('scantype')
        scantype = 'linear'
        stop_iter = params.get('stop_iter')
        az_endpoint1 = params.get('az_endpoint1')
        az_endpoint2 = params.get('az_endpoint2')
        az_speed = params.get('az_speed')
        acc = params.get('acc')
        el_endpoint1 = params.get('el_endpoint1')
        el_endpoint2 = params.get('el_endpoint2')
        el_speed = params.get('el_speed')

        self.log.info('scantype is ' + str(scantype))

        yield self.acu.stop()
        if scantype != 'linear':
            self.log.warn('Scan type not supported')
            return False
        g = sh.generate(stop_iter, az_endpoint1, az_endpoint2,
                        az_speed, acc, el_endpoint1, el_endpoint2, el_speed)
        self.acu.mode('ProgramTrack')
        while True:
            lines = next(g)
            current_lines = lines
            group_size = 250
            while len(current_lines):
                upload_lines = current_lines[:group_size]
                text = ''.join(upload_lines)
                current_lines = current_lines[group_size:]
                free_positions = self.data['status']['summary']\
                    ['Free_upload_positions']
                while free_positions < 5099:
                    yield dsleep(0.1)
                    free_positions = self.data['status']['summary']\
                        ['Free_upload_positions']
                yield self.acu.http.UploadPtStack(text)
        yield self.acu.stop()
        self.set_job_done('control')
        return True, 'Track generation ended cleanly'


def add_agent_args(parser_in=None):
    if parser_in is None:
        parser_in = argparse.ArgumentParser()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--acu_config", default="guess")
    return parser_in


if __name__ == '__main__':
    parser = add_agent_args()
    args = site_config.parse_args(agent_class='ACUAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    acu_agent = ACUAgent(agent, args.acu_config)

    runner.run(agent, auto_reconnect=True)
