import time
import numpy as np
import struct
import datetime
import calendar
import soaculib as aculib
import scan_helpers as sh
from soaculib.twisted_backend import TwistedHttpBackend
import argparse

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
            }

        self.acu_config = aculib.guess_config(acu_config)
        self.base_url = self.acu_config['base_url']
        self.sleeptime = self.acu_config['motion_waittime']
        self.udp = self.acu_config['streams']['main']
        self.udp_ext = self.acu_config['streams']['ext']

        self.log = agent.log

        # self.data provides a place to reference data from the monitors.
        # 'status' is populated by the monitor operation
        # 'broadcast' is populated by the udp_monitor operation
        self.data = {'status': {'summary': {}, 'full_status': {}},
                     'broadcast': {},
                     'uploads': {},
                     }

        self.health_check = {'broadcast': False, 'status': False}

        self.agent = agent

        self.take_data = False

        self.web_agent = tclient.Agent(reactor)
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
        agg_params = {'frame_length': 60}
        self.agent.register_feed('acu_status_summary',
                                 record=True,
                                 agg_params={'frame_length': 60,
                                             'exclude_influx': True
                                             },
                                 buffer_time=1)
        self.agent.register_feed('acu_status_full',
                                 record=True,
                                 agg_params={'frame_length': 60,
                                             'exclude_influx': True
                                             },
                                 buffer_time=1)
        self.agent.register_feed('acu_status_influx',
                                 record=True,
                                 agg_params={'frame_length': 60,
                                             'exclude_aggregator': True
                                             },
                                 buffer_time=1)
        self.agent.register_feed('acu_udp_stream',
                                 record=True,
                                 agg_params={'frame_length': 60,
                                             'exclude_influx': True
                                             },
                                 buffer_time=1)
        self.agent.register_feed('acu_broadcast_influx',
                                 record=False,
                                 agg_params={'frame_length': 60,
                                             'exclude_aggregator': True
                                             },
                                 buffer_time=1)
        self.agent.register_feed('acu_health_check',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)
        self.agent.register_feed('acu_upload',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)
        self.agent.register_feed('acu_error',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)
        agent.register_task('go_to', self.go_to, blocking=False)
        agent.register_task('run_specified_scan',
                            self.run_specified_scan,
                            locking=False)
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
    # to assess conflicts should probably be in try_set_job.

    def try_set_job(self, job_name):
        """
        Set a job status to 'run'.

        Args:
            job_name (str): Name of the task/process you are trying to start.
        """
        with self.lock.acquire_timeout(timeout=1.0, job=job_name) as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquried because it is held"
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
    def health_check(self, session, params=None):
        pass

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

        report_t = time.time()
        report_period = 10
        n_ok = 0
        min_query_period = 0.05   # Seconds
        query_t = 0
        summary_params = ['Time',
                          'Azimuth mode',
                          'Azimuth current position',
                          'Azimuth current velocity',
                          'Elevation mode',
                          'Elevation current position',
                          'Elevation current velocity',
                          # 'Boresight mode',
                          # 'Boresight current position',
                          'Qty of free program track stack positions',
                          ]
        mode_key = {'Stop': 0,
                    'Preset': 1,
                    'ProgramTrack': 2,
                    'Stow': 3,
                    'SurvivalMode': 4,
                    }
        tfn_key = {'None': 0,
                   'False': 0,
                   'True': 1
                   }
        char_replace = [' ', '-', ':', '(', ')', '+', ',', '/']
        while self.jobs['monitor'] == 'run':
            now = time.time()

            if now > report_t + report_period:
                self.log.info('Responses ok at %.3f Hz'
                              % (n_ok / (now - report_t)))
                self.health_check['status'] = True
                report_t = now
                n_ok = 0

            if now - query_t < min_query_period:
                yield dsleep(now - query_t)

            query_t = now
            try:
                # j = yield self.acu.http.Values('DataSets.StatusSATPDetailed8100')
                j = yield self.acu.http.Values('DataSets.StatusCCATDetailed8100')
                n_ok += 1
                session.data = j
            except Exception as e:
                # Need more error handling here...
                errormsg = {'aculib_error_message': str(e)}
                self.log.error(errormsg)
                acu_error = {'timestamp': time.time(),
                             'block_name': 'ACU_error',
                             'data': errormsg
                             }
                self.agent.publish_to_feed('acu_error', acu_error)
                yield dsleep(1)

            for (key, value) in session.data.items():
                ocs_key = key
                for char in char_replace:
                    ocs_key = ocs_key.replace(char, '_')
                ocs_key = ocs_key.replace('24V', 'V24')
                if key in summary_params:
                    self.data['status']['summary'][ocs_key] = value
                    if key == 'Azimuth mode':
                        self.data['status']['summary']['Azimuth_mode_num'] =\
                            mode_key[value]
                    elif key == 'Elevation mode':
                        self.data['status']['summary']['Elevation_mode_num'] =\
                            mode_key[value]
                else:
                    self.data['status']['full_status'][ocs_key] = str(value)
            influx_status = {}
            for v in self.data['status']['full_status']:
                try:
                    influx_status[str(v) + '_influx'] =\
                        float(self.data['status']['full_status'][v])
                except ValueError:
                    influx_status[str(v) + '_influx'] =\
                        tfn_key[self.data['status']['full_status'][v]]
            self.data['status']['summary']['ctime'] =\
                timecode(self.data['status']['summary']['Time'])
            acustatus_summary = {'timestamp':
                                 self.data['status']['summary']['ctime'],
                                 'block_name': 'ACU_summary_output',
                                 'data': self.data['status']['summary']
                                 }
            acustatus_full = {'timestamp':
                              self.data['status']['summary']['ctime'],
                              'block_name': 'ACU_fullstatus_output',
                              'data': self.data['status']['full_status']
                              }
            acustatus_influx = {'timestamp':
                                self.data['status']['summary']['ctime'],
                                'block_name': 'ACU_fullstatus_ints',
                                'data': influx_status
                                }
            self.agent.publish_to_feed('acu_status_summary', acustatus_summary)
            self.agent.publish_to_feed('acu_status_full', acustatus_full)
            self.agent.publish_to_feed('acu_status_influx', acustatus_influx)
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
        FMT = '<iddddd'
        FMT_LEN = struct.calcsize(FMT)
        UDP_PORT = self.acu_config['PositionBroadcast_target'].split(':')[1]
        udp_data = []
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
                self.health_check['broadcast'] = True
                process_data = udp_data[:200]
                udp_data = udp_data[200:]
                year = datetime.datetime.now().year
                gyear = calendar.timegm(time.strptime(str(year), '%Y'))
                sample_rate = (len(process_data) /
                               ((process_data[-1][0]-process_data[0][0])*86400
                                + process_data[-1][1]-process_data[0][1]))
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
                pd0_azimuth_raw = pd0[4]
                pd0_elevation_corrected = pd0[3]
                pd0_elevation_raw = pd0[5]
                bcast_first = {'Time': pd0_data_ctime,
                               'Azimuth_Corrected': pd0_azimuth_corrected,
                               'Azimuth_Raw': pd0_azimuth_raw,
                               'Elevation_Corrected': pd0_elevation_corrected,
                               'Elevation_Raw': pd0_elevation_raw,
                               }
                acu_broadcast_influx = {'timestamp': bcast_first['Time'],
                                        'block_name': 'ACU_position',
                                        'data': bcast_first,
                                        }
                self.agent.publish_to_feed('acu_broadcast_influx', acu_broadcast_influx)
                for d in process_data:
                    gday = (d[0]-1) * 86400
                    sec = d[1]
                    data_ctime = gyear + gday + sec
                    azimuth_corrected = d[2]
                    azimuth_raw = d[4]
                    elevation_corrected = d[3]
                    elevation_raw = d[5]
                    self.data['broadcast'] = {'Time': data_ctime,
                                              'Azimuth_Corrected': azimuth_corrected,
                                              'Azimuth_Raw': azimuth_raw,
                                              'Elevation_Corrected': elevation_corrected,
                                              'Elevation_Raw': elevation_raw,
                                              }
                    acu_udp_stream = {'timestamp': self.data['broadcast']['Time'],
                                      'block_name': 'ACU_position',
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
        current_az = round(self.data['broadcast']['Azimuth_Corrected'], 4)
        current_el = round(self.data['broadcast']['Elevation_Corrected'], 4)
        publish_dict = {'Start_Azimuth': current_az,
                        'Start_Elevation': current_el,
                        'Start_Boresight': 0,
                        'Upload_Type': 1,
                        'Preset_Azimuth': az,
                        'Preset_Elevation': el,
                        'Upload_Lines': []}
        acu_upload = {'timestamp': self.data['broadcast']['Time'],
                      'block_name': 'ACU_upload',
                      'data': publish_dict
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
        yield self.acu.go_3rd_axis(bs_destination)
        current_position = self.data['status']['summary']\
            ['Boresight_current_position']
        while current_position != bs_destination:
            yield dsleep(1)
            current_position = self.data['status']['summary']\
                ['Boresight_current_position']
        yield self.acu.stop()
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
    def run_specified_scan(self, session, params=None):
        """TASK run_specifid_scan

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
        scantype = params.get('scantype')
        if scantype == 'from_file':
            filename = params.get('filename')
            times, azs, els, vas, ves, azflags, elflags =\
                sh.from_file(filename)
        elif scantype == 'linear_1dir':
            azpts = params.get('azpts')
            el = params.get('el')
            azvel = params.get('azvel')
            total_time = (azpts[1]-azpts[0])/azvel
            azs = np.linspace(azpts[0], azpts[1], total_time*10)
            els = np.linspace(el, el, total_time*10)
            times = np.linspace(0.0, total_time, total_time*10)
        elif scantype == 'linear_turnaround_sameends':
            # from parameters, generate the full set of scan points
            self.log.info('scantype is' + str(scantype))
            azpts = params.get('azpts')
            el = params.get('el')
            azvel = params.get('azvel')
            acc = params.get('acc')
            ntimes = params.get('ntimes')
            times, azs, els, vas, ves, azflags, elflags =\
                sh.linear_turnaround_scanpoints(azpts, el, azvel, acc, ntimes)

        # Switch to Stop mode and clear the stack
        yield self.acu.stop()
        self.log.info('Stop called')
        yield dsleep(5)
        yield self.acu.http.Command('DataSets.CmdTimePositionTransfer',
                                    'Clear Stack')
        yield dsleep(0.1)
        self.log.info('Cleared stack.')

        # Move to the starting position for the scan and then switch to Stop
        # mode
        start_az = azs[0]
        start_el = els[0]

        upload_publish_dict = {'Start_Azimuth': start_az,
                               'Start_Elevation': start_el,
                               'Start_Boresight': 0,
                               'Upload_Type': 2,
                               'Preset_Azimuth': 0,
                               'Preset_Elevation': 0,
                               'Upload_Lines': []}

        # Follow the scan in ProgramTrack mode, then switch to Stop mode
        if scantype == 'linear_turnaround_sameends':
            all_lines = sh.write_lines(times, azs, els, vas, ves, azflags,
                                       elflags)
        elif scantype == 'from_file':
            all_lines = sh.write_lines(times, azs, els, vas, ves, azflags,
                                       elflags)
        # Other scan types not yet implemented, so break
        else:
            return False, 'Not enough information to scan'
        self.log.info('all_lines generated')
        yield self.acu.mode('ProgramTrack')
        self.log.info('mode is now ProgramTrack')
        group_size = 120
        while len(all_lines):
            upload_lines = all_lines[:group_size]
            text = ''.join(upload_lines)
            all_lines = all_lines[group_size:]
            free_positions = self.data['status']['summary']\
                ['Qty_of_free_program_track_stack_positions']
            while free_positions < 9899:
                free_positions = self.data['status']['summary']\
                    ['Qty_of_free_program_track_stack_positions']
                yield dsleep(0.1)
            yield self.acu.http.UploadPtStack(text)
            upload_publish_dict['Upload_Lines'] = upload_lines
            acu_upload = {'timestamp': self.data['broadcast']['Time'],
                          'block_name': 'ACU_upload',
                          'data': upload_publish_dict
                          }
            self.agent.publish_to_feed('acu_upload', acu_upload)
            self.log.info('Uploaded a group')
        self.log.info('No more lines to upload')
        current_az = round(self.data['broadcast']['Azimuth_Corrected'], 4)
        current_el = round(self.data['broadcast']['Elevation_Corrected'], 4)
        while current_az != azs[-1] or current_el != els[-1]:
            yield dsleep(0.1)
            modes = (self.data['status']['summary']['Azimuth_mode'],
                     self.data['status']['summary']['Elevation_mode'])
            if modes != ('ProgramTrack', 'ProgramTrack'):
                return False, 'Fault triggered (not ProgramTrack)!'
            current_az = round(self.data['broadcast']['Azimuth_Corrected'], 4)
            current_el = round(self.data['broadcast']['Elevation_Corrected'],
                               4)
        yield dsleep(self.sleeptime)
        yield self.acu.stop()
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
                    ['Qty_of_free_program_track_stack_positions']
                while free_positions < 5099:
                    yield dsleep(0.1)
                    free_positions = self.data['status']['summary']\
                        ['Qty_of_free_program_track_stack_positions']
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
