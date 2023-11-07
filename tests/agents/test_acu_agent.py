from socs.agents.acu import avoidance as av
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
