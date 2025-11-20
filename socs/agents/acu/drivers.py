import calendar
import datetime
import math
import pickle
import time
from dataclasses import dataclass, replace

import numpy as np

import socs.agents.acu.turnarounds as turnarounds

#: The number of seconds in a day.
DAY = 86400

#: Minimum number of points to group together on the start of a new
# leg, to not trigger programtrack error.
MIN_GROUP_NEW_LEG = 4

#: Registry for turn-around profile types.
TURNAROUNDS_ENUM = {
    'standard': 0,
    'standard_gen': 1,
    'three_leg': 2,
}


def _progtrack_format_time(timestamp):
    fmt = '%j, %H:%M:%S'
    return (time.strftime(fmt, time.gmtime(timestamp))
            + '{:.6f}'.format(timestamp % 1.)[1:])


class FromFileScan:
    loop_time: float
    free_form: bool
    points: list
    preamble_count: int
    step_time: float
    az_range: tuple
    el_range: tuple


@dataclass
class TrackPoint:
    #: Timestamp of the point (unix timestamp)
    timestamp: float

    #: Azimuth (deg).
    az: float

    #: Elevation (deg).
    el: float

    #: Azimuth velocity (deg/s).
    az_vel: float

    #: Elevation velocity (deg/s).
    el_vel: float

    #: Az flag: 0 if stationary, 1 if non-final point of const-vel
    #: scan segment; 2 if final point of const-vel segment.
    az_flag: int = 0

    #: El flag: like az_flag but for el.
    el_flag: int = 0

    #: If 1, indicates that once this point is uploaded the next point
    #: in sequence also needs to be soon uploaded.  Used at start of a
    #: new const-vel scan segment.
    group_flag: int = 0


def track_point_time_shift(p, dt):
    return replace(p, timestamp=p.timestamp + dt)


def get_track_points_text(tpl, timestamp_offset=None, with_group_flag=False,
                          text_block=False):
    """Get a list of ProgramTrack lines for upload to ACU.

    Args:
      tpl (list): list of TrackPoint to convert.
      timestamp_offset (float): offset to add to all timestamps
        before rendering (defaults to 0).
      with_group_flag (bool): If True return each line as
        (group_flag, text).
      text_block (bool): If True, return all lines joined together
        into a single string.

    """
    if timestamp_offset is None:
        timestamp_offset = 0
    fmted_times = [_progtrack_format_time(p.timestamp + timestamp_offset)
                   for p in tpl]
    all_lines = [('{t}; {p.az:.6f}; {p.el:.6f}; {p.az_vel:.4f}; '
                  '{p.el_vel:.4f}; {p.az_flag}; {p.el_flag}\r\n')
                 .format(p=p, t=t)
                 for p, t in zip(tpl, fmted_times)]

    if text_block:
        return ''.join(all_lines)
    if with_group_flag:
        all_lines = [(p.group_flag, line) for p, line in zip(tpl, all_lines)]
    return all_lines


