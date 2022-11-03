import argparse
import calendar
import datetime
import struct
import time

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
            'broadcast': 'idle',
            'control': 'idle',  # shared by all motion tasks/processes
            'scanspec': 'idle',
        }

        self.acu_config = aculib.guess_config(acu_config)
        self.sleeptime = self.acu_config['motion_waittime']
        self.udp = self.acu_config['streams']['main']
        self.udp_schema = aculib.get_stream_schema(self.udp['schema'])
        self.udp_ext = self.acu_config['streams']['ext']
        self.acu8100 = self.acu_config['status']['status_name']
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

    # Operation management.  This agent has several Processes that
    # must be able to alone or simultaneously.  The state of each is
    # registered in self.jobs, protected by self.lock (though this is
    # probably not necessary as long as we don't thread).  Any logic
    # to assess conflicts should probably be in _try_set_job.

    def _try_set_job(self, job_name):
        """
        Set a job status to 'run'.

        Parameters:
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

    def _set_job_stop(self, job_name):
        """
        Set a job status to 'stop'.

        Parameters:
            job_name (str): Name of the process you are trying to stop.
        """
        print('try to acquire stop')
        # return (False, 'Could not stop')
        with self.lock.acquire_timeout(timeout=1.0, job=job_name) as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it is"
                              f" held by {self.lock.job}")
                return False
            try:
                self.jobs[job_name] = 'stop'
            # state = self.jobs.get(job_name, 'idle')
            # if state == 'idle':
            #     return False, 'Job not running.'
            # if state == 'stop':
            #     return False, 'Stop already requested.'
            # self.jobs[job_name] = 'stop'
                return True, 'Requested Process stop.'
            except Exception as e:
                print(str(e))

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
    def monitor(self, session, params):
        """monitor()

        **Process** - Refresh the cache of SATP ACU status information and
        report it on the 'acu_status_summary' and 'acu_status_full' HK feeds.

        Summary parameters are ACU-provided time code, Azimuth mode,
        Azimuth position, Azimuth velocity, Elevation mode, Elevation position,
        Elevation velocity, Boresight mode, and Boresight position.

        """
        ok, msg = self._try_set_job('monitor')
        if not ok:
            return ok, msg

        session.set_status('running')
        version = yield self.acu_read.http.Version()
        self.log.info(version)

        mode_key = {'Stop': 0,
                    'Preset': 1,
                    'ProgramTrack': 2,
                    'Stow': 3,
                    'SurvivalMode': 4,
                    'Rate': 5,
                    'StarTrack': 6,
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
                yield dsleep(min_query_period - (now - query_t))

            query_t = time.time()
            try:
                j = yield self.acu_read.http.Values(self.acu8100)
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
                continue

            for (key, value) in session.data.items():
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
                            else:
                                influx_status[statkey + '_influx'] = mode_key[statval]
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
        ok, msg = self._try_set_job('broadcast')
        if not ok:
            return ok, msg
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

    @ocs_agent.param('az', type=float)
    @ocs_agent.param('el', type=float)
    @ocs_agent.param('wait', default=1., type=float)
    @ocs_agent.param('end_stop', default=False, type=bool)
    @ocs_agent.param('rounding', default=1, type=int)
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
        ok, msg = self._try_set_job('control')
        if not ok:
            return ok, msg
        az = params['az']
        el = params['el']
        if az <= self.motion_limits['azimuth']['lower'] or az >= self.motion_limits['azimuth']['upper']:
            raise ocs_agent.ParamError("Azimuth out of range! Must be "
                                       + f"{self.motion_limits['azimuth']['lower']} < az "
                                       + f"< {self.motion_limits['azimuth']['upper']}")
        if el <= self.motion_limits['elevation']['lower'] or el >= self.motion_limits['elevation']['upper']:
            raise ocs_agent.ParamError("Elevation out of range! Must be "
                                       + f"{self.motion_limits['elevation']['lower']} < el "
                                       + f"< {self.motion_limits['elevation']['upper']}")
        end_stop = params['end_stop']
        wait_for_motion = params['wait']
        round_int = params['rounding']
        self.log.info('Azimuth commanded position: ' + str(az))
        self.log.info('Elevation commanded position: ' + str(el))
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
        # self.log.info('Checking current position')
        yield self.acu_control.mode('Preset')
        if round(current_az, round_int) == az and \
                round(current_el, round_int) == el:
            yield self.acu_control.go_to(az, el, wait=0.1)
            self.log.info('Already at commanded position.')
            self._set_job_done('control')
            return True, 'Preset at commanded position'
        # yield self.acu.stop()
        # yield self.acu_control.mode('Stop')
        # self.log.info('Stopped')
        # yield dsleep(0.5)
        yield self.acu_control.go_to(az, el, wait=0.1)
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
                pe = round(mdata['Elevation_current_position'], round_int)
                pa = round(mdata['Azimuth_current_position'], round_int)
                if pe != el or pa != az:
                    yield self.acu_control.stop()
                    self.log.warn('Stopped before reaching commanded point!')
                    return False, 'Something went wrong!'
                modes = (mdata['Azimuth_mode'], mdata['Elevation_mode'])
                if modes != ('Preset', 'Preset'):
                    return False, 'Fault triggered!'
        if end_stop:
            yield self.acu_control.stop()
            self.log.info('Stop mode activated')
        self.data['uploads']['Start_Azimuth'] = 0.0
        self.data['uploads']['Start_Elevation'] = 0.0
        self.data['uploads']['Command_Type'] = 0
        self.data['uploads']['Preset_Azimuth'] = 0.0
        self.data['uploads']['Preset_Elevation'] = 0.0
        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload, from_reactor=True)
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
        ok, msg = self._try_set_job('control')
        if not ok:
            return ok, msg
        bs_destination = params.get('b')
        # yield self.acu_control.stop()
        yield dsleep(5)
        self.data['uploads']['Start_Boresight'] = self.data['status']['summary']['Boresight_current_position']
        self.data['uploads']['Command_Type'] = 1
        self.data['uploads']['Preset_Boresight'] = bs_destination
        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload)
        yield self.acu_control.go_3rd_axis(bs_destination)
        current_position = self.data['status']['summary']['Boresight_current_position']
        while current_position != bs_destination:
            yield dsleep(1)
            acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                          'block_name': 'ACU_upload',
                          'data': self.data['uploads']
                          }
            self.agent.publish_to_feed('acu_upload', acu_upload)
            current_position = self.data['status']['summary']['Boresight_current_position']
        if params.get('end_stop'):
            yield self.acu_control.stop()
        self.data['uploads']['Start_Boresight'] = 0.0
        self.data['uploads']['Command_Type'] = 0
        self.data['uploads']['Preset_Boresight'] = 0.0
        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload)
        self._set_job_done('control')
        return True, 'Moved to new 3rd axis position'

    @inlineCallbacks
    def stop_and_clear(self, session, params):
        """stop_and_clear()

        **Task** - Change the azimuth and elevation modes to Stop and clear
        points uploaded to the stack.

        """
        ok, msg = self._try_set_job('control')
        if not ok:
            self._set_job_done('control')
            yield dsleep(0.1)
            self._try_set_job('control')
        self.log.info('_try_set_job ok')
        # yield self.acu.stop()
        yield self.acu_control.mode('Stop')
        self.log.info('Stop called')
        yield dsleep(5)
        yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                            'Clear Stack')
        yield dsleep(0.1)
        self.log.info('Cleared stack.')
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
        if min(azs) <= self.motion_limits['azimuth']['lower'] or max(azs) >= self.motion_limits['azimith']['upper']:
            return False, 'Azimuth location out of range!'
        if min(els) <= self.motion_limits['elevation']['lower'] or max(els) >= self.motion_limits['elevation']['upper']:
            return False, 'Elevation location out of range!'
        yield self._run_specified_scan(session, times, azs, els, vas, ves, azflags, elflags, azonly=False, simulator=simulator)
        yield True, 'Track completed'

    @ocs_agent.param('azpts', type=tuple)
    @ocs_agent.param('el', type=float)
    @ocs_agent.param('azvel', type=float)
    @ocs_agent.param('acc', type=float)
    @ocs_agent.param('ntimes', type=int)
    @ocs_agent.param('azonly', type=bool)
    @ocs_agent.param('simulator', default=False, type=bool)
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
        ok, msg = self._try_set_job('control')
        if not ok:
            return ok, msg
        self.log.info('_try_set_job ok')

        start_az = azs[0]
        start_el = els[0]
        end_az = azs[-1]
        end_el = els[-1]

        self.data['uploads']['Start_Azimuth'] = start_az
        self.data['uploads']['Start_Elevation'] = start_el
        self.data['uploads']['Command_Type'] = 2

        acu_upload = {'timestamp': self.data['status']['summary']['ctime'],
                      'block_name': 'ACU_upload',
                      'data': self.data['uploads']
                      }
        self.agent.publish_to_feed('acu_upload', acu_upload)

        # Follow the scan in ProgramTrack mode, then switch to Stop mode
        all_lines = sh.ptstack_format(times, azs, els, vas, ves, azflags, elflags)
        self.log.info('all_lines generated')
        self.data['uploads']['PtStack_Lines'] = 'True'
        if azonly:
            yield self.acu_control.azmode('ProgramTrack')
        else:
            yield self.acu_control.mode('ProgramTrack')
        m = yield self.acu_control.mode()
        print(m)
        self.log.info('mode is now ProgramTrack')
        if simulator:
            group_size = len(all_lines)
        else:
            group_size = 120
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
            upload_vals = front_group(spec, group_size)
            spec = pop_first_vals(spec, group_size)

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
                self.agent.publish_to_feed('acu_upload', acu_upload, from_reactor=True)
            text = ''.join(upload_lines)
            free_positions = self.data['status']['summary']['Free_upload_positions']
            while free_positions < 9899:
                free_positions = self.data['status']['summary']['Free_upload_positions']
                yield dsleep(0.1)
            yield self.acu_control.http.UploadPtStack(text)
            self.log.info('Uploaded a group')
        self.log.info('No more lines to upload')
        free_positions = self.data['status']['summary']['Free_upload_positions']
        while free_positions < 9999:
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
        current_az = self.data['broadcast']['Corrected_Azimuth']
        current_el = self.data['broadcast']['Corrected_Elevation']
        while round(current_az - end_az, 1) != 0.:
            self.log.info('Waiting to settle at azimuth position')
            yield dsleep(0.1)
            current_az = self.data['broadcast']['Corrected_Azimuth']
        if not azonly:
            while round(current_el - end_el, 1) != 0.:
                self.log.info('Waiting to settle at elevation position')
                yield dsleep(0.1)
                current_el = self.data['broadcast']['Corrected_Elevation']
        yield dsleep(self.sleeptime)
        yield self.acu_control.stop()
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
        self._set_job_done('control')
        return True

    @inlineCallbacks
    def generate_scan(self, session, params):
        """generate_scan(az_endpoint1=None, az_endpoint2=None, az_speed=None, \
                         acc=None, el_endpoint1=None, el_endpoint2=None, \
                         el_speed=None, num_batches=None, start_time=None, \
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
            az_start (str): part of the scan to start at. Options are:
                'az_endpoint1', 'az_endpoint2', 'mid_inc' (start in the middle of
                the scan and start with increasing azimuth), 'mid_dec' (start in
                the middle of the scan and start with decreasing azimuth).
        """
        ok, msg = self._try_set_job('control')
        if not ok:
            return ok, msg
        self.log.info('_try_set_job ok')
        az_endpoint1 = params.get('az_endpoint1')
        az_endpoint2 = params.get('az_endpoint2')
        az_speed = params.get('az_speed')
        acc = params.get('acc')
        el_endpoint1 = params.get('el_endpoint1')
        scan_params = {k: params.get(k) for k in ['num_batches', 'start_time',
                       'wait_to_start', 'step_time', 'batch_size', 'az_start']
                       if params.get(k) is not None}
        el_endpoint2 = params.get('el_endpoint2', el_endpoint1)
        el_speed = params.get('el_speed', 0.0)

        yield self.acu_control.stop()
        g = sh.generate_constant_velocity_scan(az_endpoint1=az_endpoint1,
                                               az_endpoint2=az_endpoint2,
                                               az_speed=az_speed, acc=acc,
                                               el_endpoint1=el_endpoint1,
                                               el_endpoint2=el_endpoint2,
                                               el_speed=el_speed,
                                               **scan_params)
        self.acu_control.mode('ProgramTrack')
        while self.jobs['control'] == 'run':
            lines = next(g)
            current_lines = lines
            group_size = 250
            while len(current_lines):
                upload_lines = current_lines[:group_size]
                text = ''.join(upload_lines)
                current_lines = current_lines[group_size:]
                free_positions = self.data['status']['summary']['Free_upload_positions']
                while free_positions < 5099:
                    yield dsleep(0.1)
                    free_positions = self.data['status']['summary']['Free_upload_positions']
                yield self.acu_control.http.UploadPtStack(text)
        yield self.acu_control.stop()
        self._set_job_done('control')
        return True, 'Track generation ended cleanly'


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

    agent, runner = ocs_agent.init_site_agent(args)
    _ = ACUAgent(agent, args.acu_config)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
