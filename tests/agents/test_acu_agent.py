import numpy as np

from socs.agents.acu import avoidance as av
from socs.agents.acu import drivers, hwp_iface
from socs.agents.acu.agent import ACUAgent  # noqa: F401

HWP_IFACE_TEST_CONFIG = {
    'enabled': True,
    'tolerance': 0.1,
    'instance_id': 'hwp-super1',
    'limit_sun_avoidance': False,
    'rules': [
        {
            'el_range': [18, 90],
            'grip_states': ['cold', 'warm'],
            'spin_states': ['*'],
            'allow_moves': {
                'el': True,
                'az': True,
                'third': False,
            },
        },
        {
            'el_range': [40, 90],
            'grip_states': ['ungripped'],
            'spin_states': ['not_spinning'],
            'allow_moves': {
                'el': True,
                'az': True,
                'third': False,
            },
        },
        {
            'el_range': [48, 60],
            'grip_states': ['ungripped'],
            'spin_states': ['not_spinning'],
            'allow_moves': {
                'el': True,
                'az': True,
                'third': True,
            },
        },
        {
            'el_range': [48, 60],
            'grip_states': ['ungripped'],
            'spin_states': ['spinning'],
            'allow_moves': {
                'el': True,
                'az': True,
                'third': False,
            },
        },
    ]
}


#
# Sun avoidance
#

def get_sun(t0, az, el, **kwargs):
    # Get a SunTracker at time t0 and confirm the sun is close to
    # requested (az, el) at that time.  Returns (t0, az_sun, el_sun,
    # sun).
    sun = av.SunTracker(fake_now=t0, policy=kwargs)
    pos = sun.get_sun_pos()
    az0, el0 = pos['sun_azel']
    assert abs(az - az0) < .5 and abs(el - el0) < .5
    return t0, az0, el0, sun


def test_avoidance_support():
    t0 = 1698850000
    sun = av.SunTracker(fake_now=t0)

    # Scalar rebranch
    az, el, inv = sun._horizon_branch(0, 90)
    assert abs(el - 90) < .001
    assert not inv
    az, el, inv = sun._horizon_branch(0, 110)
    assert abs(el - 70) < .001
    assert inv

    # Vector rebranch
    az, el, inv = sun._horizon_branch(
        np.array([0, 30, 90, -110, 420]),
        np.array([-20, 80, 90, 170, 190]))
    assert np.allclose(el, np.array([-20, 80, 90, 10, -10]))
    assert np.all(inv == np.array([False, False, False, True, True]))


def test_avoidance_basics():
    t0, az0, el0, sun = get_sun(1698850000, 72, 67, max_el=180.)

    # Zenith should be about 23 deg away.
    assert abs(sun.get_sun_pos(0, 90)['sun_dist'] - 23) < 0.5

    # Unsafe positions.
    assert sun.check_trajectory([90], [60])['sun_time'] == 0

    # Upsidedown (el > 90)
    assert sun.check_trajectory([270], [120])['sun_time'] == 0

    # Safe positions
    assert sun.check_trajectory([90], [20])['sun_time'] > 0
    assert sun.check_trajectory([270], [60])['sun_time'] > 0
    assert sun.check_trajectory([72], [170])['sun_time'] > 0

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

    paths = sun.analyze_paths(70, 120, 70, 120)
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

    # Including from upsidedown.
    az1, el1 = az0 + 180, 180 - el0
    assert (el1 > 90)
    path = sun.find_escape_paths(az1, el1 - 5)
    assert path is not None
    path = sun.find_escape_paths(az1, el1 + 5)
    assert path is not None
    path = sun.find_escape_paths(az1 - 10, el1)
    assert path is not None
    path = sun.find_escape_paths(az1 + 10, el1)
    assert path is not None


def test_avoidance_night():
    # Check correct behavior when sun is below horizon.
    t0, az0, el0, sun = get_sun(1750142000, 83, -62,
                                min_el=-90.)

    # It is safe to point at the Sun, if the earth is in the way
    info = sun.check_trajectory([az0], [el0])
    assert info['sun_dist_min'] < 1.
    assert info['sun_time'] > 12 * 3600

    # Find safe paths
    paths = sun.analyze_paths(az0 - 50, el0, az0 + 50, el0)
    path, analysis = sun.select_move(paths)
    assert path is not None
    assert len(path['moves'].nodes) == 2

    # Escape paths.
    path = sun.find_escape_paths(az0, el0 - 5)
    assert path is not None
    path = sun.find_escape_paths(az0, el0 + 5)
    assert path is not None
    path = sun.find_escape_paths(az0 - 10, el0)
    assert path is not None
    path = sun.find_escape_paths(az0 + 10, el0)
    assert path is not None