def from_file(filename, fmt=None):
    """Load a ProgramTrack trajectory from a file.  This function
    supports two formats. The modern format is a pickle file. The
    older numpy format is also supported.

    Parameters:
      filename (str): Full path to the file.
      fmt (str): Optional, one of "pickle" or "numpy". If this is
        unspecified, the code will assume pickle format unless the
        filename ends in "npy".

    Returns:
      FromFileScan: Object containing the loaded points and
        supporting config for ProgramTrack mode.

    Notes:

      For the pickle-based file format, the file must encode a
      single dict. Here is a minimal example::

        {
         'timestamp': [1747233498, 1747233499, ..., 1747233523],
         'az': [180, 181, ..., 160],
         'el': [60, 60, ..., 60],
        }

      Those 3 required entries are "vectors", with the same
      length. The vectors may be any iterable type but please use
      lists or ndarrays. Optionally, the user may specify these other
      vectors:

        - 'az_vel': the az velocity at each point.
        - 'el_vel': the el velocity at each point.
        - 'az_flag': the az flag.
        - 'el_flag': the el flag.
        - 'group_flag': the point grouping flag.

      If not provided, the "vel" vectors will be computed from the
      gradient of the position vectors.  The "flag" vectors will
      default to all 0.  See :class:`TrackPoint
      <socs.agents.acu.drivers.TrackPoint>` for purpose of the various
      flags.

      The following settings (stated with their default values) may
      also be included in the dict:

        - 'free_form' (bool, False): Specifies whether the track
          should be run with the turn-around profiler disabled and
          spline (rather than linear) interpolation enabled. When
          false, the ACU will do linear interpolation *and* automatic
          profiling of turn-arounds, between constant velocity
          segments. Setting free_form=False is appropriate for
          constant elevation, constant az speed scans.  Set
          free_form=True for more complex scans.
        - 'loopable' (bool, False): Specifies whether the track should
          be repeated, forever.  When this is the case, the final
          point of the track (i.e. the last point in all the vectors)
          is ignored *except for the timestamp*, which is used to set
          the time at which the next loop iteration is started.
        - 'preamble_count' (int, 0): If loopable, this specifies the
          number of points in the track (i.e. in each vector) that are
          not included in the loopable portion.  This permits the
          track to have a ramp-up, or partial initial scan segment,
          prior to entering the repetable template.

      The older numpy-based format does not support the additional
      settings.  The numpy file must contain an iterable with 5 or 7
      entries, where all entries are 1-d arrays of the same length.
      The first 5 arrays will correspond to 'timestamp', 'az', 'el',
      'az_vel', 'el_vel'.  The 2 optional arrays are 'az_flag' and
      'el_flag'.

    """
    if fmt is None:
        fmt = 'pickle'
        if filename.endswith('npy'):
            fmt = 'numpy'

    if fmt == 'numpy':
        info = np.load(filename)
        if len(info) not in [5, 7]:
            raise ValueError(f'Unexpected field count ({len(info)}) in {filename}')
        times, az, el, vaz, vel = info[:5]
        if len(info) == 5:
            az_flags = np.zeros(len(times), int)
            el_flags = az_flags
        elif len(info) == 7:
            az_flags = info[5].astype('int')
            el_flags = info[6].astype('int')

        output = FromFileScan()
        output.loop_time = 0.
        output.free_form = False
        output.step_time = np.diff(times).min()
        output.points = [TrackPoint(*a) for a in zip(
            times, az, el, vaz, vel, az_flags, el_flags)]
        output.az_range = (az.min(), az.max())
        output.el_range = (el.min(), el.max())

    elif fmt == 'pickle':
        data = pickle.load(open(filename, 'rb'))
        output = FromFileScan()
        output.loop_time = 0.
        output.free_form = data.get('free_form', False)

        keys = ['timestamp', 'az', 'el', 'az_vel', 'el_vel',
                'az_flag', 'el_flag', 'group_flag']
        vects = {k: data.get(k) for k in keys}
        n = len(vects['az'])

        dtv = np.gradient(vects['timestamp'])
        if vects['az_vel'] is None:
            vects['az_vel'] = np.gradient(vects['az']) / dtv
        if vects['el_vel'] is None:
            vects['el_vel'] = np.gradient(vects['el']) / dtv
        if vects['az_flag'] is None:
            vects['az_flag'] = np.zeros(n, int)
        if vects['el_flag'] is None:
            vects['el_flag'] = np.zeros(n, int)
        if vects['group_flag'] is None:
            vects['group_flag'] = np.zeros(n, int)

        output.preamble_count = data.get('preamble_count', 0)
        if data.get('loopable'):
            # Measure repeat time.
            output.loop_time = (vects['timestamp'][-1]
                                - vects['timestamp'][output.preamble_count])
            # ... and drop last point.
            for k in keys:
                vects[k] = vects[k][:-1]

        columns = [vects[k] for k in keys]
        output.points = [TrackPoint(*row) for row in zip(*columns)]

        output.step_time = np.diff(vects['timestamp']).min()
        output.az_range = (vects['az'].min(), vects['az'].max())
        output.el_range = (vects['el'].min(), vects['el'].max())

    else:
        raise ValueError(f"Invalid fmt={fmt}")

    return output


def timecode(acutime, now=None):
    """Takes the time code produced by the ACU status stream and returns
    a unix timestamp.

    Parameters:
        acutime (float): The time recorded by the ACU status stream,
            corresponding to the fractional day of the year.
        now (float): The time, as unix timestamp, to assume it is now.
            This is for testing, it defaults to time.time().

    """
    sec_of_day = (acutime - 1) * DAY
    if now is None:
        now = time.time()  # testing

    # This guard protects us at end of year, when time.time() and
    # acutime might correspond to different years.
    if acutime > 180:
        context = datetime.datetime.utcfromtimestamp(now - 30 * DAY)
    else:
        context = datetime.datetime.utcfromtimestamp(now + 30 * DAY)

    year = context.year
    gyear = calendar.timegm(time.strptime(str(year), '%Y'))
    comptime = gyear + sec_of_day
    return comptime


