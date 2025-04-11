import argparse
import random
import struct
import time
from enum import Enum

import numpy as np
import ocs
import soaculib as aculib
import soaculib.status_keys as status_keys
import twisted.web.client as tclient
import yaml
from autobahn.twisted.util import sleep as dsleep
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock
from soaculib.retwisted_backend import RetwistedHttpBackend
from soaculib.twisted_backend import TwistedHttpBackend
from twisted.internet import protocol, reactor, threads
from twisted.internet.defer import DeferredList, inlineCallbacks

from socs.agents.acu import avoidance
from socs.agents.acu import drivers as sh
from socs.agents.acu import exercisor

#: The number of free ProgramTrack positions, when stack is empty.
FULL_STACK = 10000


#: Maximum update time (in s) for "monitor" process data, even with no changes
MONITOR_MAX_TIME_DELTA = 2.

#: Initial default scan params by platform type.
INIT_DEFAULT_SCAN_PARAMS = {
    'ccat': {
        'az_speed': 2,
        'az_accel': 1,
    },
    'satp': {
        'az_speed': 1,
        'az_accel': 1,
    },
}


#: Default Sun avoidance configuration blocks, by platform type.
#: Individual settings can be overridden in the platform config file.
#: The full "policy" is constructed from these settings, the
#: motion_limits, and the DEFAULT_POLICY in avoidance.py.  When
#: active Sun Avoidance is not enabled, policy parameters are still
#: useful for assessing Sun safety.
INIT_SUN_CONFIGS = {
    'ccat': {
        'enabled': False,
        'exclusion_radius': 20,
        'el_horizon': 10,
        'min_sun_time': 1800,
        'response_time': 7200,
    },
    'satp': {
        'enabled': True,
        'exclusion_radius': 20,
        'el_horizon': 10,
        'min_sun_time': 1800,
        'response_time': 7200,
    },
}

#: How often to refresh to Sun Safety map (valid up to 2x this time)
SUN_MAP_REFRESH = 6 * avoidance.HOUR


