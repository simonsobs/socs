from socs.agents.acu import avoidance as av
from socs.agents.acu import drivers
from socs.agents.acu.agent import ACUAgent  # noqa: F401


def test_avoidance():
    az0, el0 = 72, 67
    t0 = 1698850000

    sun = av.SunTracker(fake_now=t0)
    pos = sun.get_sun_pos()
    az, el = pos['sun_azel']
    assert abs(az - az0) < .5 and abs(el - el0) < .5

    # Zenith should be about 23 deg away.
    assert abs(sun.get_sun_pos(0, 90)['sun_dist'] - 23) < 0.5

    # Unsafe positions.
    assert sun.check_trajectory([90], [60])['sun_time'] == 0

    # Safe positions
    assert sun.check_trajectory([90], [20])['sun_time'] > 0
    assert sun.check_trajectory([270], [60])['sun_time'] > 0

    # Find safe paths
    paths = sun.analyze_paths(180, 30, 270, 40)
    path, analysis = sun.select_move(paths)
    assert path is not None
    assert len(path['moves'].nodes) > 1

    # Find safe short paths
    paths = sun.analyze_paths(270.01, 40.01, 270, 40)
    path, analysis = sun.select_move(paths)
    assert path is not None
    assert len(path['moves'].nodes) == 2

    # .. even if policy forbids mixed-axis moves
    sun.policy['axes_sequential'] = True
    paths = sun.analyze_paths(270.01, 40.01, 270, 40)
    path, analysis = sun.select_move(paths)
    assert path is not None
    assert len(path['moves'].nodes) == 3
    sun.policy['axes_sequential'] = False

    # Find safe paths to here (no moves)
    paths = sun.analyze_paths(270, 40, 270, 40)
    path, analysis = sun.select_move(paths)
    assert path is not None
    assert len(path['moves'].nodes) == 1

    # No safe moves to Sun position.
    paths = sun.analyze_paths(180, 20, az0, el0)
    path, analysis = sun.select_move(paths)
    assert path is None

    # Escape paths.
    path = sun.find_escape_paths(az0, el0 - 5)
    assert path is not None
    path = sun.find_escape_paths(az0, el0 + 5)
    assert path is not None
    path = sun.find_escape_paths(az0 - 10, el0)
    assert path is not None
    path = sun.find_escape_paths(az0 + 10, el0)
    assert path is not None


def test_tracks():
    # Basic function testing.
    g = drivers.generate_constant_velocity_scan(
        60, 80, 1, 1, 50, 50,
        start_time=1800000000)
    points = next(iter(g))
    drivers.get_track_points_text(points, text_block=True,
                                  timestamp_offset=3)
