import numpy as np


def gen_3leg_turnaround(t0, az0, el0, v0, turntime, az_flag, el_flag, point_group_batch,
                        second_leg_time=None, second_leg_velocity=0, step_time=0.1):
    from .drivers import TrackPoint
    """
    Generates the trajectory of a 3part turnaround given the initial position and velocity of the platform.
    This function generates a turnaround in three "legs":

        1. The initial deceleration.
        2. The middle leg with a low velocity/acceleration to gently turn the gears of the motors around so
           they contact the other face of the bearing with minimal force. The default velocity and acceleration
           is 0 so the platform comes to a full stop in this leg by a default.
        3. The final acceleration to the scan velocity in the opposite direction.

    The turnaround time of this function adheres to the same equation as the "baseline" turnaround function:

        turntime = (2.0 * scan_velocity) / scan_acceleration

    Thus, for the same scan velocity and scan acceleration this turnaround will take the same time as the baseline.

    Args:
        t0 (float): The initial time of the turnaround.
        az0 (float): The iniital azimuth position of the turnaround. Should be equal to the final azimuth position of the turnaround.
        el0 (float): The initial elevation of the turnaround. El velocity is forced to 0 here so this is only used for creating TrackPoints.
        v0 (float): The initial azimuth velocity of the turnaround.
        turntime (float): The turnaround time given by the above equation.
        az_flag (int): The az flag used by the ACU. Inherited from the scan generation function and not changed. Used for TrackPoints.
        el_flag (int): The el flag used by the ACU. Inherited from the scan generation function and not changed. Used for TrackPoints.
        point_group_batch (int): the point group batch used by the ACU. Inherited from the scan generation function and not changed. Used for TrackPoints.
        second_leg_time (float): The time used by the second leg of the turnaround. Defaults to 1 second.
                               This limits the minimum turnaround time to ~2.0 seconds!
        second_leg_velocity (float): The velocity targeted by the beginning/end of the second leg of the turnaround. Defaults to 0 deg/s.
                                   second_leg acceleration = 2.0 * second_leg_velocity / second_leg_time.
        step_time (float): The step time between points in the turnaround. Defaults to 0.1 seconds (10Hz).
    """

    # Enforce 0 el velocity. Can be changed later if these want to be used with type2 or type3 LAT scans,
    # but more work is necessary to get to that point. We shouldn't mix the two yet!
    el_vel = 0.

    if second_leg_time is None:
        second_leg_time = turntime / 3.0  # Cut the turnaround into equal thirds unless otherwise specified.
    second_leg_acceleration = 2.0 * second_leg_velocity / second_leg_time

    # Assert we have at least 0.5 seconds for the first and second legs of the turnaround!
    # This limits the turntime to >= 1.5 seconds
    assert (turntime - second_leg_time) >= 1.0, \
        "Time for the second leg of the turnaround is too long! The time remaining for the first and third legs is < 1.0 seconds!"

    # Solve for the first leg of the turnaround
    t_start_1 = 0  # We have to solve the trajectory around 0 or the linear equations become very large. Add t back on later
    t_target_1 = t_start_1 + (turntime - second_leg_time) / 2  # The first and third legs share the same portion of the turnaround time.
    az_start_1 = az0
    v_start_1 = v0
    v_target_1 = second_leg_velocity * np.sign(v_start_1)
    a_start_1 = 0
    a_target_1 = second_leg_acceleration * -1 * np.sign(v0)
    j_start_1 = 0  # We always target a jerk of 0 at the beginning and end of turnaround legs.
    j_target_1 = 0
    ts_1, azs_1, vs_1 = _gen_trajectory(t_start_1, t_target_1, az_start_1,
                                        v_start_1, v_target_1, a_start_1,
                                        a_target_1, j_start_1, j_target_1,
                                        step_time)

    # Solve for the second leg of the turnaround
    t_start_2 = t_target_1
    t_target_2 = t_start_2 + second_leg_time
    az_start_2 = azs_1[-1]  # The acceleration of the beggining of the next turnaround leg should always match the end of the last leg.
    v_start_2 = v_target_1
    v_target_2 = v_start_2 * -1
    a_start_2 = a_target_1
    a_target_2 = a_start_2
    j_start_2 = 0
    j_target_2 = 0
    ts_2, azs_2, vs_2 = _gen_trajectory(t_start_2, t_target_2, az_start_2,
                                        v_start_2, v_target_2, a_start_2,
                                        a_target_2, j_start_2, j_target_2,
                                        step_time)

    # Solve for the third leg of the turnaround
    t_start_3 = t_target_2
    t_target_3 = t_start_3 + (turntime - second_leg_time) / 2.0
    az_start_3 = azs_2[-1]
    v_start_3 = v_target_2
    v_target_3 = v0 * -1
    a_start_3 = a_target_2
    a_target_3 = 0
    j_start_3 = 0
    j_target_3 = 0
    ts_3, azs_3, vs_3 = _gen_trajectory(t_start_3, t_target_3, az_start_3,
                                        v_start_3, v_target_3, a_start_3,
                                        a_target_3, j_start_3, j_target_3,
                                        step_time)

    # Concatenate the times, azimuth positions, and azimuth velocities together.
    # The first point of each leg is a duplicate of the last so we drop those points.
    ts = np.concatenate([ts_1[1:], ts_2[1:], ts_3[1:]]) + t0
    azs = np.concatenate([azs_1[1:], azs_2[1:], azs_3[1:]])
    vs = np.concatenate([vs_1[1:], vs_2[1:], vs_3[1:]])

    # Turn our turnaround solution into TrackPoint's for the ACU.
    turnaround_track = []
    for t, az, v in zip(ts, azs, vs):
        turnaround_track.append(TrackPoint(timestamp=t,
                                az=az, el=el0, az_vel=v, el_vel=el_vel,
                                az_flag=az_flag, el_flag=el_flag,
                                group_flag=int(point_group_batch > 0)))

    return turnaround_track


