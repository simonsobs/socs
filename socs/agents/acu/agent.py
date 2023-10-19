import argparse
import random
import struct
import time
from enum import Enum

import numpy as np
import soaculib as aculib
import soaculib.status_keys as status_keys
import twisted.web.client as tclient
import yaml
from autobahn.twisted.util import sleep as dsleep
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from soaculib.twisted_backend import TwistedHttpBackend
from twisted.internet import protocol, reactor
from twisted.internet.defer import DeferredList, inlineCallbacks

from socs.agents.acu import drivers as sh
from socs.agents.acu import exercisor

#: The number of free ProgramTrack positions, when stack is empty.
FULL_STACK = 10000


#: Maximum update time (in s) for "monitor" process data, even with no changes
MONITOR_MAX_TIME_DELTA = 2.

#: Default scan params by platform type
DEFAULT_SCAN_PARAMS = {
    'ccat': {
        'az_speed': 2,
        'az_accel': 1,
    },
    'satp': {
        'az_speed': 1,
        'az_accel': 1,
    },
}


class ACUAgent:
    """Agent to acquire data from an ACU and control telescope pointing with the
    ACU.

    Parameters:
        acu_config (str):
            The configuration for the ACU, as referenced in aculib.configs.
            Default value is 'guess'.
        exercise_plan (str):
            The full path to a scan config file describing motions to cycle
            through on the ACU.  If this is None, the associated process and
            feed will not be registered.
        startup (bool):
            If True, immediately start the main monitoring processes
            for status and UDP data.
        ignore_axes (str or list of str):
            List of axes to "ignore". "ignore" means that the axis
            will not be commanded.  If a user requests an action that
            would otherwise move the axis, it is not moved but the
            action is assumed to have succeeded.  The values in this
            list should be drawn from "az", "el", and "third".  A single
            comma-delimited string (e.g. "az,el" is also accepted.
        disable_idle_reset (bool):
            If True, don't auto-start idle_reset process for LAT.

    """

    def __init__(self, agent, acu_config='guess', exercise_plan=None,
                 startup=False, ignore_axes=None, disable_idle_reset=False):
        # Separate locks for exclusive access to az/el, and boresight motions.
        self.azel_lock = TimeoutLock()
        self.boresight_lock = TimeoutLock()

        self.acu_config_name = acu_config
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

        # This initializes self.scan_params; these become the default
        # scan params when calling generate_scan.  They can be changed
        # during run time; they can also be overridden when calling
        # generate_scan.
        self.scan_params = {}
        self._set_default_scan_params()

        startup_idle_reset = (self.acu_config['platform'] in ['lat', 'ccat']
                              and not disable_idle_reset)

        if isinstance(ignore_axes, str):
            ignore_axes = [x.strip() for x in ignore_axes.split(',')]
        if ignore_axes is None:
            ignore_axes = []
        assert all([x in ['az', 'el', 'third'] for x in ignore_axes])
        self.ignore_axes = ignore_axes
        if len(self.ignore_axes):
            agent.log.warn('User requested ignore_axes={i}', i=self.ignore_axes)

        self.exercise_plan = exercise_plan

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
                                'corotator': {},
                                },
                     'broadcast': {},
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
                               startup=startup)
        agent.register_process('broadcast',
                               self.broadcast,
                               self._simple_process_stop,
                               blocking=False,
                               startup=startup)
        agent.register_process('generate_scan',
                               self.generate_scan,
                               self._simple_process_stop,
                               blocking=False,
                               startup=False)
        agent.register_process('idle_reset',
                               self.idle_reset,
                               self._simple_process_stop,
                               blocking=False,
                               startup=startup_idle_reset)
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
        self.agent.register_feed('acu_error',
                                 record=True,
                                 agg_params=basic_agg_params,
                                 buffer_time=1)
        agent.register_task('go_to',
                            self.go_to,
                            blocking=False,
                            aborter=self._simple_task_abort)
        agent.register_task('set_scan_params',
                            self.set_scan_params,
                            blocking=False)
        agent.register_task('fromfile_scan',
                            self.fromfile_scan,
                            blocking=False,
                            aborter=self._simple_task_abort)
        agent.register_task('set_boresight',
                            self.set_boresight,
                            blocking=False,
                            aborter=self._simple_task_abort)
        agent.register_task('stop_and_clear',
                            self.stop_and_clear,
                            blocking=False)
        agent.register_task('clear_faults',
                            self.clear_faults,
                            blocking=False)

        # Automatic exercise program...
        if exercise_plan:
            agent.register_process(
                'exercise', self.exercise, self._simple_process_stop,
                stopper_blocking=False)
            # Use longer default frame length ... very low volume feed.
            self.agent.register_feed('activity',
                                     record=True,
                                     buffer_time=0,
                                     agg_params={
                                         'frame_length': 600,
                                     })

    @inlineCallbacks
    def _simple_task_abort(self, session, params):
        # Trigger a task abort by updating state to "stopping"
        yield session.set_status('stopping')

    @inlineCallbacks
    def _simple_process_stop(self, session, params):
        # Trigger a process stop by updating state to "stopping"
        yield session.set_status('stopping')

    @ocs_agent.param('_')
    @inlineCallbacks
    def idle_reset(self, session, params):
        """idle_reset()

        **Process** - To prevent LAT from going into Survival mode,
        do something on the command interface every so often.  (The
        default inactivity timeout is 1 minute.)

        """
        IDLE_RESET_TIMEOUT = 60  # The watchdog timeout in ACU

        session.set_status('running')
        next_action = 0

        while session.status in ['starting', 'running']:
            if time.time() < next_action:
                yield dsleep(IDLE_RESET_TIMEOUT / 10)
                continue
            success = True
            try:
                yield self.acu_control.http.Values(self.acu8100)
            except Exception as e:
                self.log.info(' -- failed to reset Idle Stow time: {err}', err=e)
                success = False
            session.data.update({
                'timestamp': time.time(),
                'reset_ok': success})
            if not success:
                next_action = time.time() + 4
            else:
                next_action = time.time() + IDLE_RESET_TIMEOUT / 2

        return True, 'Process "idle_reset" exited cleanly.'

    @inlineCallbacks
    def monitor(self, session, params):
        """monitor()

        **Process** - Refresh the cache of SATP ACU status information and
        report it on the 'acu_status' and 'acu_status_influx' HK feeds.

        Summary parameters are ACU-provided time code, Azimuth mode,
        Azimuth position, Azimuth velocity, Elevation mode, Elevation position,
        Elevation velocity, Boresight mode, and Boresight position.

        The session.data of this process is a nested dictionary.
        Here's an example::

          {
            "StatusDetailed": {
              "Time": 81.661170959322,
              "Year": 2023,
              "Azimuth mode": "Stop",
              "Azimuth commanded position": -20.0012,
              "Azimuth current position": -20.0012,
              "Azimuth current velocity": 0.0002,
              "Azimuth average position error": 0,
              "Azimuth peak position error": 0,
              "Azimuth computer disabled": false,
              ...
            },
            "Status3rdAxis": {
              "3rd axis Mode": "Stop",
              "3rd axis commanded position": 77,
              "3rd axis current position": 77,
              "3rd axis computer disabled": "No Fault",
              ...
            },
            "StatusResponseRate": 19.237531827325963,
            "PlatformType": "satp",
            "DefaultScanParams": {
              "az_speed": 2.0,
              "az_accel": 1.0,
            },
            "connected": True,
          }

        In the case of an SATP, the Status3rdAxis is not populated
        (the Boresight info can be found in StatusDetailed).  In the
        case of the LAT, the corotator info is queried separately and
        stored under Status3rdAxis.

        """

        session.set_status('running')

        # Note that session.data will get scanned, to assign data to
        # feed blocks.  We make an explicit list of items to ignore
        # during that scan (not_data_keys).
        session.data = {'PlatformType': self.acu_config['platform'],
                        'DefaultScanParams': self.scan_params,
                        'StatusResponseRate': 0.,
                        'IgnoredAxes': self.ignore_axes,
                        'connected': False}
        not_data_keys = list(session.data.keys())

        last_complaint = 0
        while True:
            try:
                version = yield self.acu_read.http.Version()
                break
            except Exception as e:
                if time.time() - last_complaint > 3600:
                    errormsg = {'aculib_error_message': str(e)}
                    self.log.error(str(e))
                    self.log.error('monitor process failed to query version! Will keep trying.')
                    last_complaint = time.time()
                yield dsleep(10)

        self.log.info(version)
        session.data['connected'] = True

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
            # Are these needed for the SAT still?
            'Any Moving': 0,
            'All Inserted': 1,
            'All Retracted': 2,
            'Failure': 3,
        }
        lat_pin_key = {
            # From "meta" output.
            'Moving': 0,
            'Inserted': 1,
            'Retracted': 2,
            'Error': 3,
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
                          'Corotator_mode': None,
                          }

        j = yield self.acu_read.http.Values(self.acu8100)
        if self.acu3rdaxis:
            j2 = yield self.acu_read.http.Values(self.acu3rdaxis)
        else:
            j2 = {}
        session.data.update({'StatusDetailed': j,
                             'Status3rdAxis': j2,
                             'StatusResponseRate': n_ok / (query_t - report_t)})

        was_remote = False
        last_resp_rate = None
        data_blocks = {}
        influx_blocks = {}

        while session.status in ['running']:

            now = time.time()
            if now - query_t < min_query_period:
                yield dsleep(min_query_period - (now - query_t))

            query_t = time.time()
            if query_t > report_t + report_period:
                resp_rate = n_ok / (query_t - report_t)
                if last_resp_rate is None or (abs(resp_rate - last_resp_rate)
                                              > max(0.1, last_resp_rate * .01)):
                    self.log.info('Data rate for "monitor" stream is now %.3f Hz' % (resp_rate))
                    last_resp_rate = resp_rate
                report_t = query_t
                n_ok = 0
                session.data.update({'StatusResponseRate': resp_rate})

            try:
                j = yield self.acu_read.http.Values(self.acu8100)
                if self.acu3rdaxis:
                    j2 = yield self.acu_read.http.Values(self.acu3rdaxis)
                else:
                    j2 = {}
                session.data.update({'StatusDetailed': j, 'Status3rdAxis': j2,
                                     'connected': True})
                n_ok += 1
                last_complaint = 0
            except Exception as e:
                if now - last_complaint > 3600:
                    errormsg = {'aculib_error_message': str(e)}
                    self.log.error(str(e))
                    acu_error = {'timestamp': time.time(),
                                 'block_name': 'ACU_error',
                                 'data': errormsg
                                 }
                    self.agent.publish_to_feed('acu_error', acu_error)
                    last_complaint = time.time()
                    session.data['connected'] = False
                yield dsleep(1)
                continue
            for k, v in session.data.items():
                if k in not_data_keys:
                    continue
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
                sh.timecode(self.data['status']['summary']['Time'])
            if self.data['status']['platform_status']['Remote_mode'] == 0:
                if was_remote:
                    was_remote = False
                    self.log.warn('ACU in local mode!')
            elif not was_remote:
                was_remote = True
                self.log.warn('ACU now in remote mode.')
            if self.data['status']['summary']['ctime'] == prev_checkdata['ctime']:
                self.log.warn('ACU time has not changed from previous data point!')

            # Alert on any axis mode change.
            for axis_mode in prev_checkdata.keys():
                if 'mode' not in axis_mode:
                    continue
                v = self.data['status']['summary'].get(axis_mode)
                if v is None:
                    v = self.data['status']['corotator'].get(axis_mode)
                if v != prev_checkdata[axis_mode]:
                    self.log.info('{axis_mode} is now "{v}"',
                                  axis_mode=axis_mode, v=v)
                    prev_checkdata[axis_mode] = v

            # influx_blocks are constructed based on refers to all
            # other self.data['status'] keys. Do not add more keys to
            # any self.data['status'] categories beyond this point
            new_influx_blocks = {}
            for category in self.data['status']:
                new_influx_blocks[category] = {
                    'timestamp': self.data['status']['summary']['ctime'],
                    'block_name': category,
                    'data': {}}

                if category != 'commands':
                    for statkey, statval in self.data['status'][category].items():
                        if isinstance(statval, float):
                            influx_val = statval
                        elif isinstance(statval, str):
                            for key_map in [tfn_key, mode_key, fault_key, pin_key,
                                            lat_pin_key]:
                                if statval in key_map:
                                    influx_val = key_map[statval]
                                    break
                            else:
                                raise ValueError('Could not convert value for %s="%s"' %
                                                 (statkey, statval))
                        elif isinstance(statval, int):
                            if statkey in ['Year', 'Free_upload_positions']:
                                influx_val = float(statval)
                            else:
                                influx_val = int(statval)
                        new_influx_blocks[category]['data'][statkey + '_influx'] = influx_val
                else:  # i.e. category == 'commands':
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

            # Only keep blocks that have changed or have new data.
            block_keys = list(new_influx_blocks.keys())
            for k in block_keys:
                if k not in influx_blocks:
                    continue
                B, N = influx_blocks[k], new_influx_blocks[k]
                if N['timestamp'] - B['timestamp'] > MONITOR_MAX_TIME_DELTA:
                    continue
                if any([B['data'][_k] != _v for _k, _v in N['data'].items()]):
                    continue
                del new_influx_blocks[k]

            for block in new_influx_blocks.values():
                self.agent.publish_to_feed('acu_status_influx', block)
            influx_blocks.update(new_influx_blocks)

            # Assemble data for aggregator ...
            new_blocks = {}
            for block_name, data_key in [
                    ('ACU_summary_output', 'summary'),
                    ('ACU_axis_faults', 'axis_faults_errors_overages'),
                    ('ACU_position_errors', 'position_errors'),
                    ('ACU_axis_limits', 'axis_limits'),
                    ('ACU_axis_warnings', 'axis_warnings'),
                    ('ACU_axis_failures', 'axis_failures'),
                    ('ACU_axis_state', 'axis_state'),
                    ('ACU_oscillation_alarm', 'osc_alarms'),
                    ('ACU_command_status', 'commands'),
                    ('ACU_general_errors', 'ACU_failures_errors'),
                    ('ACU_platform_status', 'platform_status'),
                    ('ACU_emergency', 'ACU_emergency'),
                    ('ACU_corotator', 'corotator'),
            ]:
                new_blocks[block_name] = {
                    'timestamp': self.data['status']['summary']['ctime'],
                    'block_name': block_name,
                    'data': self.data['status'][data_key],
                }

            # Only keep blocks that have changed or have new data.
            block_keys = list(new_blocks.keys())
            for k in block_keys:
                if k == 'summary':  # always store these, as a sort of reference tick.
                    continue
                if k not in data_blocks:
                    continue
                B, N = data_blocks[k], new_blocks[k]
                if N['timestamp'] - B['timestamp'] > MONITOR_MAX_TIME_DELTA:
                    continue
                if any([B['data'][_k] != _v for _k, _v in N['data'].items()]):
                    continue
                del new_blocks[k]

            for block in new_blocks.values():
                self.agent.publish_to_feed('acu_status', block)

            data_blocks.update(new_blocks)

        return True, 'Acquisition exited cleanly.'

    @ocs_agent.param('auto_enable', type=bool, default=True)
    @inlineCallbacks
    def broadcast(self, session, params):
        """broadcast(auto_enable=True)

        **Process** - Read UDP data from the port specified by
        self.acu_config, decode it, and publish to HK feeds.  Full
        resolution (200 Hz) data are written to feed "acu_udp_stream"
        while 1 Hz decimated are written to "acu_broadcast_influx".
        The 1 Hz decimated output are also stored in session.data.

        Args:
          auto_enable (bool): If True, the Process will try to
            configure and (re-)enable the UDP stream if at any point
            the stream seems to drop out.

        Notes:
          The session.data looks like this (this is for a SATP running
          with servo details in the UDP output)::

            {
              "Time": 1679499948.8234625,
              "Corrected_Azimuth": -20.00112176010607,
              "Corrected_Elevation": 50.011521050839434,
              "Corrected_Boresight": 29.998428712246067,
              "Raw_Azimuth": -20.00112176010607,
              "Raw_Elevation": 50.011521050839434,
              "Raw_Boresight": 29.998428712246067,
              "Azimuth_Current_1": -0.000384521484375,
              "Azimuth_Current_2": -0.0008331298828125,
              "Elevation_Current_1": 0.003397979736328125,
              "Boresight_Current_1": -0.000483856201171875,
              "Boresight_Current_2": -0.000105743408203125,
              "Azimuth_Vel_1": -0.000002288818359375,
              "Azimuth_Vel_2": 0,
              "Az_Vel_Act": -0.0000011444091796875,
              "Az_Vel_Des": 0,
              "Az_Vffw": 0,
              "Az_Pos_Des": -20.00112176010607,
              "Az_Pos_Err": 0
            }

        """
        session.set_status('running')
        FMT = self.udp_schema['format']
        FMT_LEN = struct.calcsize(FMT)
        UDP_PORT = self.udp['port']
        udp_data = []
        fields = self.udp_schema['fields']
        session.data = {}

        # BroadcastStreamControl instance.
        stream = self.acu_control.streams['main']

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
                for d in process_data:
                    data_ctime = sh.timecode(d[0] + d[1] / sh.DAY)
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
                # Consider logging an outage, attempting reconfig.
                if active and now - last_packet_time > 3:
                    self.log.info('No UDP packets are being received.')
                    active = False
                    next_reconfig = time.time()
                if not active and params['auto_enable'] and next_reconfig <= time.time():
                    self.log.info('Requesting UDP stream enable.')
                    try:
                        cfg, raw = yield stream.safe_enable()
                    except Exception as err:
                        self.log.info('Exception while trying to enable stream: {err}', err=err)
                    next_reconfig += 60
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
        if not bcast_check:
            return False, 'Motion blocked; problem with "broadcast" data acq process.'

        monitor_check = yield self._check_daq_streams('monitor')
        if not monitor_check:
            return False, 'Motion blocked; problem with "monitor" data acq process.'

        if self.data['status']['platform_status']['Remote_mode'] == 0:
            self.log.warn('ACU in local mode, cannot perform motion with OCS.')
            return False, 'ACU not in remote mode.'

        return True, 'Agent state ok for motion.'

    @inlineCallbacks
    def _set_modes(self, az=None, el=None, third=None):
        """Helper for changing individual axis modes.  Respects ignore_axes.

        When setting one axis it is often necessary to write others as
        well.  The current mode is first queried, and written back
        unmodified.

        """
        modes = list((yield self.acu_control.mode(size=3)))
        changes = [False, False, False]
        for i, (k, v) in enumerate([('az', az), ('el', el), ('third', third)]):
            if k not in self.ignore_axes and v is not None:
                changes[i] = True
                modes[i] = v
        if not any(changes):
            return
        if not changes[2]:
            yield self.acu_control.mode(modes[:2])
        else:
            yield self.acu_control.mode(modes)

    @inlineCallbacks
    def _stop(self, all_axes=False):
        """Helper for putting all axes in Stop.  This will normally just issue
        acu_control.stop(); but if any axes are being "ignored", and
        the user has not passed all_axes=True, then it will avoid
        changing the mode of those axes.

        """
        if all_axes or len(self.ignore_axes) == 0:
            yield self.acu_control.stop()
            return
        yield self._set_modes('Stop', 'Stop', 'Stop')

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

        # If this axis is "ignore", skip it.
        for _axis, short_name in [
                ('Azimuth', 'az'),
                ('Elevation', 'el'),
                ('Boresight', 'third'),
        ]:
            if _axis == axis and short_name in self.ignore_axes:
                self.log.warn('Ignoring requested motion on {axis}', axis=axis)
                yield dsleep(1)
                return True, 'axis successfully ignored'

        # Specialization for different axis types.

        class AxisControl:
            def get_pos(_self):
                return self.data['status']['summary'][f'{axis}_current_position']

            def get_mode(_self):
                return self.data['status']['summary'][f'{axis}_mode']

            def get_vel(_self):
                return self.data['status']['summary'][f'{axis}_current_velocity']

        class AzAxis(AxisControl):
            @inlineCallbacks
            def goto(_self, target):
                result = yield self.acu_control.go_to(az=target)
                return result

        class ElAxis(AxisControl):
            @inlineCallbacks
            def goto(_self, target):
                result = yield self.acu_control.go_to(el=target)
                return result

        class ThirdAxis(AxisControl):
            def get_vel(_self):
                return 0.

            @inlineCallbacks
            def goto(_self, target):
                result = yield self.acu_control.go_3rd_axis(target)
                return result

        class LatCorotator(ThirdAxis):
            def get_pos(_self):
                return self.data['status']['corotator']['Corotator_current_position']

            def get_mode(_self):
                return self.data['status']['corotator']['Corotator_mode']

        ctrl = None
        if axis == 'Azimuth':
            ctrl = AzAxis()
        elif axis == 'Elevation':
            ctrl = ElAxis()
        elif axis == 'Boresight':
            if self.acu_config['platform'] in ['ccat', 'lat']:
                ctrl = LatCorotator()
            else:
                ctrl = ThirdAxis()
        if ctrl is None:
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
            current_pos, current_vel = ctrl.get_pos(), ctrl.get_vel()
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
            mode_ok = (ctrl.get_mode() == 'Preset')

            # Log only on state changes
            if state != last_state:
                _state = f'{axis}.state={state.name}'
                self.log.info(
                    f'{_state:<30} dt={now-start_time:7.3f} dist={distance:8.3f}')
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
                result = yield ctrl.goto(target)
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

    @inlineCallbacks
    def _go_to_axes(self, session, el=None, az=None, third=None):
        """Execute a movement along multiple axes, using "Preset"
        mode.  This just launches _go_to_axis on each required axis,
        and collects the results.

        Args:
          session: session object variable of the parent operation.
          az (float): target for Azimuth axis (ignored if None).
          el (float): target for Elevation axis (ignored if None).
          third (float): target for Boresight axis (ignored if None).

        Returns:
          ok (bool): True if all motions completed successfully and
            arrived at target position.
          msg (str): success/error message (combined from each target
            axis).

        """
        move_defs = []
        for axis_name, short_name, target in [
                ('Azimuth', 'az', az),
                ('Elevation', 'el', el),
                ('Boresight', 'third', third),
        ]:
            if target is not None:
                move_defs.append(
                    (short_name, self._go_to_axis(session, axis_name, target)))
        if len(move_defs) is None:
            return True, 'No motion requested.'

        moves = yield DeferredList([d for n, d in move_defs])
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
            msg = ' '.join([f'{n}: {msg}' for (n, d), msg in zip(move_defs, msgs)])
        return all_ok, msg

    @ocs_agent.param('az', type=float)
    @ocs_agent.param('el', type=float)
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

            self.log.info('Clearing faults to prepare for motion.')
            yield self.acu_control.clear_faults()
            yield dsleep(1)

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

            all_ok, msg = yield self._go_to_axes(session, az=target_az, el=target_el)
            if all_ok and params['end_stop']:
                yield self._set_modes(az='Stop', el='Stop')

        return all_ok, msg

    @ocs_agent.param('target', type=float)
    @ocs_agent.param('end_stop', default=False, type=bool)
    @inlineCallbacks
    def set_boresight(self, session, params):
        """set_boresight(target=None, end_stop=False)

        **Task** - Move the telescope to a particular third-axis angle.

        Parameters:
            target (float): destination angle for boresight rotation
            end_stop (bool): put axes in Stop mode after motion

        """
        with self.boresight_lock.acquire_timeout(0, job='set_boresight') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.boresight_lock.job} is running."

            self.log.info('Clearing faults to prepare for motion.')
            yield self.acu_control.clear_faults()
            yield dsleep(1)

            ok, msg = yield self._check_ready_motion(session)
            if not ok:
                return False, msg

            target = params['target']

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
                yield self._set_modes(third='Stop')

        return ok, msg

    def _set_default_scan_params(self):
        # A reference to scan_params is cached in monitor, so copy
        # individual items rather than creating a new dict here.
        for k, v in DEFAULT_SCAN_PARAMS[self.acu_config['platform']].items():
            self.scan_params[k] = v

    @ocs_agent.param('az_speed', type=float, default=None)
    @ocs_agent.param('az_accel', type=float, default=None)
    @ocs_agent.param('reset', default=False, type=bool)
    @inlineCallbacks
    def set_scan_params(self, session, params):
        """set_scan_params(az_speed=None, az_accel=None, reset=False))

        **Task** - Update the default scan parameters, used by
        generate_scan if not passed explicitly.

        Parameters:
          az_speed (float, optional): The azimuth scan speed.
          az_accel (float, optional): The (average) azimuth
            acceleration at turn-around.
          reset (bool, optional): If True, reset all params to default
            values before applying any updates passed explicitly here.

        """
        if params['reset']:
            self._set_default_scan_params()
        for k in ['az_speed', 'az_accel']:
            if params[k] is not None:
                self.scan_params[k] = params[k]
        self.log.info('Updated default scan params to {sp}', sp=self.scan_params)
        yield
        return True, 'Done'

    @inlineCallbacks
    def clear_faults(self, session, params):
        """clear_faults()

        **Task** - Clear any axis faults.

        """

        session.set_status('running')
        yield self.acu_control.clear_faults()
        session.set_status('stopping')
        return True, 'Job completed.'

    @ocs_agent.param('all_axes', default=False, type=bool)
    @inlineCallbacks
    def stop_and_clear(self, session, params):
        """stop_and_clear(all_axes=False)

        **Task** - Change the azimuth, elevation, and 3rd axis modes
        to Stop; also clear the ProgramTrack stack.

        Args:
          all_axes (bool): Send Stop to all axes, even ones user has
            requested to be ignored.

        """
        def _read_modes():
            modes = [self.data['status']['summary']['Azimuth_mode'],
                     self.data['status']['summary']['Elevation_mode']]
            if self.acu_config['platform'] == 'satp':
                modes.append(self.data['status']['summary']['Boresight_mode'])
            elif self.acu_config['platform'] in ['ccat', 'lat']:
                modes.append(self.data['status']['corotator']['Corotator_mode'])
            return modes

        session.set_status('running')
        for i in range(6):
            for short_name, mode in zip(['az', 'el', 'third'],
                                        _read_modes()):
                if (params['all_axes'] or short_name not in self.ignore_axes) and mode != 'Stop':
                    break
            else:
                self.log.info('All axes in Stop mode')
                break
            yield self._stop(params['all_axes'])
            self.log.info('Stop called (iteration %i)' % (i + 1))
            yield dsleep(0.1)

        else:
            msg = 'Failed to set all axes to Stop mode!'
            self.log.error(msg)
            return False, msg

        for i in range(6):
            free_stack = self.data['status']['summary']['Free_upload_positions']
            if free_stack < FULL_STACK:
                yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                                    'Clear Stack')
                self.log.info('Clear Stack called (iteration %i)' % (i + 1))
                yield dsleep(0.1)
            else:
                self.log.info('Stack cleared')
                break
        else:
            msg = 'Failed to clear the ProgramTrack stack!'
            self.log.warn(msg)
            return False, msg

        session.set_status('stopping')
        return True, 'Job completed'

    @ocs_agent.param('filename', type=str)
    @ocs_agent.param('adjust_times', type=bool, default=True)
    @ocs_agent.param('azonly', type=bool, default=True)
    @inlineCallbacks
    def fromfile_scan(self, session, params=None):
        """fromfile_scan(filename=None, adjust_times=True, azonly=True)

        **Task** - Upload and execute a scan pattern from numpy file.

        Parameters:
            filename (str): full path to desired numpy file. File should
                contain an array of shape (5, nsamp) or (7, nsamp).  See Note.
            adjust_times (bool): If True (the default), the track
                timestamps are interpreted as relative times, only,
                and the track will be formatted so the first point
                happens a few seconds in the future.  If False, the
                track times will be taken at face value (even if the
                first one is, like, 0).
            azonly (bool): If True, the elevation part of the track
                will be uploaded but the el axis won't be put in
                ProgramTrack mode.  It might be put in Stop mode
                though.

        Notes:
            The columns in the numpy array are:

            - 0: timestamps, in seconds.
            - 1: azimuth, in degrees.
            - 2: elevation, in degrees.
            - 3: az_vel, in deg/s.
            - 4: el_vel, in deg/s.
            - 5: az_flags (2 if last point in a leg; 1 otherwise.)
            - 6: el_flags (2 if last point in a leg; 1 otherwise.)

            It is acceptable to omit columns 5 and 6.
        """
        session.set_status('running')

        times, azs, els, vas, ves, azflags, elflags = sh.from_file(params['filename'])
        if min(azs) <= self.motion_limits['azimuth']['lower'] \
           or max(azs) >= self.motion_limits['azimuth']['upper']:
            return False, 'Azimuth location out of range!'
        if min(els) <= self.motion_limits['elevation']['lower'] \
           or max(els) >= self.motion_limits['elevation']['upper']:
            return False, 'Elevation location out of range!'

        # Modify times?
        if params['adjust_times']:
            times = times + time.time() - times[0] + 5.

        # Turn those lines into a generator.
        all_lines = sh.ptstack_format(times, azs, els, vas, ves, azflags, elflags,
                                      absolute=True)

        def line_batcher(lines, n=10):
            while len(lines):
                some, lines = lines[:n], lines[n:]
                yield some

        point_gen = line_batcher(all_lines)
        step_time = np.median(np.diff(times))

        ok, err = yield self._run_track(session, point_gen, step_time,
                                        azonly=params['azonly'])
        return ok, err

    @ocs_agent.param('az_endpoint1', type=float)
    @ocs_agent.param('az_endpoint2', type=float)
    @ocs_agent.param('az_speed', type=float, default=None)
    @ocs_agent.param('az_accel', type=float, default=None)
    @ocs_agent.param('el_endpoint1', type=float, default=None)
    @ocs_agent.param('el_endpoint2', type=float, default=None)
    @ocs_agent.param('el_speed', type=float, default=0.)
    @ocs_agent.param('num_scans', type=float, default=None)
    @ocs_agent.param('start_time', type=float, default=None)
    @ocs_agent.param('wait_to_start', type=float, default=None)
    @ocs_agent.param('step_time', type=float, default=None)
    @ocs_agent.param('az_start', default='end',
                     choices=['end', 'mid', 'az_endpoint1', 'az_endpoint2',
                              'mid_inc', 'mid_dec'])
    @ocs_agent.param('az_drift', type=float, default=None)
    @ocs_agent.param('az_only', type=bool, default=True)
    @ocs_agent.param('scan_upload_length', type=float, default=None)
    @inlineCallbacks
    def generate_scan(self, session, params):
        """generate_scan(az_endpoint1, az_endpoint2, \
                         az_speed=None, az_accel=None, \
                         el_endpoint1=None, el_endpoint2=None, \
                         el_speed=None, \
                         num_scans=None, start_time=None, \
                         wait_to_start=None, step_time=None, \
                         az_start='end', az_drift=None, az_only=True, \
                         scan_upload_length=None)

        **Process** - Scan generator, currently only works for
        constant-velocity az scans with fixed elevation.

        Parameters:
            az_endpoint1 (float): first endpoint of a linear azimuth scan
            az_endpoint2 (float): second endpoint of a linear azimuth scan
            az_speed (float): azimuth speed for constant-velocity scan
            az_accel (float): turnaround acceleration for a constant-velocity scan
            el_endpoint1 (float): first endpoint of elevation motion.
                In the present implementation, this will be the
                constant elevation declared at every point in the
                track.
            el_endpoint2 (float): this is ignored.
            el_speed (float): this is ignored.
            num_scans (int or None): if not None, limits the scan to
                the specified number of constant velocity legs. The
                process will exit without error once that has
                completed.
            start_time (float or None): a unix timestamp giving the
                time at which the scan should begin.  The default is
                None, which means the scan will start immediately (but
                taking into account the value of wait_to_start).
            wait_to_start (float): number of seconds to wait before
                starting a scan, in the case that start_time is None.
                The default is to compute a minimum time based on the
                scan parameters and the ACU ramp-up algorithm; this is
                typically 5-10 seconds.
            step_time (float): time, in seconds, between points on the
                constant-velocity parts of the motion.  The default is
                None, which will cause an appropriate value to be
                chosen automatically (typically 0.1 to 1.0).
            az_start (str): part of the scan to start at.  To start at one
                of the extremes, use 'az_endpoint1', 'az_endpoint2', or
                'end' (same as 'az_endpoint1').  To start in the midpoint
                of the scan use 'mid_inc' (for first half-leg to have
                positive az velocity), 'mid_dec' (negative az velocity),
                or 'mid' (velocity oriented towards endpoint2).
            az_drift (float): if set, this should be a drift velocity
              in deg/s.  The scan extrema will move accordingly.  This
              can be used to better follow compact sources as they
              rise or set through the focal plane.
            az_only (bool): if True (the default), then only the
                Azimuth axis is put in ProgramTrack mode, and the El axis
                is put in Stop mode.
            scan_upload_length (float): number of seconds for each set
                of uploaded points. If this is not specified, the
                track manager will try to use as short a time as is
                reasonable.

        Notes:
          Note that all parameters are optional except for
          az_endpoint1 and az_endpoint2.  If only those two parameters
          are passed, the Process will scan between those endpoints,
          with the elevation axis held in Stop, indefinitely (until
          Process .stop method is called)..

        """
        self.log.info('User scan params: {params}', params=params)

        az_endpoint1 = params['az_endpoint1']
        az_endpoint2 = params['az_endpoint2']
        el_endpoint1 = params['el_endpoint1']
        el_endpoint2 = params['el_endpoint2']

        # Params with defaults configured ...
        az_speed = params['az_speed']
        az_accel = params['az_accel']
        if az_speed is None:
            az_speed = self.scan_params['az_speed']
        if az_accel is None:
            az_accel = self.scan_params['az_accel']

        # Do we need to limit the az_accel?  This limit comes from a
        # maximum jerk parameter; the equation below (without the
        # empirical 0.85 adjustment) is stated in the SATP ACU ICD.
        min_turnaround_time = (0.85 * az_speed / 9 * 11.616)**.5
        max_turnaround_accel = 2 * az_speed / min_turnaround_time
        if az_accel > max_turnaround_accel:
            self.log.warn('WARNING: user requested accel=%.2f; limiting to %.2f' %
                          (az_accel, max_turnaround_accel))
            az_accel = max_turnaround_accel

        # If el is not specified, drop in the current elevation.
        init_el = None
        if el_endpoint1 is None:
            el_endpoint1 = self.data['status']['summary']['Elevation_current_position']
        else:
            init_el = el_endpoint1
        if el_endpoint2 is None:
            el_endpoint2 = el_endpoint1

        azonly = params.get('az_only', True)
        scan_upload_len = params.get('scan_upload_length')
        scan_params = {k: params.get(k) for k in [
            'num_scans', 'num_batches', 'start_time',
            'wait_to_start', 'step_time', 'batch_size',
            'az_start', 'az_drift']
            if params.get(k) is not None}
        el_speed = params.get('el_speed', 0.0)

        plan = sh.plan_scan(az_endpoint1, az_endpoint2,
                            el=el_endpoint1, v_az=az_speed, a_az=az_accel,
                            az_start=scan_params.get('az_start'))

        # Use the plan to set scan upload parameters.
        if scan_params.get('step_time') is None:
            scan_params['step_time'] = plan['step_time']
        if scan_params.get('wait_to_start') is None:
            scan_params['wait_to_start'] = plan['wait_to_start']

        step_time = scan_params['step_time']
        point_batch_count = None
        if scan_upload_len:
            point_batch_count = scan_upload_len / step_time

        session.set_status('running')
        self.log.info('The plan: {plan}', plan=plan)
        self.log.info('The scan_params: {scan_params}', scan_params=scan_params)

        # Clear faults.
        self.log.info('Clearing faults to prepare for motion.')
        yield self.acu_control.clear_faults()
        yield dsleep(1)

        # Verify we're good to move
        ok, msg = yield self._check_ready_motion(session)
        if not ok:
            return False, msg

        # Seek to starting position
        self.log.info(f'Moving to start position, az={plan["init_az"]}, el={init_el}')
        ok, msg = yield self._go_to_axes(session, az=plan['init_az'], el=init_el)

        if not ok:
            return False, f'Start position seek failed with message: {msg}'

        # Prepare the point generator.
        g = sh.generate_constant_velocity_scan(az_endpoint1=az_endpoint1,
                                               az_endpoint2=az_endpoint2,
                                               az_speed=az_speed, acc=az_accel,
                                               el_endpoint1=el_endpoint1,
                                               el_endpoint2=el_endpoint2,
                                               el_speed=el_speed,
                                               az_first_pos=plan['init_az'],
                                               **scan_params)

        return (yield self._run_track(
            session=session, point_gen=g, step_time=step_time,
            azonly=azonly, point_batch_count=point_batch_count))

    @inlineCallbacks
    def _run_track(self, session, point_gen, step_time, azonly=False,
                   point_batch_count=None):
        """Run a ProgramTrack track scan, with points provided by a
        generator.

        Args:
          session: session object for the parent operation.
          point_gen: generator that yields points
          step_time: the minimum time between point track points.
            This is used to guarantee that points are uploaded
            sufficiently in advance for the servo unit to process
            them.
          azonly: set to True to leave the el axis locked.
          point_batch_count: number of points to include in batch
            uploads.  This parameter can be used to increase the value
            beyond the minimum set internally based on step_time.

        Returns:
          Tuple (success, msg) where success is a bool.

        """
        # The approximate loop time
        LOOP_STEP = 0.1  # seconds

        # Minimum number of points to have in the stack.  While the
        # docs strictly require 4, this number should be at least 1
        # more than that to allow for rounding when we are setting the
        # refill threshold.
        MIN_STACK_POP = 6  # points

        if point_batch_count is None:
            point_batch_count = 0

        STACK_REFILL_THRESHOLD = FULL_STACK - \
            max(MIN_STACK_POP + LOOP_STEP / step_time, point_batch_count)
        STACK_TARGET = FULL_STACK - \
            max(MIN_STACK_POP * 2 + LOOP_STEP / step_time, point_batch_count * 2)

        # Special error bits to watch here
        PTRACK_FAULT_KEYS = [
            'ProgramTrack_position_failure',
            'Track_start_too_early',
            'Turnaround_accel_too_high',
            'Turnaround_time_too_short',
        ]

        with self.azel_lock.acquire_timeout(0, job='generate_scan') as acquired:

            if not acquired:
                return False, f"Operation failed: {self.azel_lock.job} is running."
            if session.status not in ['starting', 'running']:
                return False, "Operation aborted before motion began."

            yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                                'Clear Stack')
            yield dsleep(0.2)

            if azonly:
                yield self._set_modes(az='ProgramTrack')
            else:
                yield self._set_modes(az='ProgramTrack', el='ProgramTrack')

            yield dsleep(0.5)

            # Values for mode are:
            # - 'go' -- keep uploading points (unless there are no more to upload).
            # - 'stop' -- do not request more points from generator; finish the ones you have.
            # - 'abort' -- do not upload more points; exit loop and clear stack.
            mode = 'go'

            lines = []
            last_mode = None
            was_graceful_exit = True
            faults = {}

            while True:
                current_modes = {'Az': self.data['status']['summary']['Azimuth_mode'],
                                 'El': self.data['status']['summary']['Elevation_mode'],
                                 'Remote': self.data['status']['platform_status']['Remote_mode']}
                free_positions = self.data['status']['summary']['Free_upload_positions']

                if last_mode != mode:
                    self.log.info(f'scan mode={mode}, line_buffer={len(lines)}, track_free={free_positions}')
                    last_mode = mode

                for k in PTRACK_FAULT_KEYS:
                    if k not in faults and self.data['status']['ACU_failures_errors'].get(k):
                        self.log.info('Fault during track: "{k}"', k=k)
                        faults[k] = True

                if mode != 'abort':
                    # Reasons we might decide to abort ...
                    if current_modes['Az'] != 'ProgramTrack':
                        self.log.warn('Unexpected mode transition!')
                        mode = 'abort'
                        was_graceful_exit = False
                    if current_modes['Remote'] == 0:
                        self.log.warn('ACU no longer in remote mode!')
                        mode = 'abort'
                        was_graceful_exit = False
                    if session.status == 'stopping':
                        mode = 'abort'

                if mode == 'abort':
                    lines = []

                # Is it time to upload more lines?
                if free_positions >= STACK_REFILL_THRESHOLD:
                    new_line_target = max(int(free_positions - STACK_TARGET), 1)

                    while mode == 'go' and (len(lines) < new_line_target or lines[-1][0] != 0):
                        try:
                            lines.extend(next(point_gen))
                        except StopIteration:
                            mode = 'stop'

                    # Grab the minimum batch
                    upload_lines, lines = lines[:new_line_target], lines[new_line_target:]

                    # If the last line has a "group" flag, keep transferring lines.
                    while len(lines) and len(upload_lines) and upload_lines[-1][0] != 0:
                        upload_lines.append(lines.pop(0))

                    if len(upload_lines):
                        # Discard the group flag and upload all.
                        text = ''.join([line for _flag, line in upload_lines])
                        yield self.acu_control.http.UploadPtStack(text)

                if len(lines) == 0 and free_positions >= FULL_STACK - 1:
                    break

                yield dsleep(LOOP_STEP)

            # Go to Stop mode?
            # yield self.acu_control.stop()

            # Clear the stack, but wait a bit or it can cause a fault.
            # Yes, sometimes you have to wait a very long time ...
            yield dsleep(10)
            yield self.acu_control.http.Command('DataSets.CmdTimePositionTransfer',
                                                'Clear Stack')

        if not was_graceful_exit:
            return False, 'Problems during scan'
        return True, 'Scan ended cleanly'

    @ocs_agent.param('starting_index', type=int, default=0)
    def exercise(self, session, params):
        """exercise(starting_index=0)

        **Process** - Run telescope platform through some pre-defined motions.

        For historical reasons, this does not command agent functions
        internally, but rather instantiates a *client* and calls the
        agent as though it were an external entity.

        """
        # Load the exercise plan.
        plans = yaml.safe_load(open(self.exercise_plan, 'rb'))
        super_plan = exercisor.get_plan(plans[self.acu_config_name])

        session.data = {
            'timestamp': time.time(),
            'iterations': 0,
            'attempts': 0,
            'errors': 0,
        }
        session.set_status('running')

        def _publish_activity(activity):
            msg = {
                'block_name': 'A',
                'timestamp': time.time(),
                'data': {'activity': activity},
            }
            self.agent.publish_to_feed('activity', msg)

        def _publish_error(delta_error=1):
            session.data['errors'] += delta_error
            msg = {
                'block_name': 'B',
                'timestamp': time.time(),
                'data': {'error_count': session.data['errors']}
            }
            self.agent.publish_to_feed('activity', msg)

        def _exit_now(ok, msg):
            _publish_activity('idle')
            self.agent.feeds['activity'].flush_buffer()
            return ok, msg

        _publish_activity('idle')
        _publish_error(0)

        target_instance_id = self.agent.agent_address.split('.')[-1]
        exercisor.set_client(target_instance_id, self.agent.site_args)
        settings = super_plan.get('settings', {})

        plan_idx = 0
        plan_t = None

        for plan in super_plan['steps']:
            plan['iter'] = iter(plan['driver'])

        while session.status in ['running']:
            time.sleep(1)
            session.data['timestamp'] = time.time()
            session.data['iterations'] += 1

            # Fault maintenance
            faults = exercisor.get_faults()
            if faults['safe_lock']:
                self.log.info('SAFE lock detected, exiting')
                return _exit_now(False, 'Exiting on SAFE lock.')

            if faults['local_mode']:
                self.log.info('LOCAL mode detected, exiting')
                return _exit_now(False, 'Exiting on LOCAL mode.')

            if faults['az_summary']:
                if session.data['attempts'] > 5:
                    self.log.info('Too many az summary faults, exiting.')
                    return _exit_now(False, 'Too many az summary faults.')
                session.data['attempts'] += 1
                self.log.info('az summary fault -- trying to clear.')
                exercisor.clear_faults()
                time.sleep(10)
                continue

            session.data['attempts'] = 0

            # Plan execution
            active_plan = super_plan['steps'][plan_idx]
            if plan_t is None:
                plan_t = time.time()

            now = time.time()
            if now - plan_t > active_plan['duration']:
                plan_idx = (plan_idx + 1) % len(super_plan['steps'])
                plan_t = None
                continue

            if settings.get('use_boresight'):
                bore_target = random.choice(settings['boresight_opts'])
                self.log.info(f'Setting boresight={bore_target}...')
                _publish_activity('boresight')
                exercisor.set_boresight(bore_target)

            plan, info = next(active_plan['iter'])

            self.log.info('Launching next scan. plan={plan}', plan=plan)

            _publish_activity(active_plan['driver'].code)
            ok = None
            if 'targets' in plan:
                exercisor.steps(**plan)
            else:
                exercisor.scan(**plan)
            _publish_activity('idle')

            if ok is None:
                self.log.info('Scan completed without error.')
            else:
                self.log.info(f'Scan exited with error: {ok}')
                _publish_error()

        return _exit_now(True, "Stopped run process")


def add_agent_args(parser_in=None):
    if parser_in is None:
        parser_in = argparse.ArgumentParser()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--acu-config")
    pgroup.add_argument("--exercise-plan")
    pgroup.add_argument("--no-processes", action='store_true',
                        default=False)
    pgroup.add_argument("--ignore-axes",
                        help="Comma-delimited list of axes to ignore "
                        "(el, az, third).")
    pgroup.add_argument("--disable-idle-reset", action='store_true',
                        help="Disable idle_reset, even for LAT.")
    return parser_in


def main(args=None):
    parser = add_agent_args()
    args = site_config.parse_args(agent_class='ACUAgent',
                                  parser=parser,
                                  args=args)
    agent, runner = ocs_agent.init_site_agent(args)
    _ = ACUAgent(agent, args.acu_config, args.exercise_plan,
                 startup=not args.no_processes,
                 ignore_axes=args.ignore_axes,
                 disable_idle_reset=args.disable_idle_reset)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
