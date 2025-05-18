"""
Interface to HWPSupervisor.

"""

import time
from dataclasses import asdict, dataclass, field

from ocs import client_http, ocs_client, site_config

# Helper functions for dealing with el ranges.


def _range_contains(a, b):
    # true if "a contains b" i.e. if b is a subset of a
    return a[0] <= b[0] and a[1] >= b[1]


def _simplify_ranges(*a):
    """Combine and order a set of intervals, to form an ordered,
    non-abutting list of intervals.

    """
    reduced = sorted([tuple(_a) for _a in a])
    i0 = 1
    while i0 < len(reduced):
        a, b = reduced[i0 - 1], reduced[i0]
        if a[1] >= b[0]:
            reduced[i0 - 1] = (a[0], max(b[1], a[1]))
            reduced.pop(i0)
        else:
            i0 += 1
    return reduced


AXIS_NAMES = ['el', 'az', 'third']


@dataclass
class MotionRule:
    #: Tuple giving the elevation range to which this rule applies.
    el_range: tuple

    #: List of grip_state values to which this rule applies. Note "*"
    #: matches any grip_state.
    grip_states: list

    #: List of spin_state values to which this rule applies. Note "*"
    #: matches any spin_state.
    spin_states: list

    #: Dict mapping each axis to a bool that indicates whether moves in
    #: that axis are permitted.
    allow_moves: dict

    def test_hwp(self, grip_state, spin_state):
        """Returns True only if grip_state and spin_state args are
        matched by this rule.

        """
        if grip_state not in self.grip_states and '*' not in self.grip_states:
            return False
        if spin_state not in self.spin_states and '*' not in self.spin_states:
            return False
        return True


@dataclass
class HWPInterlocks:
    #: bool indicating whether the config is valid (and thus eligible
    #: to be enabled).
    configured: bool = False

    #: bool indicating whether to bother with HWP interlocks.
    enabled: bool = False

    #: instance_id of HWPSupervisor agent to query.
    instance_id: str = 'hwp-supervisor'

    #: amount of leeway in el (deg) to grant when checking rules.
    tolerance: float = 0.1

    #: whether HWP state-based elevation limits should be applied to
    #: Sun avoidance escape movements
    limit_sun_avoidance: bool = True

    #: rules: list of MotionRule objects, each of which grants move
    #: privs on some axis based on elevation range and HWP state.
    rules: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, cfg):
        if cfg is None:
            return cls()
        self = cls(configured=True, **cfg)
        self.rules = [MotionRule(**rule) for rule in self.rules]
        return self

    def encoded(self, basic=False):
        d = asdict(self)
        if basic:
            d.pop('rules')
        return d

    def get_client(self):
        return HWPSupervisorClient(self.instance_id)

    def test_range(self, el_range, grip_state, spin_state):
        """Determine what motion types are permitted, given the
        current HWP state and the elevation (range) of the planned
        motion.

        Args:
          el_range (tuple[float] or None):
            The starting and ending elevations of the move.
          grip_state (str):
            The HWP gripper state.
          spin_state (str):
            The HWP spinning state.

        The rules are evaluated in the context of grip_state and
        spin_state, to obtain the ranges of els over which moves in
        each axis is permitted.  Then the el_range, if provided is
        tested against those ranges.

        E.g for a call like::

          test_range((40, 40), 'ungripped', 'not_spinning')

        the returned structure looks like this::

          {'el': (True, (30, 70), [(30, 70)]),
           'az': (True, (30, 70), [(30, 70)]),
           'third': (False, None, [(30, 50), (60, 70)]),
          }

        I.e. for each axis, a tuple is returned where the third value
        is the full list of permitted elevation ranges for this state;
        the first value is whether the requested el_range,
        specifically, overlaps with the elevation ranges, and the
        second value is the particular range that overlaps with
        requested el_range (or None if not the case).

        """
        allow_moves = {k: [None, None, []] for k in AXIS_NAMES}
        for rule in self.rules:
            if not rule.test_hwp(grip_state, spin_state):
                continue
            # For each axis move that is allowed, add the el range
            # into the allow_moves entry.
            for k, (_, _, el_ranges) in allow_moves.items():
                if rule.allow_moves[k]:
                    el_ranges.append(rule.el_range)
        for k in allow_moves:
            allow_moves[k][2] = _simplify_ranges(*allow_moves[k][2])
        if el_range is not None:
            el_range = [min(el_range), max(el_range)]
            for k in allow_moves.keys():
                allow_moves[k][0] = False
                for _e in allow_moves[k][2]:
                    if _range_contains(_e, el_range):
                        allow_moves[k][0] = True
                        allow_moves[k][1] = _e
        return {k: tuple(v) for k, v in allow_moves.items()}


class HWPSupervisorClient:
    """OCSClient wrapper to query and interpret the state of the
    HWPSupervisor.  Instantiate with the instance_id of the
    HWPSupervisor to be monitored.

    """

    def __init__(self, instance_id):
        self.instance_id = instance_id
        self.cclient = site_config.get_control_client(instance_id)

    def update(self):
        """Analyze HWPSupervisor state info and make determinations
        about hwp state.  Returns a dict with the results.

        When everything works well, the useful results in the dict are:

        - ``timestamp``: current time
        - ``ok``: True if state determination went reasonably well
        - ``err_msg``: populated if not ok.
        - ``grip_state``: one of "unknown", "cold", "warm", "ungripped"
        - ``spin_state``: one of "unknown", "spinning", "not_spinning"

        The following raw data from monitor process are copied into
        the output dict::

          hwp_state:
            is_spinning       -> _is_spinning
            pid_target_freq   -> _target_freq
            gripper:
              grip_state      -> _grip_state
              brake           -> _grip_brakes
          acu:
            request_block_motion             -> request_block_motion
            request_block_motion_timestamp   -> request_block_motion_timestamp

        """
        ok, err_msg = False, ''
        hs, acu = {}, {}
        try:
            _, _, session = ocs_client.OCSReply(*self.cclient.request('status', 'monitor'))
            if session is not None:
                hs = session['data'].get('hwp_state', {})
                acu = session['data'].get('acu', {})
                ok = True
        except client_http.ControlClientError as e:
            err_msg = f'Error getting status: {e}'
        except Exception as e:
            err_msg = f'Surprising error: {e}'

        # Enhanced spin state logic...
        is_spinning = hs.get('is_spinning')  # bool or None
        target_freq = hs.get('pid_target_freq')  # float or None I guess
        if is_spinning or target_freq not in [None, 0]:
            spin_state = 'spinning'
        elif is_spinning is False and target_freq in [0.]:
            spin_state = 'not_spinning'
        else:
            spin_state = 'unknown'

        # Enhanced gripper state logic...
        _grip_state = hs.get('gripper', {}).get('grip_state')
        brakes = hs.get('gripper', {}).get('brake')  # 1 1 1 when stable
        brakes_on = False
        try:
            brakes_on = len(brakes) and all(brakes)
        except BaseException:
            pass
        if _grip_state is not None and brakes_on:
            grip_state = _grip_state
        else:
            grip_state = 'unknown'

        return {
            'timestamp': time.time(),
            'ok': ok,
            'err_msg': err_msg,
            'grip_state': grip_state,
            'spin_state': spin_state,
            '_grip_brakes': brakes,
            '_grip_state': _grip_state,
            '_is_spinning': is_spinning,
            '_target_freq': target_freq,
            'request_block_motion': acu.get('request_block_motion'),
            'request_block_motion_timestamp': acu.get('request_block_motion_timestamp'),
        }