def _get_target_az(current_az, current_t, increasing, az_endpoint1, az_endpoint2, az_speed, az_drift):
    # Return the next endpoint azimuth, based on current (az, t)
    # and whether to move in +ve or -ve az direction.
    #
    # Includes the effects of az_drift, to keep the scan endpoints
    # (at least at the end of a scan) on the drifted trajectories.
    if increasing:
        target = max(az_endpoint1, az_endpoint2)
    else:
        target = min(az_endpoint1, az_endpoint2)
    if az_drift is not None:
        v = az_speed if increasing else -az_speed
        target = target + az_drift / (v - az_drift) * (
            (target - current_az + v * current_t))
    return target


def generate_constant_velocity_scan(az_endpoint1, az_endpoint2, az_speed,
                                    acc, el_endpoint1, el_endpoint2,
                                    el_speed=0,
                                    num_batches=None,
                                    num_scans=None,
                                    start_time=None,
                                    wait_to_start=10.,
                                    step_time=1.,
                                    batch_size=500,
                                    az_start='mid_inc',
                                    az_first_pos=None,
                                    az_drift=None,
                                    turnaround_method='standard'):
    """Python generator to produce times, azimuth and elevation positions,
    azimuth and elevation velocities, azimuth and elevation flags for
    arbitrarily long constant-velocity azimuth scans.

    Parameters:
        az_endpoint1 (float): azimuth endpoint for the scan start
        az_endpoint2 (float): second azimuth endpoint of the scan
        az_speed (float): speed of the constant-velocity azimuth motion
        acc (float): turnaround acceleration for the azimuth motion at the
            endpoints
        el_endpoint1 (float): elevation endpoint for the scan start
        el_endpoint2 (float): second elevation endpoint of the scan. For
            constant az scans, this must be equal to el_endpoint1.
        el_speed (float): speed of the elevation motion. For constant az
            scans, set to 0.0
        num_batches (int or None): sets the number of batches for the
            generator to create. Default value is None (interpreted as infinite
            batches).
        num_scans (int or None): if not None, limits the points
          returned to the specified number of constant velocity legs.
        start_time (float or None): a ctime at which to start the scan.
            Default is None, which is interpreted as starting now +
            wait_to_start.
        wait_to_start (float): number of seconds to wait between
            start_time and when the scan actually starts. Default is 10 seconds.
        step_time (float): time between points on the constant-velocity
            parts of the motion. Default value is 1.0 seconds. Minimum value is
            0.05 seconds.
        batch_size (int): number of values to produce in each iteration.
            Default is 500. Batch size is reset to the length of one leg of the
            motion if num_batches is not None.
        az_start (str): part of the scan to start at.  To start at one
            of the extremes, use 'az_endpoint1', 'az_endpoint2', or
            'end' (same as 'az_endpoint1').  To start in the midpoint
            of the scan use 'mid_inc' (for first half-leg to have
            positive az velocity), 'mid_dec' (negative az velocity),
            or 'mid' (velocity oriented towards endpoint2).
        az_first_pos (float): If not None, the first az scan will
            start at this position (but otherwise proceed in the same
            starting direction).
        az_drift (float): The rate (deg / s) at which to shift the
            scan endpoints in time.  This can be used to better track
            celestial sources in targeted scans.
        turnaround_method (str): The method used for generating turnaround.
            Default ('standard') generates the baseline minimal jerk trajectory.
            'three_leg' generates a three-leg turnaround which attempts to
            minimize the acceleration at the midpoint of the turnaround.

    Yields:
        points (list): a list of TrackPoint objects.  Raises
          StopIteration once exit condition, if defined, is met.

    """
    if az_endpoint1 == az_endpoint2:
        raise ValueError('Generator requires two different az endpoints!')

    # Force the el_speed to 0.  It matters because an el_speed in
    # ProgramTrack data that exceeds the ACU limits will cause the
    # point to be rejected, even if there's no motion in el planned
    # (which, at the time of this writing, there is not).
    el_speed = 0.

    # Note that starting scan direction gets modified, below,
    # depending on az_start.
    increasing = az_endpoint2 > az_endpoint1

    if az_start in ['az_endpoint1', 'az_endpoint2', 'end']:
        if az_start in ['az_endpoint1', 'end']:
            az = az_endpoint1
        else:
            az = az_endpoint2
            increasing = not increasing
    elif az_start in ['mid_inc', 'mid_dec', 'mid']:
        az = (az_endpoint1 + az_endpoint2) / 2
        if az_start == 'mid':
            pass
        elif az_start == 'mid_inc':
            increasing = True
        else:
            increasing = False
    else:
        raise ValueError(f'az_start value "{az_start}" not supported. Choose from '
                         'az_endpoint1, az_endpoint2, mid_inc, mid_dec')
    az_vel = az_speed if increasing else -az_speed

    # Bias the starting point for the first leg?
    if az_first_pos is not None:
        az = az_first_pos

    if start_time is None:
        t0 = time.time() + wait_to_start
    else:
        t0 = start_time
    t = 0
    turntime = 2.0 * az_speed / acc
    el = el_endpoint1
    if step_time < 0.05:
        raise ValueError('Time step size too small, must be at least '
                         '0.05 seconds')
    daz = step_time * az_speed
    el_vel = el_speed
    az_flag = 0
    el_flag = 0
    if num_batches is None:
        stop_iter = float('inf')
    else:
        stop_iter = num_batches
        batch_size = int(np.ceil(abs(az_endpoint2 - az_endpoint1) / daz))

    def dec_num_scans():
        nonlocal num_scans
        if num_scans is not None:
            num_scans -= 1

    def check_num_scans():
        return num_scans is None or num_scans > 0

    target_az = _get_target_az(az, t, increasing, az_endpoint1, az_endpoint2, az_speed, az_drift)
    point_group_batch = 0

    i = 0
    point_queue = []
    while i < stop_iter and check_num_scans():
        i += 1
        point_block = []
        for j in range(batch_size):
            if len(point_queue):  # Pull from points in the queue first
                point_block.append(point_queue.pop(0))
                continue

            point_block.append(TrackPoint(
                timestamp=t + t0,
                az=az, el=el, az_vel=az_vel, el_vel=el_vel,
                az_flag=az_flag, el_flag=el_flag,
                group_flag=int(point_group_batch > 0)))

            if point_group_batch > 0:
                point_group_batch -= 1

            if increasing:
                if az <= (target_az - 2 * daz):
                    t += step_time
                    az += daz
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                elif az == target_az:
                    # Turn around.
                    turnaround_track = turnarounds.gen_turnaround(turnaround_method=turnaround_method,
                                                                  t0=t + t0, az0=az, el0=el, v0=az_vel,
                                                                  turntime=turntime,
                                                                  az_flag=az_flag, el_flag=el_flag,
                                                                  point_group_batch=point_group_batch)
                    point_queue.extend(turnaround_track)

                    t += turntime
                    az_vel = -1 * az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = False
                    target_az = _get_target_az(az, t, increasing, az_endpoint1, az_endpoint2, az_speed, az_drift)
                    dec_num_scans()
                    point_group_batch = MIN_GROUP_NEW_LEG - 1
                else:
                    time_remaining = (target_az - az) / az_speed
                    az = target_az
                    t += time_remaining
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 2
                    el_flag = 0
            else:
                if az >= (target_az + 2 * daz):
                    t += step_time
                    az -= daz
                    az_vel = -1 * az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                elif az == target_az:
                    # Turn around.
                    turnaround_track = turnarounds.gen_turnaround(turnaround_method=turnaround_method,
                                                                  t0=t + t0, az0=az, el0=el, v0=az_vel,
                                                                  turntime=turntime,
                                                                  az_flag=az_flag, el_flag=el_flag,
                                                                  point_group_batch=point_group_batch)
                    point_queue.extend(turnaround_track)

                    t += turntime
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = True
                    target_az = _get_target_az(az, t, increasing, az_endpoint1, az_endpoint2, az_speed, az_drift)
                    dec_num_scans()
                    point_group_batch = MIN_GROUP_NEW_LEG - 1
                else:
                    time_remaining = (az - target_az) / az_speed
                    az = target_az
                    t += time_remaining
                    az_vel = -1 * az_speed
                    el_vel = el_speed
                    az_flag = 2
                    el_flag = 0

            if not check_num_scans():
                # Kill the velocity on the last point and exit -- this
                # was recommended at LAT FAT for smoothly stopping the
                # motion at end of program.
                point_block[-1].az_vel = 0
                point_block[-1].el_vel = 0
                break

        yield point_block


