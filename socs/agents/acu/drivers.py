import calendar
import datetime
import math
import time

import numpy as np

#: The number of seconds in a day.
DAY = 86400

#: Minimum number of points to group together on the start of a new
# leg, to not trigger programtrack error.
MIN_GROUP_NEW_LEG = 4


def constant_velocity_scanpoints(azpts, el, azvel, acc, ntimes):
    """
    Produces lists of times, azimuths, elevations, azimuthal velocities,
    elevation velocities, azimuth motion flags, and elevation motion flags
    for a finitely long azimuth scan with constant velocity. Scan begins
    at the first azpts value.

    Parameters:
        azpts (2-tuple): The endpoints of motion in azimuth, where the
            first point is the start position of the scan.
        el (float): The elevation that is maintained throughout the scan
        azvel (float): Desired speed of the azimuth motion in degrees/sec
        acc (float): The turnaround acceleration in degrees/sec^2
        ntimes(int): Number of times to travel between the endpoints.
            ntimes = 1 corresponds to a scan from, ex., left to right, and does not
            return to left.

    Returns:
        tuple of lists : (times, azimuths, elevations, azimuth veolicities,
        elevation velocities, azimuth flags, elevation flags)
    """
    if float(azvel) == 0.0:
        print('Azimuth velocity is zero, invalid scan parameter')
        return False
    if float(acc) == 0.0:
        print('Acceleration is zero, unable to calculate turnaround')
        return False
    turn_time = 2 * azvel / acc
    tot_time_dir = float((abs(azpts[1] - azpts[0])) / azvel)
    num_dirpoints = int(tot_time_dir * 10.)
    if num_dirpoints < 2:
        print('Scan is too short to run')
        return False
    sect_start_time = 0.0
    conctimes = []
    concaz = []
    el1 = np.linspace(el, el, num_dirpoints)
    concel = list(el1)
    concva = []
    ve1 = np.zeros(num_dirpoints)
    concve = list(ve1)

    # Flag values:
    # 0 : unidentified portion of the scan
    # 1 : constant velocity, with the next point at the same velocity
    # 2 : final point before a turnaround
    azflags = [1 for i in range(num_dirpoints - 1)]
    azflags += [2]
    all_azflags = []

    elflags = [0 for i in range(num_dirpoints)]
    all_elflags = []

    for n in range(ntimes):
        # print(str(n)+' '+str(sect_start_time))
        end_dir_time = sect_start_time + tot_time_dir
        time_for_section = np.linspace(sect_start_time, end_dir_time,
                                       num_dirpoints)
        if n % 2 != 0:
            new_az = np.linspace(azpts[1], azpts[0], num_dirpoints)
            new_va = np.zeros(num_dirpoints) + \
                np.sign(azpts[0] - azpts[1]) * azvel
        else:
            new_az = np.linspace(azpts[0], azpts[1], num_dirpoints)
            new_va = np.zeros(num_dirpoints) + \
                np.sign(azpts[1] - azpts[0]) * azvel

        conctimes.extend(time_for_section)
        concaz.extend(new_az)
        concel.extend(el1)
        concva.extend(new_va)
        concve.extend(ve1)
        all_azflags.extend(azflags)
        all_elflags.extend(elflags)
        sect_start_time = time_for_section[-1] + turn_time

    all_azflags[-1] = 0

    return conctimes, concaz, concel, concva, concve, all_azflags, \
        all_elflags


def from_file(filename):
    """
    Produces properly formatted lists of times, azimuth and elevation
    locations, azimuth and elevation velocities, and azimuth and elevation
    motion flags for a finitely long scan from a numpy file. Numpy file
    must be formatted as an array of arrays in the order [times, azimuths,
    elevations, azimuth velocities, elevation velocities]

    Parameters:
        filename (str): Full path to the numpy file containing scan
            parameter array

    Returns:
        tuple of lists: (times, azimuths, elevations, azimuth velocities,
        elevation velocities, azimuth flags, elevation flags)

    NOTE: Flags can be set in the numpy file (0=unspecified, 1=constant
    velocity, 2=last point before turnaround). If flags are not set in
    the file, all flags are set to 0 to accommodate non-linear scans
    """
    info = np.load(filename)
    if len(info) not in [5, 7]:
        raise ValueError(f'Unexpected field count ({len(info)}) in {filename}')
    conctimes = info[0]
    concaz = info[1]
    concel = info[2]
    concva = info[3]
    concve = info[4]
    if len(info) == 5:
        az_flags = np.zeros(len(conctimes), int)
        el_flags = az_flags
    elif len(info) == 7:
        az_flags = info[5].astype('int')
        el_flags = info[6].astype('int')
    return conctimes, concaz, concel, concva, concve, az_flags, el_flags