def test_avoidance_zenith():
    # Check behavior when Sun near zenith.
    t0, az0, el0, sun = get_sun(
        1702311400, 91.8, 87.9)

    # Zenith should be about 2 deg away.
    assert abs(sun.get_sun_pos(0, 90)['sun_dist'] - 2) < 0.5

    for az in np.arange(0, 360, 30):
        # Unsafe positions.
        assert sun.check_trajectory([az], [90])['sun_time'] == 0
        # Safe positions
        assert sun.check_trajectory([az], [0])['sun_time'] > 0
        assert sun.check_trajectory([az], [180])['sun_time'] > 0

    # Find safe paths
    paths = sun.analyze_paths(0, 30, 270, 40)
    path, analysis = sun.select_move(paths)
    assert path is not None
    assert len(path['moves'].nodes) > 1

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

    # A similar point, but now check that extended el branch scopes
    # can find paths effectively.
    t0, az0, el0, sun = get_sun(
        1702312400, 268, 87.9, max_el=180)

    path = sun.find_escape_paths(az0, el0 - 5)
    assert path is not None
    path = sun.find_escape_paths(az0, el0 + 5)
    assert path is not None
    path = sun.find_escape_paths(az0 - 10, el0)
    assert path is not None
    path = sun.find_escape_paths(az0 + 10, el0)
    assert path is not None


def test_avoidance_sunrise():
    # Check behavior when Sun near horizon, rising.
    # Just after sunrise
    t0, az0, el0, sun = get_sun(1750159200, 64, 0.9)

    info = sun.check_trajectory([az0], [1.])
    assert info['sun_dist_min'] < 10
    assert info['sun_time'] == 0

    # Just before sunrise
    t0, az0, el0, sun = get_sun(1750158000, 66, -3)

    info = sun.check_trajectory([az0], [1.])
    assert info['sun_dist_min'] < 10

    # Even though Sun distance is within exclusion radius, sun_time
    # should be positive (though not very big).
    assert info['sun_time'] > 0
    assert info['sun_time'] < abs(el0) * 3600 / 15 * 2


def test_avoidance_sunset():
    # Check behavior when Sun near horizon, setting.
    # Just before sunset
    t0, az0, el0, sun = get_sun(1750110000, 297, 2.2)

    info = sun.check_trajectory([az0], [1.])
    assert info['sun_dist_min'] < 10
    assert info['sun_time'] == 0

    # Just after sunset
    t0, az0, el0, sun = get_sun(1750110900, 295, -0.8)

    # Even though Sun distance is within exclusion radius, sun_time
    # should be positive -- well over 12 hours, closer to 24.
    info = sun.check_trajectory([az0], [1.])
    assert info['sun_dist_min'] < 10
    assert info['sun_time'] > 16 * 3600


def test_tracks():
    # Basic function testing.
    g = drivers.generate_constant_velocity_scan(
        60, 80, 1, 1, 50, 50,
        start_time=1800000000)
    points = next(iter(g))
    drivers.get_track_points_text(points, text_block=True,
                                  timestamp_offset=3)


#
# HWP interface system
#

def test_hwp_iface_ranges_math():
    misc = [
        (10, 20), (30, 40), (20, 25), (-10, 11)
    ]
    assert hwp_iface._simplify_ranges(*misc) == [(-10, 25), (30, 40)]
    for a, b, result in [
            ((0, 10), (11, 20), False),
            ((0, 10), (1, 1), True),
            ((0, 10), (2, 10), True),
            ((0, 10), (-1, 4), False),
            ((0, 10), (8, 11), False),
    ]:
        assert hwp_iface._range_contains(a, b) == result


def _gen_rules(*args):
    def listify(x):
        return [x] if isinstance(x, str) else x
    rules = []
    for el0, el1, grip, spin, el, az, th in args:
        rules.append({
            'el_range': [el0, el1],
            'grip_states': listify(grip),
            'spin_states': listify(spin),
            'allow_moves': {
                'el': el,
                'az': az,
                'third': th,
            }})
    return {'tolerance': .1,
            'rules': rules}


def test_hwp_iface_parse_config():
    # Test parsing of a full config dict ...
    hwp_iface.HWPInterlocks.from_dict(HWP_IFACE_TEST_CONFIG)


def test_hwp_iface_rule_eval():
    # Test range combination rules.
    def ex(d, item=0):
        return tuple([d[k][item] for k in ['el', 'az', 'third']])

    mo_rules = hwp_iface.HWPInterlocks.from_dict(_gen_rules(
        (40, 70, 'gripped', 'not_spinning', True, False, False),
        (50, 60, 'ungripped', 'not_spinning', False, True, True),
        (55, 62, 'ungripped', 'spinning', True, True, False),
    ))

    ruling = mo_rules.test_range(None, 'gripped', 'not_spinning')
    assert ex(ruling, 2) == ([(40, 70)], [], [])

    ruling = mo_rules.test_range([40, 50], 'gripped', 'not_spinning')
    assert ex(ruling) == (True, False, False)

    ruling = mo_rules.test_range([45, 51], 'gripped', 'not_spinning')
    assert ex(ruling) == (True, False, False)

    ruling = mo_rules.test_range([45, 51], 'ungripped', 'not_spinning')
    assert ex(ruling) == (False, False, False)

    ruling = mo_rules.test_range([51, 45], 'ungripped', 'not_spinning')
    assert ex(ruling) == (False, False, False)

    ruling = mo_rules.test_range([51, 52], 'ungripped', 'not_spinning')
    assert ex(ruling) == (False, True, True)

    ruling = mo_rules.test_range([30, 41], 'gripped', 'not_spinning')
    assert ex(ruling) == (False, False, False)