def generate_type3_scan(az_endpoint1, az_endpoint2, az_speed,
                        acc, el_endpoint1, el_endpoint2,
                        el_freq=.15,
                        az_vel_ref=None,
                        num_batches=None,
                        num_scans=None,
                        start_time=None,
                        wait_to_start=10.,
                        step_time=1.,
                        batch_size=500,
                        az_start='mid_inc',
                        az_first_pos=None,
                        az_drift=None,
                        turnaround_method='three_leg'):
    """Python generator to produce times, azimuth and elevation positions,
    azimuth and elevation velocities, azimuth and elevation flags for
    arbitrarily long type 3 scan.

    Parameters:
        az_endpoint1 (float): azimuth endpoint for the scan start
        az_endpoint2 (float): second azimuth endpoint of the scan
        az_speed (float): speed of the constant-velocity azimuth motion
        acc (float): turnaround acceleration for the azimuth motion at the
            endpoints
        el_endpoint1 (float): elevation endpoint for the scan start
        el_endpoint2 (float): second elevation endpoint of the scan. For
            constant az scans, this must be equal to el_endpoint1.
        el_freq(float): frequency of the elevation nods in Hz.
        az_vel_ref(float or None): azimuth to center the velocity profile at.
                                   If None then the average of the endpoints is used.
        num_batches (int or None): sets the number of batches for the
            generator to create. Default value is None (interpreted as infinite
            batches).
        num_scans (int or None): if not None, limits the points
          returned to the specified number of constant velocity legs.
        start_time (float or None): a ctime at which to start the scan.
            Default is None, which is interpreted as starting now +
            wait_to_start.
        wait_to_start (float): number of seconds to wait between
            start_time and when the scan actually starts. Default is 10 seconds.
        step_time (float): time between points on the constant-velocity
            parts of the motion. Default value is 1.0 seconds. Minimum value is
            0.05 seconds.
        batch_size (int): number of values to produce in each iteration.
            Default is 500. Batch size is reset to the length of one leg of the
            motion if num_batches is not None.
        az_start (str): part of the scan to start at.  To start at one
            of the extremes, use 'az_endpoint1', 'az_endpoint2', or
            'end' (same as 'az_endpoint1').  To start in the midpoint
            of the scan use 'mid_inc' (for first half-leg to have
            positive az velocity), 'mid_dec' (negative az velocity),
            or 'mid' (velocity oriented towards endpoint2).
        az_first_pos (float): If not None, the first az scan will
            start at this position (but otherwise proceed in the same
            starting direction).
        az_drift (float): The rate (deg / s) at which to shift the
            scan endpoints in time.  This can be used to better track
            celestial sources in targeted scans.

    Yields:
        points (list): a list of TrackPoint objects.  Raises
          StopIteration once exit condition, if defined, is met.

    """
    def get_scan_time(az0, az1, az_speed, az_cent):
        upper = -1 * np.cos(np.deg2rad(az1 - az_cent))
        lower = -1 * np.cos(np.deg2rad(az0 - az_cent))

        return abs(upper - lower) / np.deg2rad(az_speed)

    if az_endpoint1 == az_endpoint2:
        raise ValueError('Generator requires two different az endpoints!')

    if az_drift is not None:
        raise ValueError("Az drift not supported for type 2 or 3 scans!")

    # Get center of az range
    if az_vel_ref is None:
        az_vel_ref = (az_endpoint1 + az_endpoint2) / 2.
    az_cent = az_vel_ref - 90

    if any([abs(_az - az_vel_ref) > 70.
            for _az in [az_endpoint1, az_endpoint2]]):
        raise ValueError("Az limits for type 2 and 3 scans must not be more than 70 "
                         "degrees away from az_vel_ref.")

    # Get el throw
    el_throw = abs(el_endpoint2 - el_endpoint1) / 2
    el_cent = (el_endpoint1 + el_endpoint2) / 2.

    # Note that starting scan direction gets modified, below,
    # depending on az_start.
    increasing = az_endpoint2 > az_endpoint1

    if az_start in ['az_endpoint1', 'az_endpoint2', 'end']:
        if az_start in ['az_endpoint1', 'end']:
            az = az_endpoint1
        else:
            az = az_endpoint2
            increasing = not increasing
    elif az_start in ['mid_inc', 'mid_dec', 'mid']:
        az = (az_endpoint1 + az_endpoint2) / 2
        if az_start == 'mid':
            pass
        elif az_start == 'mid_inc':
            increasing = True
        else:
            increasing = False
    else:
        raise ValueError(f'az_start value "{az_start}" not supported. Choose from '
                         'az_endpoint1, az_endpoint2, mid_inc, mid_dec')
    az_vel = az_speed if increasing else -az_speed

    # Bias the starting point for the first leg?
    if az_first_pos is not None:
        az = az_first_pos

    if start_time is None:
        t0 = time.time() + wait_to_start
    else:
        t0 = start_time

    vel_0 = az_speed / np.sin(np.deg2rad(az_endpoint1 - az_cent))
    vel_1 = az_speed / np.sin(np.deg2rad(az_endpoint2 - az_cent))
    min_tt = {1: (0.85 * abs(vel_0) / 9 * 11.616)**.5, -1: (0.85 * abs(vel_1) / 9 * 11.616)**.5}
    tt = {1: max(2 * vel_0 / acc, min_tt[1]), -1: max(2 * vel_1 / acc, min_tt[-1])}
    t = 0
    el = el_endpoint1
    if step_time < 0.05:
        raise ValueError('Time step size too small, must be at least '
                         '0.05 seconds')
    az_flag = 0
    el_flag = 0
    if num_batches is None:
        stop_iter = float('inf')
    else:
        stop_iter = num_batches
        batch_size = int(np.ceil(get_scan_time(az_endpoint1, az_endpoint2, az_speed, az_cent) / step_time))

    def dec_num_scans():
        nonlocal num_scans
        if num_scans is not None:
            num_scans -= 1

    def check_num_scans():
        return num_scans is None or num_scans > 0

    target_az = _get_target_az(az, t, increasing, az_endpoint1, az_endpoint2, az_speed / np.sin(np.deg2rad(az - az_cent)), az_drift)
    point_group_batch = 0

    def get_el(_t):
        return (el_cent - el_throw * np.cos(_t * el_freq * 2 * np.pi),
                el_throw * el_freq * 2 * np.pi * np.sin(_t * el_freq * 2 * np.pi))

    i = 0
    point_queue = []
    while i < stop_iter and check_num_scans():
        i += 1
        point_block = []
        for j in range(batch_size):
            if len(point_queue):  # Pull from points in the queue first
                point_block.append(point_queue.pop(0))
                continue

            point_block.append(TrackPoint(
                timestamp=t + t0,
                az=az, el=0, az_vel=az_vel / np.sin(np.deg2rad(az - az_cent)), el_vel=1,
                az_flag=az_flag, el_flag=el_flag,
                group_flag=int(point_group_batch > 0)))

            if point_group_batch > 0:
                point_group_batch -= 1

            if increasing:
                if get_scan_time(az, target_az, az_speed, az_cent) > 2 * step_time:
                    t += step_time
                    az += step_time * az_speed / np.sin(np.deg2rad(az - az_cent))
                    az_vel = az_speed
                    az_flag = 0  # 1
                    el_flag = 0
                elif az == target_az:
                    point_group_batch = MIN_GROUP_NEW_LEG - 1
                    # Turn around.
                    _v = az_vel / np.sin(np.deg2rad(az - az_cent))
                    turnaround_track = turnarounds.gen_turnaround(turnaround_method=turnaround_method,
                                                                  t0=t + t0, az0=az, el0=el, v0=_v,
                                                                  turntime=tt[1],
                                                                  az_flag=az_flag, el_flag=el_flag,
                                                                  step_time=step_time,
                                                                  second_leg_time=0.,
                                                                  point_group_batch=point_group_batch)
                    point_queue.extend(turnaround_track)

                    # Turn around.
                    t += tt[1]
                    az_vel = -1 * az_speed
                    az_flag = 1  # 1
                    el_flag = 0
                    increasing = False
                    target_az = _get_target_az(az, t, increasing, az_endpoint1, az_endpoint2, az_speed / np.sin(np.deg2rad(az - az_cent)), az_drift)
                    dec_num_scans()
                else:
                    time_remaining = get_scan_time(az, target_az, az_speed, az_cent)
                    az = target_az
                    t += time_remaining
                    az_vel = az_speed
                    az_flag = 0  # 2
                    el_flag = 0
            else:
                if get_scan_time(az, target_az, az_speed, az_cent) > 2 * step_time:
                    t += step_time
                    az -= step_time * az_speed / np.sin(np.deg2rad(az - az_cent))
                    az_vel = -1 * az_speed
                    az_flag = 0  # 1
                    el_flag = 0
                elif az == target_az:
                    point_group_batch = MIN_GROUP_NEW_LEG - 1
                    # Turn around.
                    _v = az_vel / np.sin(np.deg2rad(az - az_cent))
                    turnaround_track = turnarounds.gen_turnaround(turnaround_method=turnaround_method,
                                                                  t0=t + t0, az0=az, el0=el, v0=_v,
                                                                  turntime=tt[1],
                                                                  az_flag=az_flag, el_flag=el_flag,
                                                                  step_time=step_time,
                                                                  second_leg_time=0.,
                                                                  point_group_batch=point_group_batch)
                    point_queue.extend(turnaround_track)

                    # Turn around.
                    t += tt[-1]
                    az_vel = az_speed
                    az_flag = 1  # 1
                    el_flag = 0
                    increasing = True
                    target_az = _get_target_az(az, t, increasing, az_endpoint1, az_endpoint2, az_speed / np.sin(np.deg2rad(az - az_cent)), az_drift)
                    dec_num_scans()
                else:
                    time_remaining = get_scan_time(az, target_az, az_speed, az_cent)
                    az = target_az
                    t += time_remaining
                    az_vel = -1 * az_speed
                    az_flag = 0  # 2
                    el_flag = 0

            if not check_num_scans():
                # Kill the velocity on the last point and exit -- this
                # was recommended at LAT FAT for smoothly stopping the
                # motion at end of program.
                point_block[-1].az_vel = 0
                point_block[-1].el_vel = 1000
                break

        for p in point_block:
            if p.el_vel == 1000:
                p.el_vel = 0.
            else:
                p.el, p.el_vel = get_el(p.timestamp - t0)

        yield point_block


