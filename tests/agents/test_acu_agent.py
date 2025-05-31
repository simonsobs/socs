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
