"""
Interface to HWPSupervisor.

"""

import time
from dataclasses import dataclass, field

from ocs import client_http, ocs_client, site_config

# Helper functions for dealing with el ranges.


def range_intersect(a, b):
    rg = max(a[0], b[0]), min(a[1], b[1])
    return (rg[0], max(rg))


def range_contains(a, b):
    # true if "a contains b" i.e. if b is a subset of a
    return a[0] <= b[0] and a[1] >= b[1]


def range_merge(a, b):
    if a[0] > b[0]:
        return range_merge(b, a)
    if a[1] >= b[0]:
        return [(a[0], max(b[1], a[1]))]
    return [a, b]


def join_ranges(*a):
    """
    Combine and order a set of intervals, to form  into a
    """
    reduced = sorted([tuple(_a) for _a in a])
    i0 = 1
    while i0 < len(reduced):
        j = range_merge(reduced[i0 - 1], reduced[i0])
        if len(j) == 1:
            reduced[i0 - 1] = j[0]
            reduced.pop(i0)
        else:
            i0 += 1
    return reduced


AXIS_NAMES = ['el', 'az', 'third']


@dataclass
class StateRule:
    """Attributes:

    el_range: tuple giving the elevation range to which this rule
    applies.

    grip_states: list of "gripped" states to which this rule applies.

    spin_states: list of "spinning" states to which this rule applies.

    allow_moves: dict indicating whether motion is granted on each
      axis.

    """
    el_range: tuple
    grip_states: list
    spin_states: list
    allow_moves: dict

    def test(self, el, grip_state, spin_state):
        """Return bool indicating whether this rule matches the state
        specified in the arguments.

        """
        if el < self.el_range[0] or el > self.el_range[1]:
            return False
        if grip_state not in self.grip_states and '*' not in self.grip_states:
            return False
        if spin_state not in self.spin_states and '*' not in self.spin_states:
            return False
        return True


@dataclass
class MotionRules:
    """Attributes:

      rules: list of move StateRule, each of which grants move privs
        on some axis based on elevation range and HWP state.

      tolerance: amount of leeway in el (deg) to grant when checking
        rules.

    """
    tolerance: float = 0
    rules: list = field(default_factory=list)

    def test_range(self, el_range, grip_state, spin_state, full_output=False):
        """Determine what motion types are permitted, given the
        current HWP state and the elevation (range) of the planned
        motion.

        Args:
          el_range (tuple[float]):
            The starting and ending elevations of the move.
          grip_state (str):
            The HWP gripper state.
          spin_state (str):
            The HWP spinning state.
          full_output (bool):
            Controls detail level of output.

        When full_output=True, the returned structure looks like
        something like this::

          {'el': {'ok': True,
                  'allowed_el': [(30, 70)]},
           'az': {'ok': True,
                  'allowed_el': [(30, 70)]},
           'third': {'ok': False,
                  'allowed_third': [(30, 50), (60, 70])},
          }

        When full_output=False, the detailed per-axis results are
        replaced with just the boolean value of 'ok'; i.e.::

          {'el': True,
           'az': True,
           'third': False}

        """
        allow_moves = {k: [] for k in AXIS_NAMES}
        for rule in self.rules:
            if not rule.test(rule.el_range[0], grip_state, spin_state):
                continue
            # For each axis move that is allowed, add the el range
            # into the allow_moves entry.
            for k, el_ranges in allow_moves.items():
                if rule.allow_moves[k]:
                    el_ranges.append(rule.el_range)
        final_answer = {}
        for k, el_ranges in allow_moves.items():
            # intersect with target.
            el_ranges1 = [range_intersect(el_range, e) for e in el_ranges]
            # join -- if this isn't a single contiguous interval, then no go.
            el_ranges2 = join_ranges(*el_ranges1)
            ok = len(el_ranges2) == 1 and range_contains(el_ranges2[0], el_range)
            if full_output:
                final_answer[k] = {
                    'ok': ok,
                    'allowed_el': el_ranges2,
                }
            else:
                final_answer[k] = ok
        return final_answer


def parse_config(cfg):
    mo_rules = MotionRules()
    mo_rules.tolerance = cfg['tolerance']
    for rule in cfg.get('rules', []):
        mo_rules.rules.append(StateRule(**rule))
    return mo_rules


class HWPSupervisorClient:
    def __init__(self, instance_id):
        self.instance_id = instance_id
        self.cclient = site_config.get_control_client(instance_id)

    def update(self):
        ok, err_msg = False, ''
        hs, acu = {}, {}
        try:
            _, _, session = ocs_client.OCSReply(*self.cclient.request('status', 'monitor'))
            if session is not None:
                hs = session.data.get('hwp_state', {})
                acu = session.data.get('acu', {})
                ok = True
        except client_http.ControlClientError as e:
            err_msg = f'Error getting status: {e}'
        except Exception as e:
            err_msg = f'Surprising error: {e}'

        return {
            'timestamp': time.time(),
            'ok': ok,
            'err_mesg': err_msg,
            'gripper': hs.get('gripper'),
            'is_spinning': hs.get('is_spinning'),
            'request_block_motion': acu.get('request_block_motion'),
            'request_block_motion_timestamp': acu.get('request_block_motion_timestamp'),
        }