def generate_type2_scan(az_endpoint1, az_endpoint2, az_speed,
                        acc, el_endpoint1,
                        az_vel_ref=None,
                        num_batches=None,
                        num_scans=None,
                        start_time=None,
                        wait_to_start=10.,
                        step_time=1.,
                        batch_size=500,
                        az_start='mid_inc',
                        az_first_pos=None,
                        az_drift=None,
                        turnaround_method='three_leg'):
    """Python generator to produce times, azimuth and elevation positions,
    azimuth and elevation velocities, azimuth and elevation flags for
    arbitrarily long type 2 scan.

    Parameters:
        az_endpoint1 (float): azimuth endpoint for the scan start
        az_endpoint2 (float): second azimuth endpoint of the scan
        az_speed (float): speed of the constant-velocity azimuth motion
        acc (float): turnaround acceleration for the azimuth motion at the
            endpoints
        el_endpoint1 (float): elevation endpoint for the scan start
        az_vel_ref(float or None): azimuth to center the velocity profile at.
                                   If None then the average of the endpoints is used.
        num_batches (int or None): sets the number of batches for the
            generator to create. Default value is None (interpreted as infinite
            batches).
        num_scans (int or None): if not None, limits the points
          returned to the specified number of constant velocity legs.
        start_time (float or None): a ctime at which to start the scan.
            Default is None, which is interpreted as starting now +
            wait_to_start.
        wait_to_start (float): number of seconds to wait between
            start_time and when the scan actually starts. Default is 10 seconds.
        step_time (float): time between points on the constant-velocity
            parts of the motion. Default value is 1.0 seconds. Minimum value is
            0.05 seconds.
        batch_size (int): number of values to produce in each iteration.
            Default is 500. Batch size is reset to the length of one leg of the
            motion if num_batches is not None.
        az_start (str): part of the scan to start at.  To start at one
            of the extremes, use 'az_endpoint1', 'az_endpoint2', or
            'end' (same as 'az_endpoint1').  To start in the midpoint
            of the scan use 'mid_inc' (for first half-leg to have
            positive az velocity), 'mid_dec' (negative az velocity),
            or 'mid' (velocity oriented towards endpoint2).
        az_first_pos (float): If not None, the first az scan will
            start at this position (but otherwise proceed in the same
            starting direction).
        az_drift (float): The rate (deg / s) at which to shift the
            scan endpoints in time.  This can be used to better track
            celestial sources in targeted scans.

    Yields:
        points (list): a list of TrackPoint objects.  Raises
          StopIteration once exit condition, if defined, is met.

    """
    return generate_type3_scan(az_endpoint1, az_endpoint2, az_speed,
                               acc, el_endpoint1, el_endpoint1,
                               el_freq=0,
                               az_vel_ref=az_vel_ref,
                               num_batches=num_batches,
                               num_scans=num_scans,
                               start_time=start_time,
                               wait_to_start=wait_to_start,
                               step_time=step_time,
                               batch_size=batch_size,
                               az_start=az_start,
                               az_first_pos=az_first_pos,
                               az_drift=az_drift,
                               turnaround_method=turnaround_method)