class ACUAgent:
    """Agent to acquire data from an ACU and control telescope pointing with the
    ACU.

    Parameters:
        acu_config (str):
            The configuration for the ACU, as referenced in aculib.configs.
            Default value is 'guess'.
        startup (bool):
            If True, immediately start the main monitoring processes
            for status and UDP data.
        ignore_axes (list of str):
            List of axes to "ignore". "ignore" means that the axis
            will not be commanded.  If a user requests an action that
            would otherwise move the axis, it is not moved but the
            action is assumed to have succeeded.  The values in this
            list should be drawn from "az", "el", "third", and "none".
            This argument *replaces* the setting from the config file.
            ("none" entries will simply be ignored.)
        disable_idle_reset (bool):
            If True, don't auto-start idle_reset process for LAT.
        disable_sun_avoidance (bool): If set, start up with Sun
            Avoidance completely disabled.
        min_el (float): If not None, override the default configured
            elevation lower limit.
        max_el (float): If not None, override the default configured
            elevation upper limit.

    """

    def __init__(self, agent, acu_config='guess',
                 startup=False, ignore_axes=None,
                 disable_idle_reset=False,
                 disable_sun_avoidance=False,
                 min_el=None, max_el=None,
                 ):

        # Agent support

        self.agent = agent
        self.log = agent.log

        # Separate locks for exclusive access to az/el, and boresight motions.
        self.azel_lock = TimeoutLock()
        self.boresight_lock = TimeoutLock()

        # Config file processing

        self.acu_config_name = acu_config
        self.acu_config = aculib.guess_config(acu_config)
        self.platform_type = self.acu_config['platform']  # ccat, satp.

        self.udp = self.acu_config['streams']['main']
        self.udp_schema = aculib.get_stream_schema(self.udp['schema'])
        self.udp_ext = self.acu_config['streams']['ext']

        # The 'status' dataset is necessary; the 'third' axis can be
        # None (in SATP it's all included in default); the 'shutter'
        # is enabled for LAT.
        _dsets = self.acu_config['_datasets']
        self.datasets = {
            'status': _dsets.get('default_dataset'),
            'third': _dsets.get('third_axis_dataset'),
            'shutter': _dsets.get('shutter_dataset'),
        }
        for k, v in self.datasets.items():
            if v is not None:
                self.datasets[k] = dict(_dsets['datasets'])[v]

        self.monitor_fields = status_keys.status_fields[self.platform_type]['status_fields']

        # Config file + overrides processing

        # Motion limits (az / el / third ranges).
        self.motion_limits = self.acu_config['motion_limits']
        if min_el:
            self.log.warn(f'Override: min_el={min_el}')
            self.motion_limits['elevation']['lower'] = min_el
        if max_el:
            self.log.warn(f'Override: max_el={max_el}')
            self.motion_limits['elevation']['upper'] = max_el

        # Sun avoidance (must be set up *after* finalizing motion limits)
        self.sun_config = INIT_SUN_CONFIGS[self.platform_type]
        self.sun_config.update(self.acu_config.get('sun_avoidance', {}))
        if disable_sun_avoidance:
            self.sun_config['enabled'] = False
        self.log.info('On startup, sun_config={sun_config}',
                      sun_config=self.sun_config)
        self._reset_sun_params()

        # Scan params (default vel / accel).
        self.default_scan_params = \
            dict(INIT_DEFAULT_SCAN_PARAMS[self.platform_type])
        for _k in self.default_scan_params.keys():
            _v = self.acu_config.get('scan_params', {}).get(_k)
            if _v is not None:
                self.default_scan_params[_k] = _v
        agent.log.info('On startup, default scan_params={scan_params}',
                       scan_params=self.default_scan_params)
        self.scan_params = dict(self.default_scan_params)

        # Axes to ignore.
        self.ignore_axes = self.acu_config.get('ignore_axes', [])
        if ignore_axes is not None:
            self.ignore_axes = [x for x in ignore_axes if x != 'none']
        if len(self.ignore_axes):
            assert all([x in ['az', 'el', 'third'] for x in self.ignore_axes])
            agent.log.warn('Note ignore_axes={i}', i=self.ignore_axes)

        # Named positions.
        self.named_positions = self.acu_config.get('named_positions', {})
        for k, v in self.named_positions.items():
            agent.log.info(f'Using named position {k}: {v[0]},{v[1]}')
            try:
                str(k), float(v[0]), float(v[1])
            except Exception:
                agent.log.error('Failed to parse named position "{k}"', k=k)

        # Exercise plan.
        self.exercise_plan = self.acu_config.get('exercise_plan')

        # Other flags.
        startup_idle_reset = (self.platform_type in ['lat', 'ccat']
                              and not disable_idle_reset)

        # The connections to the ACU.

        tclient._HTTP11ClientFactory.noisy = False

        self.acu_control = aculib.AcuControl(
            acu_config, backend=RetwistedHttpBackend(persistent=False))
        self.acu_read = aculib.AcuControl(
            acu_config, backend=TwistedHttpBackend(persistent=True), readonly=True)

        # Structures for passing status data around

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
                                'shutter': {},
                                },
                     'broadcast': {},
                     }

        # Structure for the broadcast process to communicate state to
        # the monitor process, for a data quality feed.
        self._broadcast_qual = {
            'timestamp': time.time(),
            'active': False,
            'time_offset': 0,
        }

        # Task, Process, Feed registration.

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
        agent.register_process('monitor_sun',
                               self.monitor_sun,
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
        agent.register_feed('acu_status',
                            record=True,
                            agg_params=fullstatus_agg_params,
                            buffer_time=1)
        agent.register_feed('acu_status_influx',
                            record=True,
                            agg_params=influx_agg_params,
                            buffer_time=1)
        agent.register_feed('acu_commands_influx',
                            record=True,
                            agg_params=influx_agg_params,
                            buffer_time=1)
        agent.register_feed('acu_udp_stream',
                            record=True,
                            agg_params=fullstatus_agg_params,
                            buffer_time=1)
        agent.register_feed('acu_broadcast_influx',
                            record=True,
                            agg_params=influx_agg_params,
                            buffer_time=1)
        agent.register_feed('acu_error',
                            record=True,
                            agg_params=basic_agg_params,
                            buffer_time=1)
        agent.register_feed('sun',
                            record=True,
                            agg_params=basic_agg_params,
                            buffer_time=0)
        agent.register_feed('data_qual',
                            record=True,
                            agg_params=basic_agg_params,
                            buffer_time=0)
        agent.register_task('go_to',
                            self.go_to,
                            blocking=False,
                            aborter=self._simple_task_abort)
        agent.register_task('go_to_named',
                            self.go_to_named,
                            blocking=False)
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
        agent.register_task('set_speed_mode',
                            self.set_speed_mode,
                            blocking=False)
        agent.register_task('stop_and_clear',
                            self.stop_and_clear,
                            blocking=False)
        agent.register_task('clear_faults',
                            self.clear_faults,
                            blocking=False)
        agent.register_task('update_sun',
                            self.update_sun,
                            blocking=False)
        agent.register_task('escape_sun_now',
                            self.escape_sun_now,
                            blocking=False,
                            aborter=self._simple_task_abort)
        if self.datasets['shutter']:
            agent.register_task('set_shutter',
                                self.set_shutter,
                                blocking=False,
                                aborter=self._simple_task_abort)

        # Automatic exercise program...
        if self.exercise_plan:
            agent.register_process(
                'exercise', self.exercise, self._simple_process_stop,
                stopper_blocking=False)
            # Use longer default frame length ... very low volume feed.
            agent.register_feed('activity',
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

        next_action = 0

        while session.status in ['starting', 'running']:
            if time.time() < next_action:
                yield dsleep(IDLE_RESET_TIMEOUT / 10)
                continue
            success = True
            try:
                yield self.acu_control.http.Values(self.datasets['status'])
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
            "IgnoredAxes": [],
            "NamedPositions": {
              "home": [
                180,
                40
              ]
            },
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

        # Note that session.data will get scanned, to assign data to
        # feed blocks.  We make an explicit list of items to ignore
        # during that scan (not_data_keys).
        session.data = {'PlatformType': self.acu_config['platform'],
                        'DefaultScanParams': self.scan_params,
                        'StatusResponseRate': 0.,
                        'IgnoredAxes': self.ignore_axes,
                        'NamedPositions': self.named_positions,
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

        @inlineCallbacks
        def _get_status():
            output = {}
            for short, collection in [
                    ('status', 'StatusDetailed'),
                    ('third', 'Status3rdAxis'),
                    ('shutter', 'StatusShutter')]:
                if self.datasets[short]:
                    output[collection] = (
                        yield self.acu_read.Values(self.datasets[short]))
                else:
                    output[collection] = {}
            return output

        session.data['StatusResponseRate'] = n_ok / (query_t - report_t)
        session.data.update((yield _get_status()))
        qual_pacer = Pacemaker(.1)

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

            if qual_pacer.next_sample <= time.time():
                # Publish UDP data health feed
                qual_pacer.sleep()  # should be instantaneous, just update counters
                bq = self._broadcast_qual
                bq_offset = bq['time_offset']
                if bq_offset is None:
                    bq_offset = 0.
                bq_ok = (bq['active'] and (now - bq['timestamp'] < 5)
                         and abs(bq_offset) < 1.)
                block = {
                    'timestamp': time.time(),
                    'block_name': 'qual0',
                    'data': {
                        'Broadcast_stream_ok': int(bq_ok),
                        'Broadcast_recv_offset': bq_offset,
                    }
                }
                self.agent.publish_to_feed('data_qual', block)

            try:
                session.data.update((yield _get_status()))
                session.data['connected'] = True
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
                # Check that we have data (commands and corotator often don't)
                if len(block['data']) > 0:
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
                    ('ACU_shutter', 'shutter'),
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
        FMT = self.udp_schema['format']
        FMT_LEN = struct.calcsize(FMT)
        UDP_PORT = self.udp['port']

        # The udp_data list is used as a queue; it contains
        # struct-unpacked samples from the UDP stream in the form
        # (time_received, data).
        udp_data = []
        fields = self.udp_schema['fields']
        session.data = {}

        # BroadcastStreamControl instance.
        stream = self.acu_control.streams['main']

        class MonitorUDP(protocol.DatagramProtocol):
            def datagramReceived(self, data, src_addr):
                now = time.time()
                host, port = src_addr
                offset = 0
                while len(data) - offset >= FMT_LEN:
                    d = struct.unpack(FMT, data[offset:offset + FMT_LEN])
                    udp_data.append((now, d))
                    offset += FMT_LEN

        handler = reactor.listenUDP(int(UDP_PORT), MonitorUDP())
        influx_data = {}
        influx_data['Time_bcast_influx'] = []
        for i in range(2, len(fields)):
            influx_data[fields[i].replace(' ', '_') + '_bcast_influx'] = []

        best_dt = None

        active = True
        last_packet_time = time.time()

        while session.status in ['running']:
            now = time.time()

            if len(udp_data) >= 200:
                if not active:
                    self.log.info('UDP packets are being received.')
                    active = True
                last_packet_time = now
                best_dt = None

                process_data = udp_data[:200]
                udp_data = udp_data[200:]
                for recv_time, d in process_data:
                    data_ctime = sh.timecode(d[0] + d[1] / sh.DAY)
                    if best_dt is None or abs(recv_time - data_ctime) < best_dt:
                        best_dt = recv_time - data_ctime

                    self.data['broadcast']['Time'] = data_ctime
                    influx_data['Time_bcast_influx'].append(data_ctime)
                    for i in range(2, len(d)):
                        self.data['broadcast'][fields[i].replace(' ', '_')] = d[i]
                        influx_data[fields[i].replace(' ', '_') + '_bcast_influx'].append(d[i])
                    acu_udp_stream = {'timestamp': self.data['broadcast']['Time'],
                                      'block_name': 'ACU_broadcast',
                                      'data': self.data['broadcast']
                                      }
                    self.agent.publish_to_feed('acu_udp_stream', acu_udp_stream)
                influx_means = {}
                for key in influx_data.keys():
                    influx_means[key] = np.mean(influx_data[key])
                    influx_data[key] = []
                acu_broadcast_influx = {'timestamp': influx_means['Time_bcast_influx'],
                                        'block_name': 'ACU_bcast_influx',
                                        'data': influx_means,
                                        }
                self.agent.publish_to_feed('acu_broadcast_influx', acu_broadcast_influx)
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

            self._broadcast_qual = {
                'timestamp': now,
                'active': active,
                'time_offset': best_dt,
            }
            yield dsleep(.01)

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
    def _go_to_axis(self, session, axis, target,
                    state_feedback=None):
        """Execute a movement, using "Preset" mode, on a specific axis.

        Args:
          session: session object variable of the parent operation.
          axis (str): one of 'Azimuth', 'Elevation', 'Boresight'.
          target (float): target position.
          state_feedback (dict): place to record state (see notes).

        Returns:
          ok (bool): True if the motion completed successfully and
            arrived at target position.
          msg (str): success/error message.

        Notes:
          This has various checks to ensure the movement executes as
          expected and in a timely fashion.  In the case that the
          warning horn sounds, this function should block until that
          completes, even if the requested position has been achieved
          (i.e. no actual motion was needed).

          The state_feedback may be used to pipeline the initial parts
          of the movement, so two functions aren't trying to command
          at the same time.  The ``state_feedback`` dict should be
          passed in initialized with ``{'state': 'init'}``.  When
          initial commanding is finished, this function will update it
          to `state="wait"`, and then on completion to `state="done"`.

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
        # can be as long as 12 seconds.  For the LAT, can take an
        # extra couple seconds if there were faults to clear.
        MAX_STARTUP_TIME = 15.

        # How long does it take to sound the warning horn?  It takes
        # 10 seconds.  Don't wait longer than this.
        WARNING_HORN_TOO_LONG = 15.

        # How long after mode change to Preset should we expect to see
        # brakes released, except in case that warning horn is
        # sounding?  3 seconds should be enough.
        WARNING_HORN_DETECT = 3.

        # Velocity to assume when computing maximum time a move should
        # take (to bail out in unforeseen circumstances).  There are
        # other checks in place to catch when the platform has not
        # started moving or has stopped at the wrong place.  So the
        # timeout computed from this should only activate in cases
        # where some other commander has taken over and then kept the
        # platform moving around.
        UNREASONABLE_VEL = 0.1

        # Positive acknowledgment of AcuControl.go_to
        OK_RESPONSE = b'OK, Command executed.'

        # Enum for the motion states
        State = Enum(f'{axis}State',
                     ['INIT', 'WAIT_MOVING', 'WAIT_STILL', 'FAIL', 'DONE'])

        if state_feedback is None:
            state_feedback = {}
        state_feedback['state'] = 'init'

        # If this axis is "ignore", skip it.
        for _axis, short_name in [
                ('Azimuth', 'az'),
                ('Elevation', 'el'),
                ('Boresight', 'third'),
        ]:
            if _axis == axis and short_name in self.ignore_axes:
                self.log.warn('Ignoring requested motion on {axis}', axis=axis)
                state_feedback['state'] = 'done'
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

            def get_active(_self):
                return bool(
                    self.data['status']['axis_state'][f'{axis}_brakes_released']
                    and not self.data['status']['axis_state'][f'{axis}_axis_stop'])

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

            def get_active(_self):
                return bool(
                    self.data['status']['corotator']['Corotator_brakes_released']
                    and not self.data['status']['corotator']['Corotator_axis_stop'])

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
        warning_horn = False

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
                    + MAX_STARTUP_TIME + 2 * PROFILE_TIME \
                    + WARNING_HORN_TOO_LONG

            # Do we seem to be moving / not moving?
            ok, _d = get_history(PROFILE_TIME)
            still = ok and (np.std(_d) < 0.01)
            moving = ok and (np.std(_d) >= 0.01)
            has_never_moved = (has_never_moved and not moving)

            near_destination = distance < THERE_YET
            mode_ok = (ctrl.get_mode() == 'Preset')
            active_now = ctrl.get_active()

            # Log only on state changes
            if state != last_state:
                _state = f'{axis}.state={state.name}'
                self.log.info(
                    f'{_state:<30} dt={now - start_time:7.3f} dist={distance:8.3f}')
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
                    if active_now:
                        state = state.WAIT_STILL
                    elif time_since_start > WARNING_HORN_TOO_LONG:
                        self.log.error('Warning horn too long!')
                        state = state.FAIL
                    elif time_since_start > WARNING_HORN_DETECT and not warning_horn:
                        warning_horn = True
                        self.log.info('Warning horn is probably sounding.')
                elif still and motion_expected:
                    self.log.error(f'Motion did not start within {MAX_STARTUP_TIME:.1f} s.')
                    state = state.FAIL

            elif state == State.WAIT_STILL:
                # Once moving, watch for end of motion.
                state_feedback['state'] = 'wait'
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

        state_feedback['state'] = 'done'
        return success, msg

    @inlineCallbacks
    def _go_to_axes(self, session, el=None, az=None, third=None,
                    clear_faults=False):
        """Execute a movement along multiple axes, using "Preset"
        mode.  This just launches _go_to_axis on each required axis,
        and collects the results.

        Args:
          session: session object variable of the parent operation.
          az (float): target for Azimuth axis (ignored if None).
          el (float): target for Elevation axis (ignored if None).
          third (float): target for Boresight axis (ignored if None).
          clear_faults (bool): whether to clear ACU faults first.

        Returns:
          ok (bool): True if all motions completed successfully and
            arrived at target position.
          msg (str): success/error message (combined from each target
            axis).

        """
        # Construct args for each _go_to_axis command... don't create
        # the Deferred here, because we will want to clear_faults
        # first (and the Deferred might start running before that
        # completes).
        move_defs = []
        for axis_name, short_name, target in [
                ('Azimuth', 'az', az),
                ('Elevation', 'el', el),
                ('Boresight', 'third', third),
        ]:
            if target is not None:
                move_defs.append(
                    (short_name, (session, axis_name, target)))

        if len(move_defs) is None:
            return True, 'No motion requested.'

        if clear_faults:
            yield self.acu_control.clear_faults()
            yield dsleep(1)

        # Start each move, waiting for each to pass the "init" state
        # before beginning the next one.
        moves = []
        for name, args in move_defs:
            fb = {'state': 'init'}
            move_def = self._go_to_axis(*args, state_feedback=fb)
            while fb['state'] == 'init':
                yield dsleep(.1)
            moves.append(move_def)

        # Now wait for all to complete.
        moves = yield DeferredList(moves)
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
            msg = ' '.join([f'{name}: {msg}'
                            for (name, args), msg in zip(move_defs, msgs)])
        return all_ok, msg

    @ocs_agent.param('az', type=float)
    @ocs_agent.param('el', type=float)
    @ocs_agent.param('end_stop', default=False, type=bool)
    @inlineCallbacks
    def go_to(self, session, params):
        """go_to(az, el, end_stop=False)

        **Task** - Move the telescope to a particular point (azimuth,
        elevation) in Preset mode. When motion has ended and the telescope
        reaches the preset point, it returns to Stop mode and ends.

        Parameters:
            az (float): destination angle for the azimuth axis
            el (float): destination angle for the elevation axis
            end_stop (bool): put the telescope in Stop mode at the end of
                the motion

        """
        with self.azel_lock.acquire_timeout(0, job='go_to') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.azel_lock.job} is running."

            if self._get_sun_policy('motion_blocked'):
                return False, "Motion blocked; Sun avoidance in progress."

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

            self.log.info(f'Requested position: az={target_az}, el={target_el}')

            legs, msg = yield self._get_sunsafe_moves(target_az, target_el,
                                                      zero_legs_ok=False)
            if msg is not None:
                self.log.error(msg)
                return False, msg

            if len(legs) > 1:
                self.log.info(f'Executing move via {len(legs)} separate legs (sun optimized)')

            for leg_az, leg_el in legs:
                all_ok, msg = yield self._go_to_axes(session, az=leg_az, el=leg_el)
                if not all_ok:
                    break

            if all_ok and params['end_stop']:
                yield self._set_modes(az='Stop', el='Stop')

        return all_ok, msg

    @ocs_agent.param('target', type=float)
    @ocs_agent.param('end_stop', default=False, type=bool)
    @inlineCallbacks
    def set_boresight(self, session, params):
        """set_boresight(target, end_stop=False)

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

            ok, msg = yield self._go_to_axis(session, 'Boresight', target)

            if ok and params['end_stop']:
                yield self._set_modes(third='Stop')

        return ok, msg

    @ocs_agent.param('target')
    @ocs_agent.param('end_stop', default=True, type=bool)
    @inlineCallbacks
    def go_to_named(self, session, params):
        """go_to_named(target, end_stop=True)

        **Task** - Move the telescope to a named position,
        e.g. "home", that has been configured through command line args.

        Parameters:
          target (str): name of the target position.
          end_stop (bool): put axes in Stop mode after motion

        """
        target = self.named_positions.get(params['target'])
        if target is None:
            return False, 'Position "%s" is not configured.' % params['target']

        ok, msg, _session = self.agent.start('go_to', {'az': target[0], 'el': target[1],
                                                       'end_stop': params['end_stop']})
        if ok == ocs.ERROR:
            return False, 'Failed to start go_to task.'
        ok, msg, _session = yield self.agent.wait('go_to')
        return (ok == ocs.OK), msg

    @ocs_agent.param('speed_mode', choices=['high', 'low'])
    @inlineCallbacks
    def set_speed_mode(self, session, params):
        """set_speed_mode(speed_mode)

        **Task** - Set the ACU Speed Mode.  This affects motion when
        in Preset mode, such as when using go_to in this Agent.  It
        should not affect the speed of scans done in ProgramTrack
        mode.

        Parameters:
          speed_mode (str): 'high' or 'low'.

        Notes:
          The axes must be in Stop mode for this to work.  This task
          will return an error if the command appears to have failed.

          The actual speed and acceleration settings for the "high"
          and "low" (perhaps called "aux") settings must be configured
          on the ACU front panel.

        """
        http = aculib.streams.ModularHttpInterface(
            self.acu_config['dev_url'], backend=TwistedHttpBackend())
        data = 'Command=Set Speed ' + params['speed_mode'].capitalize()
        resp_bytes = yield http.Post(data, 'DataSets.CmdGeneralTransfer', '3')
        resp = resp_bytes.decode('utf8')
        if '<p>Status: executed</p>' in resp:
            return True, "Speed mode changed."
        elif '<p>Status: not allowed</p>' in resp:
            return False, "Mode change blocked (are you in Stop?)"
        else:
            return False, "Response was not as expected."

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
            self.scan_params.update(self.default_scan_params)
        for k in ['az_speed', 'az_accel']:
            if params[k] is not None:
                self.scan_params[k] = params[k]
        self.log.info('Updated default scan params to {sp}', sp=self.scan_params)
        yield
        return True, 'Done'

    @ocs_agent.param('_')
    @inlineCallbacks
    def clear_faults(self, session, params):
        """clear_faults()

        **Task** - Clear any axis faults.

        """

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
        """fromfile_scan(filename, adjust_times=True, azonly=True)

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
        if self._get_sun_policy('motion_blocked'):
            return False, "Motion blocked; Sun avoidance in progress."

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

        # You must also not exceed the platform max accel.
        if self.motion_limits['azimuth'].get('accel'):
            max_turnaround_accel = min(
                max_turnaround_accel,
                self.motion_limits['azimuth'].get('accel') / 1.88)

        if az_accel > max_turnaround_accel:
            self.log.warn('WARNING: user requested accel=%.2f; limiting to %.2f' %
                          (az_accel, max_turnaround_accel))
            az_accel = max_turnaround_accel

        # If el is not specified, drop in the current elevation.
        if el_endpoint1 is None:
            el_endpoint1 = self.data['status']['summary']['Elevation_current_position']
        if el_endpoint2 is None:
            el_endpoint2 = el_endpoint1

        # If requested el is just outside acceptable range, tweak it in.
        _f, _ = self._get_limit_func('elevation')
        el_endpoint1, _untweaked_el = _f(el_endpoint1), el_endpoint1
        if abs(el_endpoint1 - _untweaked_el) > 0.1:
            return False, "Current elevation (%.4f) is well outside limits." % _untweaked_el
        init_el = el_endpoint1

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

        self.log.info('The plan: {plan}', plan=plan)
        self.log.info('The scan_params: {scan_params}', scan_params=scan_params)

        # Before any motion, check for sun safety.
        ok, msg = self._check_scan_sunsafe(az_endpoint1, az_endpoint2, el_endpoint1,
                                           az_speed, az_accel)
        if ok:
            self.log.info('Sun safety check: {msg}', msg=msg)
        else:
            self.log.error('Sun safety check fails: {msg}', msg=msg)
            return False, 'Scan is not Sun Safe.'

        # Clear faults.
        self.log.info('Clearing faults to prepare for motion.')
        yield self.acu_control.clear_faults()
        yield dsleep(1)

        # Verify we're good to move
        ok, msg = yield self._check_ready_motion(session)
        if not ok:
            return False, msg

        # Seek to starting position.  Note we ask for at least one leg
        # here, because go_to_axes knows how to wait for the warning
        # horn to finish before returning, which relieves us from
        # handling that delay in the (already onerous) scan point
        # timing.
        self.log.info(f'Moving to start position, az={plan["init_az"]}, el={init_el}')
        legs, msg = yield self._get_sunsafe_moves(plan['init_az'], init_el,
                                                  zero_legs_ok=False)
        if msg is not None:
            self.log.error(msg)
            return False, msg
        for leg_az, leg_el in legs:
            ok, msg = yield self._go_to_axes(session, az=leg_az, el=leg_el)
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

        # Time to allow for initial ProgramTrack transition.
        MAX_PROGTRACK_SET_TIME = 5.

        # Minimum number of points to have in the stack.  While the
        # docs strictly require 4, this number should be at least 1
        # more than that to allow for rounding when we are setting the
        # refill threshold.
        MIN_STACK_POP = 6  # points

        # Minimum amount of time (seconds), in advance, to populate
        # the trajectory.  In cases where step_time is short, this
        # creates a longer track window to survive agent outages.
        # (The cost is that stopping a scan may take a little longer.)
        MIN_STACK_ADVANCE_TIME = 3.

        # Minimum nuber of points to keep in the stack.
        _pbc = max(MIN_STACK_POP, MIN_STACK_ADVANCE_TIME / step_time)
        if point_batch_count is None or _pbc > point_batch_count:
            point_batch_count = _pbc

        STACK_REFILL_THRESHOLD = \
            FULL_STACK - point_batch_count - LOOP_STEP / step_time
        STACK_TARGET = \
            FULL_STACK - point_batch_count * 2 - LOOP_STEP / step_time

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
            yield dsleep(0.5)

            if azonly:
                yield self._set_modes(az='ProgramTrack')
            else:
                yield self._set_modes(az='ProgramTrack', el='ProgramTrack')

            yield dsleep(0.1)

            # Values for mode are:
            # - 'go' -- keep uploading points (unless there are no more to upload).
            # - 'stop' -- do not request more points from generator; finish the ones you have.
            # - 'abort' -- do not upload more points; exit loop and clear stack.
            mode = 'go'

            lines = []
            last_mode = None
            was_graceful_exit = True
            start_time = time.time()
            got_progtrack = False
            faults = {}
            got_points_in = False
            first_upload_time = None

            while True:
                now = time.time()
                current_modes = {'Az': self.data['status']['summary']['Azimuth_mode'],
                                 'El': self.data['status']['summary']['Elevation_mode'],
                                 'Remote': self.data['status']['platform_status']['Remote_mode']}
                free_positions = self.data['status']['summary']['Free_upload_positions']

                # Use this var to detect case where we're uploading
                # points but ACU is quietly dumping them because the
                # vel is too high.
                got_points_in = got_points_in \
                    or (got_progtrack and free_positions < FULL_STACK)

                if last_mode != mode:
                    self.log.info(f'scan mode={mode}, line_buffer={len(lines)}, track_free={free_positions}')
                    last_mode = mode

                for k in PTRACK_FAULT_KEYS:
                    if k not in faults and self.data['status']['ACU_failures_errors'].get(k):
                        self.log.info('Fault during track: "{k}"', k=k)
                        faults[k] = True

                if mode != 'abort':
                    # Reasons we might decide to abort ...
                    if current_modes['Az'] == 'ProgramTrack':
                        got_progtrack = True
                    else:
                        if got_progtrack:
                            self.log.warn('Unexpected exit from ProgramTrack mode!')
                            mode = 'abort'
                            was_graceful_exit = False
                        elif now - start_time > MAX_PROGTRACK_SET_TIME:
                            self.log.warn('Failed to set ProgramTrack mode in a timely fashion.')
                            mode = 'abort'
                            was_graceful_exit = False
                    if not got_points_in and (first_upload_time is not None) \
                       and (now - first_upload_time > 10):
                        self.log.warn('ACU seems to be dumping our track. Vel too high?')
                        mode = 'abort'
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

                    # Make sure that you get one more line than you
                    # need (len(lines) > new_line_target), so that
                    # after "grabbing the minimum batch", below, there
                    # is still >= 1 line left.  The lines-is-empty
                    # check is used to decide we're done.
                    while mode == 'go' and (len(lines) <= new_line_target or lines[-1][0] != 0):
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
                        for attempt in range(5):
                            _dt = time.time()
                            try:
                                # This seems to return b'Ok.' no matter ~what,
                                # so not much point checking it.
                                yield self.acu_control.http.UploadPtStack(text)
                                break
                            except Exception as err:
                                _dt = time.time() - _dt
                                self.log.warn(f'Upload {len(upload_lines)} failed (attempt {attempt}) after {_dt:.3f} seconds')
                                self.log.warn('Exception was: {err}', err=err)
                        else:
                            raise RuntimeError('Upload fail.')
                        if first_upload_time is None:
                            first_upload_time = time.time()

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

    #
    # Sun Safety Monitoring and Active Avoidance
    #

    def _reset_sun_params(self):
        """Resets self.sun_params based on the instance defaults, and
        motion_limits.  This must be called at least once, on startup,
        to set up Sun monitoring and avoidance properly.

        """
        # Set up sun_params data structure.
        _p = {
            # Global enable (but see "disable_until").
            'active_avoidance': False,

            # Can be set to a timestamp, in which case Sun Avoidance
            # is disabled until that time has passed.
            'disable_until': 0,

            # Flag for indicating normal motions should be blocked
            # (Sun Escape is active).
            'block_motion': False,

            # Flag for update_sun to indicate Sun map needs recomputed
            'recompute_req': False,

            # If set, should be a timestamp at which escape_sun_now
            # will be initiated.
            'next_drill': None,

            # Parameters for the Sun Safety Map computation.
            'safety_map_kw': {
                'sun_time_shift': 0,
            },

            # Avoidance policy, for use in avoidance decisions.
            'policy': {},
        }

        # Active avoidance?
        _p['active_avoidance'] = self.sun_config['enabled']

        # Avoidance requires platform limits and move policies
        _p['policy'].update({
            'min_az': self.motion_limits['azimuth']['lower'],
            'max_az': self.motion_limits['azimuth']['upper'],
            'min_el': self.motion_limits['elevation']['lower'],
            'max_el': self.motion_limits['elevation']['upper'],
            'axes_sequential': self.motion_limits.get('axes_sequential', False),
        })

        # User parameters defining the danger zone, and escape
        # policies.  This list should be kept consistent with the
        # preamble docs in avoidance.py.
        for k in [
                'exclusion_radius',
                'min_sun_time',
                'response_time',
                'el_horizon',
                'el_dodging',
                'axes_sequential',
        ]:
            if k in self.sun_config:
                _p['policy'][k] = self.sun_config[k]

        self.sun_params = _p

    def _get_sun_policy(self, key):
        now = time.time()
        p = self.sun_params
        active = (p['active_avoidance'] and (now >= p['disable_until']))

        if key == 'motion_blocked':
            return active and p['block_motion']
        elif key == 'sunsafe_moves':
            return active
        elif key == 'escape_enabled':
            return active
        elif key == 'map_valid':
            return (self.sun is not None
                    and self.sun.base_time is not None
                    and self.sun.base_time <= now
                    and self.sun.base_time >= now - 2 * SUN_MAP_REFRESH)
        else:
            return p[key]

    @ocs_agent.param('_')
    @inlineCallbacks
    def monitor_sun(self, session, params):
        """monitor_sun()

        **Process** - Monitors and reports the position of the Sun;
        maintains a Sun Safety Map for verifying that moves and scans
        are Sun-safe; triggers a "Sun escape" if the boresight enters
        an unsafe position.

        The monitoring functions are always active (as long as this
        process is running).  But the escape functionality must be
        explicitly enabled (through the default platform
        configuration, command line arguments, or the update_sun
        task).

        Session data looks like this::

          {
            "timestamp": 1698848292.5579932,
            "active_avoidance": false,
            "disable_until": 0,
            "block_motion": false,
            "recompute_req": false,
            "next_drill": null,
            "safety_map_kw": {
              "sun_time_shift": 0
            },
            "policy": {
              "exclusion_radius": 20,
              "el_horizon": 10,
              "min_sun_time": 1800,
              "response_time": 7200,
              "min_az": -90,
              "max_az": 450,
              "min_el": 18.5,
              "max_el": 90
            },
            "sun_pos": {
              "map_exists": true,
              "map_is_old": false,
              "map_ref_time": 1698848179.1123455,
              "platform_azel": [
                90.0158,
                20.0022
              ],
              "sun_radec": [
                216.50815789438036,
                -14.461844389380719
              ],
              "sun_azel": [
                78.24269024936028,
                60.919554369324096
              ],
              "sun_dist": 41.75087242151837,
              "sun_safe_time": 71760
            },
            "avoidance": {
              "safety_unknown": false,
              "warning_zone": false,
              "danger_zone": false,
              "escape_triggered": false,
              "escape_active": false,
              "last_escape_time": 0,
              "sun_is_real": true,
              "platform_is_moveable": true
            }
          }

        In debugging, the Sun position might be falsified.  In that
        case the "sun_pos" subtree will contain an entry like this::

          "WARNING": "Fake Sun Position is in use!",

        and "avoidance": "sun_is_real" will be set to false.  (No
        other functionality is changed when using a falsified Sun
        position; flags are computed and actions decided based on the
        false position.)

        """
        def _get_sun_map():
            # To run in thread ...
            start = time.time()
            new_sun = avoidance.SunTracker(policy=self.sun_params['policy'],
                                           **self.sun_params['safety_map_kw'])
            return new_sun, time.time() - start

        def _notify_recomputed(result):
            nonlocal req_out
            new_sun, compute_time = result
            self.log.info('(Re-)computed Sun Safety Map (took %.1fs)' %
                          compute_time)
            self.sun = new_sun
            req_out = False

        def lookup(keys, tree):
            if isinstance(keys, str):
                keys = [keys]
            if len(keys) == 0:
                if isinstance(tree, (bool, np.bool_)):
                    return int(tree)
                return tree
            return lookup(keys[1:], tree[keys[0]])

        # Feed -- unpack some elements of session.data
        feed_keys = {
            'sun_avoidance': ('active_avoidance', int),
            'sun_az': (('sun_pos', 'sun_azel', 0), float),
            'sun_el': (('sun_pos', 'sun_azel', 1), float),
            'sun_dist': (('sun_pos', 'sun_dist'), float),
            'sun_safe_time': (('sun_pos', 'sun_safe_time'), float),
        }
        for k in ['warning_zone', 'danger_zone',
                  'escape_triggered', 'escape_active']:
            feed_keys[f'sun_{k}'] = (('avoidance', k), int)
        feed_pacer = Pacemaker(.1)

        req_out = False
        self.sun = None
        last_panic = 0

        session.data = {}

        while session.status in ['starting', 'running']:
            new_data = {
                'timestamp': time.time(),
            }
            new_data.update(self.sun_params)

            try:
                az, el = [self.data['status']['summary'][f'{ax}_current_position']
                          for ax in ['Azimuth', 'Elevation']]
                if az is None or el is None:
                    raise KeyError
            except KeyError:
                az, el = None, None

            try:
                moveable = [bool(self.data['status']['platform_status'][k])
                            for k in ['Safe_mode', 'Remote_mode']]
                moveable = (not moveable[0]) and moveable[1]
            except KeyError:
                moveable = False

            no_map = self.sun is None
            old_map = (not no_map
                       and self.sun._now() - self.sun.base_time > SUN_MAP_REFRESH)
            do_recompute = (
                not req_out
                and (no_map or old_map or self.sun_params['recompute_req'])
            )

            if do_recompute:
                req_out = True
                self.sun_params['recompute_req'] = False
                threads.deferToThread(_get_sun_map).addCallback(
                    _notify_recomputed)

            new_data.update({
                'sun_pos': {
                    'map_exists': not no_map,
                    'map_is_old': old_map,
                    'map_ref_time': None if no_map else self.sun.base_time,
                    'platform_azel': (az, el),
                },
            })

            # Flags for unsafe position.
            safety_known, danger_zone, warning_zone = False, False, False
            # Flag for time shift during debugging.
            sun_is_real = True
            if self.sun is not None:
                info = self.sun.get_sun_pos(az, el)
                sun_is_real = ('WARNING' not in info)
                new_data['sun_pos'].update(info)
                if az is not None:
                    t = self.sun.check_trajectory([az], [el])['sun_time']
                    new_data['sun_pos']['sun_safe_time'] = t if t > 0 else 0
                    safety_known = True
                    danger_zone = (t < self.sun_params['policy']['min_sun_time'])
                    warning_zone = (t < self.sun_params['policy']['response_time'])

            # Has a drill been requested?
            drill_req = (self.sun_params['next_drill'] is not None
                         and self.sun_params['next_drill'] <= time.time())

            # Should we be doing a escape_sun_now?
            panic_for_real = safety_known and danger_zone and self._get_sun_policy('escape_enabled')
            panic_for_fun = drill_req

            # Is escape_sun_now task running?
            ok, msg, _session = self.agent.status('escape_sun_now')
            escape_in_progress = (_session.get('status', 'done') != 'done')

            # Block motion as long as we are not sun-safe.
            self.sun_params['block_motion'] = (panic_for_real or escape_in_progress)

            new_data['avoidance'] = {
                'safety_unknown': not safety_known,
                'warning_zone': warning_zone,
                'danger_zone': danger_zone,
                'escape_triggered': panic_for_real,
                'escape_active': escape_in_progress,
                'last_escape_time': last_panic,
                'sun_is_real': sun_is_real,
                'platform_is_moveable': moveable,
            }

            if (panic_for_real or panic_for_fun):
                now = time.time()
                # Different retry conditions for moveable / not moveable
                if moveable and (now - last_panic > 60.):
                    # When moveable, only attempt escape every 1 minute.
                    self.log.warn('monitor_sun is requesting escape_sun_now.')
                    self.agent.start('escape_sun_now')
                    last_panic = now
                elif not moveable and (now - last_panic > 600.):
                    # When not moveable, only print complaint message every 10 minutes.
                    self.log.warn('monitor_sun cannot request escape_sun_now, '
                                  'because platform not moveable by remote!')
                    last_panic = now

                # Regardless, clear the drill indicator -- we don't
                # want that to occur randomly later.
                self.sun_params['next_drill'] = None

            # Update session.
            session.data.update(new_data)

            # Publish -- only if we have the sun pos though..
            if sun_is_real and safety_known and feed_pacer.next_sample <= time.time():
                feed_pacer.sleep()  # should be instantaneous, just update counters
                block = {'timestamp': time.time(),
                         'block_name': 'sun0',
                         'data': {}}
                for kshort, (keys, cast) in feed_keys.items():
                    block['data'][kshort] = cast(lookup(keys, new_data))
                self.agent.publish_to_feed('sun', block)

            yield dsleep(1)

        return True, 'monitor_sun exited cleanly.'

    @ocs_agent.param('reset', type=bool, default=None)
    @ocs_agent.param('enable', type=bool, default=None)
    @ocs_agent.param('temporary_disable', type=float, default=None)
    @ocs_agent.param('escape', type=bool, default=None)
    @ocs_agent.param('exclusion_radius', type=float, default=None)
    @ocs_agent.param('shift_sun_hours', type=float, default=None)
    def update_sun(self, session, params):
        """update_sun(reset=None, enable=None, temporary_disable=None, \
                      escape=None, exclusion_radius=None, \
                      shift_sun_hours=None)

        **Task** - Update Sun monitoring and avoidance parameters.

        All arguments are optional.

        Args:
          reset (bool): If True, reset all sun_params to the platform
            defaults.  (The "defaults" includes any overrides
            specified on Agent command line.)
          enable (bool): If True, enable active Sun avoidance.  If
            avoidance was temporarily disabled it is re-enabled.  If
            False, disable active Sun avoidance (non-temporarily).
          temporary_disable (float): If set, disable Sun avoidance for
            this number of seconds.
          escape (bool): If True, schedule an escape drill for 10
            seconds from now.
          exclusion_radius (float): If set, change the FOV radius
            (degrees), for Sun avoidance purposes, to this number.
          shift_sun_hours (float): If set, compute the Sun position as
            though it were this many hours in the future.  This is for
            debugging, testing, and work-arounds.  Pass zero to
            cancel.

        """
        do_recompute = False
        now = time.time()
        self.log.info('update_sun params: {params}',
                      params={k: v for k, v in params.items()
                              if v is not None})

        if params['reset']:
            self._reset_sun_params()
            do_recompute = True
        if params['enable'] is not None:
            self.sun_params['active_avoidance'] = params['enable']
            self.sun_params['disable_until'] = 0
        if params['temporary_disable'] is not None:
            self.sun_params['disable_until'] = params['temporary_disable'] + now
        if params['escape']:
            self.log.warn('Setting sun escape drill to start in 10 seconds.')
            self.sun_params['next_drill'] = now + 10
        if params['exclusion_radius'] is not None:
            self.sun_params['policy']['exclusion_radius'] = \
                params['exclusion_radius']
            do_recompute = True
        if params['shift_sun_hours'] is not None:
            self.sun_params['safety_map_kw']['sun_time_shift'] = \
                params['shift_sun_hours'] * 3600
            do_recompute = True

        if do_recompute:
            self.sun_params['recompute_req'] = True

        return True, 'Params updated.'

    @ocs_agent.param('_')
    @inlineCallbacks
    def escape_sun_now(self, session, params):
        """escape_sun_now()

        **Task** - Take control of the platform, and move it to a
        Sun-Safe position.  This will abort/stop any current go_to or
        generate_scan, identify the safest possible path to North or
        South (without changing elevation, if possible), and perform
        the moves to get there.

        """
        state = 'init'
        last_state = state

        session.data = {'state': state,
                        'timestamp': time.time()}

        while session.status in ['starting', 'running'] and state not in ['escape-done']:
            az, el = [self.data['status']['summary'][f'{ax}_current_position']
                      for ax in ['Azimuth', 'Elevation']]

            if state == 'init':
                state = 'escape-abort'
            elif state == 'escape-abort':
                # raise stop flags and issue stop on motion ops
                for op in ['generate_scan', 'go_to']:
                    self.agent.stop(op)
                    self.agent.abort(op)
                state = 'escape-wait-idle'
                timeout = 30
            elif state == 'escape-wait-idle':
                for op in ['generate_scan', 'go_to']:
                    ok, msg, _session = self.agent.status(op)
                    if _session.get('status', 'done') != 'done':
                        break
                else:
                    state = 'escape-move'
                    last_move = time.time()
                timeout -= 1
                if timeout < 0:
                    state = 'escape-stop'
            elif state == 'escape-stop':
                yield self._stop()
                state = 'escape-move'
                last_move = time.time()
            elif state == 'escape-move':
                self.log.info('Getting escape path for (t, az, el) = '
                              '(%.1f, %.3f, %.3f)' % (time.time(), az, el))
                escape_path = self.sun.find_escape_paths(az, el)
                if escape_path is None:
                    self.log.error('Failed to find acceptable path; using '
                                   'failsafe (South, low el).')
                    legs = [(180., max(self.sun_params['policy']['min_el'], 0))]
                else:
                    legs = escape_path['moves'].nodes[1:]
                self.log.info('Escaping to (az, el)={pos} ({n} moves)',
                              pos=legs[-1], n=len(legs))
                state = 'escape-move-legs'
                leg_d = None
            elif state == 'escape-move-legs':
                def _leg_done(result):
                    nonlocal state, last_move, leg_d
                    all_ok, msg = result
                    if not all_ok:
                        self.log.error('Leg failed.')
                        # Recompute the escape path.
                        if time.time() - last_move > 60:
                            self.log.error('Too many failures -- giving up for now')
                            state = 'escape-done'
                        else:
                            state = 'escape-move'
                    else:
                        leg_d = None
                        last_move = time.time()
                    if not self._get_sun_policy('escape_enabled'):
                        state = 'escape-done'
                if leg_d is None:
                    if len(legs) == 0:
                        state = 'escape-done'
                    else:
                        leg_az, leg_el = legs.pop(0)
                        leg_d = self._go_to_axes(session, az=leg_az, el=leg_el,
                                                 clear_faults=True)
                        leg_d.addCallback(_leg_done)
            elif state == 'escape-done':
                # This block won't run -- loop will exit.
                pass

            session.data['state'] = state
            if state != last_state:
                self.log.info('escape_sun_now: state is now "{state}"', state=state)
                last_state = state
            yield dsleep(1)

        return True, "Exited."

    def _check_scan_sunsafe(self, az1, az2, el, v_az, a_az):
        """This will return True if active avoidance is disabled.  If active
        avoidance is enabled, then it will only return true if the
        planned scan seems to currently be sun-safe.

        """
        if not self._get_sun_policy('sunsafe_moves'):
            return True, 'Sun-safety checking is not enabled.'

        if not self._get_sun_policy('map_valid'):
            return False, 'Sun Safety Map not computed or stale; run the monitor_sun process.'

        # Include a bit of buffer for turn-arounds.
        az1, az2 = min(az1, az2), max(az1, az2)
        turn = v_az**2 / a_az
        az1 -= turn
        az2 += turn
        n = max(2, int(np.ceil((az2 - az1) / 1.)))
        azs = np.linspace(az1, az2, n)

        info = self.sun.check_trajectory(azs, azs * 0 + el)
        safe = info['sun_time'] >= self.sun_params['policy']['min_sun_time']
        if safe:
            msg = 'Scan is safe for %.1f hours' % (info['sun_time'] / 3600)
        else:
            msg = 'Scan will be unsafe in %.1f hours' % (info['sun_time'] / 3600)

        return safe, msg

    def _get_sunsafe_moves(self, target_az, target_el, zero_legs_ok=True):
        """Given a target position, find a Sun-safe way to get there.  This
        will either be a direct move, or else an ordered slew in az
        before el (or vice versa).

        Returns (legs, msg).  If legs is None, it indicates that no
        Sun-safe path could be found; msg is an error message.  If a
        path can be found, the legs is a list of intermediate move
        targets, ``[(az0, el0), (az1, el1) ...]``, terminating on
        ``(target_az, target_el)``.  msg is None in that case.

        In the case that platform is already at the target position,
        an empty list of legs will be returned unless zero_legs_ok is
        False in which case a 1-entry list of legs is returned, with
        the target position in it.

        When Sun avoidance is not enabled, this function returns as
        though the direct path to the target is a safe one (though
        axes_sequential=True may turn this into a move with two legs).

        """
        # Get current position.
        try:
            az, el = [self.data['status']['summary'][f'{ax}_current_position']
                      for ax in ['Azimuth', 'Elevation']]
            if az is None or el is None:
                raise KeyError
        except KeyError:
            return None, 'Current position could not be determined.'

        if not self._get_sun_policy('sunsafe_moves'):
            if self.motion_limits.get('axes_sequential'):
                # Move in az first, then el.
                return [(target_az, el), (target_az, target_el)], None
            return [(target_az, target_el)], None

        if not self._get_sun_policy('map_valid'):
            return None, 'Sun Safety Map not computed or stale; run the monitor_sun process.'

        # Check the target position and block it outright.
        if self.sun.check_trajectory([target_az], [target_el])['sun_time'] <= 0:
            return None, 'Requested target position is not Sun-Safe.'

        moves = self.sun.analyze_paths(az, el, target_az, target_el)
        move, decisions = self.sun.select_move(moves)
        if move is None:
            return None, 'No Sun-Safe moves could be identified!'

        legs = list(move['moves'].nodes)
        if len(legs) == 1 and not zero_legs_ok:
            return legs, None
        return legs[1:], None

    @ocs_agent.param('action', choices=['open', 'close'])
    @inlineCallbacks
    def set_shutter(self, session, params):
        """set_shutter(action)

        **Task** - Request a (LAT) shutter action, wait for it to
        complete or fail.

        Args:
          action (str): 'open' or 'close'

        """
        def log(msg):
            session.add_message(msg)

        log(f'requested action={params["action"]}')

        if self.data['status'].get('shutter', {}).get('Shutter_open') is None:
            return False, 'Shutter dataset does not seem to be populating.'

        if params['action'] == 'open':
            dset_cmd = 'ShutterOpen'
            desired_key, undesired_key = 'Shutter_open', 'Shutter_closed'
        else:
            dset_cmd = 'ShutterClose'
            desired_key, undesired_key = 'Shutter_closed', 'Shutter_open'

        OK_RESPONSE = b'OK, Command executed.'

        # This just needs to be longer than 1 loop time.
        STATE_WAIT = 5.

        # Shutter typically closes in ~45 seconds.  But in early tests
        # it sometimes takes an additional 45 seconds for moving->0.
        MOVING_WAIT = 120.

        state = 'init'
        session.data = {'state': state,
                        'timestamp': time.time()}

        while (session.status in ['starting', 'running']
               and state not in ['done', 'error']):
            last_state = state
            now = time.time()

            az, el = [self.data['status']['summary'][f'{ax}_current_position']
                      for ax in ['Azimuth', 'Elevation']]
            shutter = self.data['status']['shutter']

            for bad_key in ['Shutter_timeout', 'Shutter_failure']:
                if shutter[bad_key]:
                    state = 'error'
                    message = f'Detected error state: {bad_key}'

            if state in ['error', 'done']:
                pass

            elif state == 'init':
                # Issue the command
                result = yield self.acu_control.Command(self.datasets['shutter'], dset_cmd)
                if result == OK_RESPONSE:
                    state = 'wait-moving'
                    timeout = time.time() + STATE_WAIT
                else:
                    state = 'error'
                    message = 'Failed to issue shutter command.'

            elif state == 'wait-moving':
                if now > timeout:
                    state = 'error'
                    message = 'Shutter failed to start moving.'
                elif shutter['Shutter_moving']:
                    state = 'wait-stopped'
                    timeout = now + MOVING_WAIT

            elif state == 'wait-stopped':
                if now > timeout:
                    state = 'error'
                    message = 'Shutter will not stop moving.'
                elif not shutter['Shutter_moving']:
                    state = 'wait-final'
                    timeout = now + STATE_WAIT

            elif state == 'wait-final':
                if now > timeout:
                    state = 'error'
                    message = 'Shutter failed to reach final expected state.'
                elif shutter[desired_key] and not shutter[undesired_key]:
                    state = 'done'
                    message = 'Shutter move successful.'

            else:
                message = f'invalid state: {state}'
                state = 'error'

            session.data['state'] = state
            if state != last_state:
                log(f'set_shutter: state is now "{state}"')
                last_state = state
            yield dsleep(1)

        if state == 'done':
            return True, message
        elif state == 'error':
            return False, message

        return False, 'Aborted in state {state}'

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
    pgroup.add_argument("--no-processes", action='store_true',
                        default=False)
    pgroup.add_argument("--ignore-axes", choices=['el', 'az', 'third', 'none'],
                        nargs='+', help="One or more axes to ignore.")
    pgroup.add_argument("--disable-idle-reset", action='store_true',
                        help="Disable idle_reset, even for LAT.")
    pgroup.add_argument("--min-el", type=float,
                        help="Override the minimum el defined in platform config.")
    pgroup.add_argument("--max-el", type=float,
                        help="Override the maximum el defined in platform config.")
    pgroup.add_argument("--disable-sun-avoidance", action='store_true',
                        help="Disable Sun Avoidance before startup.")

    return parser_in


def main(args=None):
    parser = add_agent_args()
    args = site_config.parse_args(agent_class='ACUAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    _ = ACUAgent(agent, args.acu_config,
                 startup=not args.no_processes,
                 ignore_axes=args.ignore_axes,
                 disable_idle_reset=args.disable_idle_reset,
                 disable_sun_avoidance=args.disable_sun_avoidance,
                 min_el=args.min_el,
                 max_el=args.max_el)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