def ptstack_format(conctimes, concaz, concel, concva, concve, az_flags,
                   el_flags, group_flag=None, start_offset=0, absolute=False):
    """Produces a list of lines in the format necessary to upload to the ACU
    to complete a scan. Params are the outputs of from_file,
    constant_velocity_scanpoints, or generate_constant_velocity_scan.

    Parameters:
        conctimes (list): Times starting at 0 for the ACU to reach
            associated positions
        concaz (list): Azimuth positions associated with conctimes
        concel (list): Elevation positions associated with conctimes
        concva (list): Azimuth velocities associated with conctimes
        concve (list): Elevation velocities associated with conctimes
        az_flags (list): Flags associated with azimuth motions at
            conctimes
        el_flags (list): Flags associated with elevation motions at
            conctimes
        group_flag (list): If not None, must be a list drawn from [0,
            1] where 1 indicates that the point should not be uploaded
            unless the subsequent point is also immediately uploaded.
        start_offset (float): Offset, in seconds, to apply to all
            timestamps.
        absolute (bool): If true, timestamps are taken at face value,
            and only start_offset is added.  If false, then the current
            time is also added (but note that if the first timestamp
            is 0, then you will need to also pass start_offset > 0).

    Returns:
        list: Lines in the correct format to upload to the ACU.  If
        group_flag was included, then each upload line is returned as
        a tuple (group_flag, line_text).

    """

    fmt = '%j, %H:%M:%S'
    if not absolute:
        start_offset = time.time() + start_offset
    true_times = [start_offset + i for i in conctimes]
    fmt_times = [time.strftime(fmt, time.gmtime(t))
                 + ('{tt:.6f}'.format(tt=t % 1.))[1:] for t in true_times]

    all_lines = [('{ftime}; {az:.6f}; {el:.6f}; {azvel:.4f}; '
                  '{elvel:.4f}; {azflag}; {elflag}'
                  '\r\n'.format(ftime=fmt_times[n], az=concaz[n],
                                el=concel[n], azvel=concva[n], elvel=concve[n],
                                azflag=az_flags[n], elflag=el_flags[n]))
                 for n in range(len(fmt_times))]

    if group_flag is not None:
        all_lines = [(i, line) for i, line in zip(group_flag, all_lines)]

    return all_lines


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
                                    ptstack_fmt=True):
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
        ptstack_fmt (bool): determine whether values are produced with the
            necessary format to upload to the ACU. If False, this function will
            produce lists of time, azimuth, elevation, azimuth velocity,
            elevation velocity, azimuth flags, and elevation flags. Default is
            True.

    """
    def get_target_az(current_az, current_t, increasing):
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

    target_az = get_target_az(az, t, increasing)
    point_group_batch = 0

    i = 0
    while i < stop_iter and check_num_scans():
        i += 1
        point_block = [[], [], [], [], [], [], [], []]
        for j in range(batch_size):
            point_block[0].append(t + t0)
            point_block[1].append(az)
            point_block[2].append(el)
            point_block[3].append(az_vel)
            point_block[4].append(el_vel)
            point_block[5].append(az_flag)
            point_block[6].append(el_flag)
            point_block[7].append(int(point_group_batch > 0))

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
                    t += turntime
                    az_vel = -1 * az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = False
                    target_az = get_target_az(az, t, increasing)
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
                    t += turntime
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = True
                    target_az = get_target_az(az, t, increasing)
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
                point_block[3][-1] = 0
                point_block[4][-1] = 0
                break

        if ptstack_fmt:
            yield ptstack_format(point_block[0], point_block[1],
                                 point_block[2], point_block[3],
                                 point_block[4], point_block[5],
                                 point_block[6], point_block[7],
                                 start_offset=3, absolute=True)
        else:
            yield tuple(point_block)


def plan_scan(az_end1, az_end2, el, v_az=1, a_az=1, az_start=None):
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