def _gen_trajectory(t_i, t_f, xn1_i, x0_i, x0_f, x1_i, x1_f, x2_i, x2_f, step_time):
    """
    Generally, generates the trajectory that minimizes the third derivative of the parameter defined by x0.

    In the context of this module, this function is used to generate the legs of the 3part turnaround in a way that
    minimizes the snap of the motion. Because we don't know the final positions of each of the legs we must
    generate the trajectories using the initial and final velocity, acceleration, and jerk, which minimizes the snap.

    In this context, x0 is the function of velocity, x1 is acceleration, x2 is jerk, and xn1 is position.

    Args:
        t_i (float): The initial time of the trajectory.
        t_f (float): The final time of the trajectory.
        xn1_i (float): The initial position.
        x0_i (float): The initial velocity.
        x0_f (float): The final velocity.
        x1_i (float): The initial acceleration.
        x1_f (float): The final acceleration.
        x2_i (float): The initial jerk.
        x2_f (float): The final jerk.

    Returns:
        ts (float array): A numpy array of timestamps.
        xs (float array): A numpy array of azimuth positions.
        vs (float array): A numpy array of azimuth velocities.
    """

    # Solve for the polynomial components that fits our initial and final conditions
    A = solve_fifth_polynomial_lin_eqs(t_i, t_f, x0_i, x0_f, x1_i, x1_f, x2_i, x2_f)

    ts = np.arange(t_i, t_f + step_time, step_time)  # Divide our times into points with step_time spacing
    vs = np.polyval(A[::-1], ts)

    xs = np.polyval(np.polyint(A[::-1]), ts)
    xs = xs - xs[0] + xn1_i  # Solve for the positions of each point

    return ts, xs, vs


# Linear Algebra Below
def solve_fifth_polynomial_lin_eqs(t_i, t_f, x0_i, x0_f, x1_i, x1_f, x2_i, x2_f):
    """
    Solves for the components of a polynomial equation of order five the form:

        x0 = A0 + A1*x + A2*x^2 + A3*x^3 + A4*x^4 + A5*a^5,

    given the initial/final conditions of the 0th, 1st, and 2nd derivatives.

    This solution minimizes the third derivative over the trajectory between t_i and t_f.

    Args:
        t_i (float): starting time
        t_f (float): stop time
        x0_i (float): initial 0th derivative condition
        x0_f (float): final 0th derivative condition
        x1_i (float): initial 1st derivative condition
        x1_f (float): final 1st derivative condition
        x2_i (float): initial 2nd derivative condition
        x2_f (float): initial 2nd derivative condition

    Returns:
        A0 (float): The solved 0th parameter of the order five polynomial.
        A1 (float): The solved 1st parameter of the order five polynomial.
        A2 (float): The solved 2nd parameter of the order five polynomial.
        A3 (float): The solved 3rd parameter of the order five polynomial.
        A4 (float): The solved 4th parameter of the order five polynomial.
        A5 (float): The solved 5th parameter of the order five polynomial.
    """

    x0 = [1, 1, 1, 1, 1, 1]
    x1 = [0, 1, 2, 3, 4, 5]
    x2 = [0, 0, 2, 6, 12, 20]

    A = np.zeros((6, 6))
    for i, x in enumerate([x0, x1, x2]):
        for j, y in enumerate(x):
            if j < i:
                continue

            A[2 * i, j] = y * t_i**(j - i)
            A[2 * i + 1, j] = y * t_f**(j - i)

    B = np.zeros(6)
    B[0] = x0_i
    B[1] = x0_f
    B[2] = x1_i
    B[3] = x1_f
    B[4] = x2_i
    B[5] = x2_f

    return np.linalg.solve(A, B)