def plan_scan(az_end1, az_end2, el, v_az=1, a_az=1, az_start=None,
              scan_type=1):
    """Determine some important parameters for running a ProgramTrack
    scan with the desired end points, velocity, and mean turn-around
    acceleration.

    These get complicated in the limit of high velocity and narrow
    scan.

    Returns:

      A dict with outputs of the calculations.  The following items
      must be considered when generating and posting the track points:

      - 'step_time': The recommended track point separation, in
        seconds.
      - 'wait_to_start': The minimum time (s) between initiating
        ProgramTrack mode and the first uploaded point's timestamp.
      - 'init_az': The az (deg) at which to position the telescope
        before beginning the scan.  This takes into account any "ramp
        up" that needs to occur and the fact that such ramp up needs
        to be finished before the ACU starts profiling the first
        turn-around.

      The following dict items provide additional detail /
      intermediate results:

      - 'scan_start_buffer': Minimum amount (deg of az) by which to
        shift the start of the first scan leg in order to satisfy the
        requirements for az_prep and az_rampup.  This ultimately is
        what can make init_az different from the natural first leg
        starting point.  This parameter is always non-negative.
      - 'turnprep_buffer': Minimum azimuth travel required for
        ProgramTrack to prepare a turn-around.
      - 'rampup_buffer': Minimum azimuth travel required for
        ProgramTrack to ramp up to the first leg velocity.  Degrees,
        positive.
      - 'rampup_time': Number of seconds before the first track point
        where the platform could start moving (as part of smooth
        acceleration into the initial velocity).

    """
    # Convert Agent-friendly arguments to az/throw/init
    az = (az_end1 + az_end2) / 2
    throw = (az_end2 - az_end1) / 2

    if az_start in [None, 'mid']:
        init = 'mid'
    elif az_start == 'mid_inc':
        init = 'mid'
        throw = abs(throw)
    elif az_start == 'mid_dec':
        init = 'mid'
        throw = -abs(throw)
    elif az_start in ['az_endpoint1', 'end']:
        init = 'end'
    elif az_start in ['az_endpoint2']:
        init = 'end'
        throw = -throw
    else:
        raise ValueError(f'Unexpected az_start={az_start}')

    # Info to pass back.
    plan = {}

    # Point time separation: at least 5 points per leg, preferably 10.
    dt = 2 * abs(throw / v_az) / 10
    dt = min(max(dt, 0.1), 1.0)
    assert (2 * abs(throw / v_az) / dt >= 5)
    plan['step_time'] = dt

    # In the case of type 2/3 scans, force step_time to be at most 0.1 seconds.
    if scan_type in [2, 3]:
        plan['step_time'] = min(0.1, plan['step_time'])

    # Turn around prep distance (deg)? 5 point periods, times the vel.
    turnprep_buffer = 5 * dt * v_az

    # Ramp-up distance needed
    a0 = 1.  # Peak accel of ramp-up...
    rampup_buffer = v_az**2 / a0
    plan['turnprep_buffer'] = turnprep_buffer
    plan['rampup_buffer'] = rampup_buffer

    # Any az ramp-up prep required?
    if init == 'mid':
        scan_start_buffer = max(turnprep_buffer + rampup_buffer - abs(throw), 0)
    elif init == 'end':
        scan_start_buffer = max(turnprep_buffer + rampup_buffer - 2 * abs(throw), 0)
    plan['scan_start_buffer'] = scan_start_buffer

    # Set wait time (this comes out a little lower than its supposed to...)
    # plan['wait_time'] = v_az / a0 * 2
    plan['rampup_time'] = v_az / a0
    plan['wait_to_start'] = max(5, plan['rampup_time'] * 1.2)

    # Fill out some other useful info...
    plan['init_az'] = az - math.copysign(scan_start_buffer, throw)
    if init == 'end':
        plan['init_az'] -= throw

    return plan
