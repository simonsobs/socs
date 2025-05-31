# Sun Avoidance
#
# The docstring below is intended for injection into the documentation
# system.

"""When considering Sun Safety of a boresight pointing, we consider an
exclusion zone around the Sun with a user-specified radius. This is
called the ``exclusion_radius`` or the field-of-view radius.

The Safety of the instrument at any given moment is parametrized
by two numbers:

  ``sun_dist``
    The separation between the Sun and the boresight (az, el), in
    degrees.

  ``sun_time``
    The minimum time, in seconds, which must elapse before the current
    (az, el) pointing of the boresight will lie within the exclusion
    radius of the Sun.

While the ``sun_dist`` is an important indicator of whether the
instrument is currently in immediate danger, the ``sun_time`` is
helpful with looking forward and avoiding positions that will soon be
dangerous.

The user-defined policy for Sun Safety is captured in the following
settings:

  ``exclusion_radius``
    The radius, in degres, of a disk centered on the Sun that must be
    avoided by the boresight.

  ``min_sun_time``
    An (az, el) position is considered unsafe (danger zone) if the
    ``sun_time`` is less than the ``min_sun_time``. (Expressed in
    seconds.)

  ``response_time``
    An (az, el) position is considered vulnerable (warning zone) if
    the ``sun_time`` is less than the ``response_time``. This is
    intended to represent the maximum amount of time it could take an
    operator to reach the instrument and secure it, were motion to
    stall unexpectedly. (Expressed in seconds.)

  ``el_horizon``
    The elevation (in degrees) below which the Sun may be considered
    as invisible to the instrument.

  ``el_dodging``
    This setting affects how point-to-point motions are executed, with
    respect to what elevations may be used in intermediate legs of the
    trajectory. When this is False, the platform is restricted to
    travel only at elevations that lie between the initial and the
    target elevation. When True, the platform is permitted to travel
    at other elevations, all the way up to the limits of the
    platform. Using True is helpful to find Sun-safe trajectories in
    some circumstances. But False is helpful if excess elevation
    changes are potentially disturbing to the cryogenics.  This
    setting only affects point-to-point motions; "escape" paths will
    always consider all available elevations.

  ``axes_sequential``
    If True, a point-to-point motion will only be accepted if each leg
    is a constant el or constant az move. When this setting is False,
    legs that move simultaneously in az and el are permitted (and
    probably preferred) as long as they are safe.


A "Sun-safe" position is a pointing of the boresight that currently
has a ``sun_time`` that meets or exceeds the ``min_sun_time``
parameter.

"""

import datetime
import math
import time

import ephem
import numpy as np
from pixell import enmap
from so3g.proj import coords, quat

try:
    import pylab as pl
except ModuleNotFoundError:
    pass

DEG = np.pi / 180

HOUR = 3600
DAY = 86400
NO_TIME = DAY * 2

#: Default policy to apply when evaluating Sun-safety and planning
#: trajectories.  Note the Agent code may apply different defaults,
#: based on known platform details.
DEFAULT_POLICY = {
    'exclusion_radius': 20,
    'min_el': 0,
    'max_el': 90,
    'min_az': -45,
    'max_az': 405,
    'el_horizon': 0,
    'el_dodging': False,
    'min_sun_time': HOUR,
    'response_time': HOUR * 4,
    'axes_sequential': False,
}


class SunTracker:
    """Provide guidance on what horizion coordinate positions and
    trajectories are sun-safe.

    Args:
      policy (dict): Exclusion policy parameters.  See module
        docstring, and DEFAULT_POLICY.  The policy should also include
        {min,max}\\_{el,az}, giving the limits supported by those axes.
      site (EarthlySite or None): Site to use; default is the SO LAT.
        If not None, pass an so3g.proj.EarthlySite or compatible.
      map_res (float, deg): resolution to use for the Sun Safety Map.
      sun_time_shift (float, seconds): For debugging and testing,
        compute the Sun's position as though it were this manys
        seconds in the future.  If None or zero, this feature is
        disabled.
      fake_now (float, seconds): For debugging and testing, replace
        the tracker's computation of the current time (time.time())
        with this value.  If None, this testing feature is disabled.
      compute (bool): If True, immediately compute the Sun Safety Map
        by calling .reset().
      base_time (unix timestamp): Store this base_time and, if compute
        is True, pass it to .reset().

    """

    def __init__(self, policy=None, site=None,
                 map_res=.5, sun_time_shift=None, fake_now=None,
                 compute=True, base_time=None):
        # Note res is stored in radians.
        self.res = map_res * DEG
        if sun_time_shift is None:
            sun_time_shift = 0.
        self.sun_time_shift = sun_time_shift
        self.fake_now = fake_now
        self.base_time = base_time

        # Process and store the instrument config and safety policy.
        if policy is None:
            policy = {}
        for k in policy.keys():
            assert k in DEFAULT_POLICY
        _p = dict(DEFAULT_POLICY)
        _p.update(policy)
        self.policy = _p

        if site is None:
            # This is close enough.
            site = coords.SITES['so_lat']
        site_eph = ephem.Observer()
        site_eph.lon = site.lon * DEG
        site_eph.lat = site.lat * DEG
        site_eph.elevation = site.elev
        self._site = site_eph

        if compute:
            self.reset(base_time)

    def _now(self):
        if self.fake_now:
            return self.fake_now
        return time.time()

    def _sun(self, t):
        self._site.date = \
            datetime.datetime.utcfromtimestamp(t + self.sun_time_shift)
        return ephem.Sun(self._site)

    def reset(self, base_time=None):
        """Compute and store the Sun Safety Map for a specific
        timestamp.

        This basic computation is required prior to calling other
        functions that use the Sun Safety Map.

        """
        # Set a reference time -- the map of sun times is usable from
        # this reference time to at least 12 hours in the future.
        if base_time is None:
            base_time = self._now()

        # Identify zenith (ra, dec) at base_time.
        Qz = coords.CelestialSightLine.naive_az_el(
            base_time, 180. * DEG, 90. * DEG).Q
        ra_z, dec_z, _ = quat.decompose_lonlat(Qz)

        # Map extends from dec -80 to +80.
        shape, wcs = enmap.band_geometry(
            dec_cut=80 * DEG, res=self.res, proj='car')

        # The map of sun time deltas
        sun_times = enmap.zeros(shape, wcs=wcs) - 1
        sun_dist = enmap.zeros(shape, wcs=wcs) - 1

        # Quaternion rotation for each point in the map.
        dec, ra = sun_times.posmap()
        map_q = quat.rotation_lonlat(ra.ravel(), dec.ravel())

        v = self._sun(base_time)

        # Get the map of angular distance to the Sun.
        qsun = quat.rotation_lonlat(v.ra, v.dec)
        sun_dist[:] = (quat.decompose_iso(~qsun * map_q)[0]
                       .reshape(sun_dist.shape) / coords.DEG)

        # Get the map where each pixel says the time delay between
        # base_time and when the time when the sky coordinate will be
        # in the Sun mask.
        dt = -ra[0] * DAY / (2 * np.pi)
        qsun = quat.rotation_lonlat(v.ra, v.dec)
        qoff = ~qsun * map_q
        r = quat.decompose_iso(qoff)[0].reshape(sun_times.shape) / DEG
        sun_times[r <= self.policy['exclusion_radius']] = 0.
        for g in sun_times:
            if (g < 0).all():
                continue
            # Identify pixel on the right of the masked region.
            flips = ((g == 0) * np.hstack((g[:-1] != g[1:], g[-1] != g[0]))).nonzero()[0]
            dt0 = dt[flips[0]]
            _dt = (dt - dt0) % DAY
            g[g < 0] = _dt[g < 0]

        # Fill in remaining -1 with NO_TIME.
        sun_times[sun_times < 0] = NO_TIME

        # Store the sun_times map and stuff.
        self.base_time = base_time
        self.sun_times = sun_times
        self.sun_dist = sun_dist
        self.map_q = map_q

    def _azel_pix(self, az, el, dt=0, round=True, segments=False):
        """Return the pixel indices of the Sun Safety Map that are
        hit by the trajectory (az, el) at time dt.

        Args:
          az (array of float, deg): Azimuth.
          el (array of float, deg): Elevation.
          dt (array of float, s): Time offset relative to the base
            time, at which to evaluate the trajectory.
          round (bool): If True, round results to integer (for easy
            look-up in the map).
          segments (bool): If True, split up the trajectory into
            segments (a list of pix_ji sections) such that they don't
            cross the map boundaries at any point.

        """
        az = np.asarray(az)
        el = np.asarray(el)
        qt = coords.CelestialSightLine.naive_az_el(
            self.base_time + dt, az * DEG, el * DEG).Q
        ra, dec, _ = quat.decompose_lonlat(qt)
        pix_ji = self.sun_times.sky2pix((dec, ra))
        if round:
            pix_ji = pix_ji.round().astype(int)
            # Handle out of bounds as follows:
            # - RA indices are mod-ed into range.
            # - dec indices are clamped to the map edge.
            j, i = pix_ji
            j[j < 0] = 0
            j[j >= self.sun_times.shape[-2]] = self.sun_times.shape[-2] - 1
            i[:] = i % self.sun_times.shape[-1]

        if segments:
            jumps = ((abs(np.diff(pix_ji[0])) > self.sun_times.shape[-2] / 2)
                     + (abs(np.diff(pix_ji[1])) > self.sun_times.shape[-1] / 2))
            jump = jumps.nonzero()[0]
            starts = np.hstack((0, jump + 1))
            stops = np.hstack((jump + 1, len(pix_ji[0])))
            return [pix_ji[:, a:b] for a, b in zip(starts, stops)]

        return pix_ji

    def check_trajectory(self, az, el, t=None, raw=False):
        """For a telescope trajectory (vectors az, el, in deg), assumed to
        occur at time t (defaults to now), get the minimum value of
        the Sun Safety Map traversed by that trajectory.  Also get the
        minimum value of the Sun Distance map.

        This requires the Sun Safety Map to have been computed with a
        base_time in the 24 hours before t.

        Returns a dict with entries:

        - ``'sun_time'``: Minimum Sun Safety Time on the traj.
        - ``'sun_time_start'``: Sun Safety Time at first point.
        - ``'sun_time_stop'``: Sun Safety Time at last point.
        - ``'sun_dist_min'``: Minimum distance to Sun, in degrees.
        - ``'sun_dist_mean'``: Mean distance to Sun.
        - ``'sun_dist_start'``: Distance to Sun, at first point.
        - ``'sun_dist_stop'``: Distance to Sun, at last point.

        """
        if t is None:
            t = self._now()
        j, i = self._azel_pix(az, el, dt=t - self.base_time)
        sun_delta = self.sun_times[j, i]
        sun_dists = self.sun_dist[j, i]

        # If sun is below horizon, rail sun_dist to 180 deg.
        if self.get_sun_pos(t=t)['sun_azel'][1] < self.policy['el_horizon']:
            sun_dists[:] = 180.

        if raw:
            return sun_delta, sun_dists
        return {
            'sun_time': sun_delta.min(),
            'sun_time_start': sun_delta[0],
            'sun_time_stop': sun_delta[-1],
            'sun_dist_start': sun_dists[0],
            'sun_dist_stop': sun_dists[-1],
            'sun_dist_min': sun_dists.min(),
            'sun_dist_mean': sun_dists.mean(),
        }

    def get_sun_pos(self, az=None, el=None, t=None):
        """Get info on the Sun's location at time t.  If (az, el) are also
        specified, returns the angular separation between that
        pointing and Sun's center.

        """
        if t is None:
            t = self._now()
        v = self._sun(t)
        qsun = quat.rotation_lonlat(v.ra, v.dec)

        qzen = coords.CelestialSightLine.naive_az_el(t, 0, np.pi / 2).Q
        neg_zen_az, zen_el, _ = quat.decompose_lonlat(~qzen * qsun)

        results = {
            'sun_radec': (v.ra / DEG, v.dec / DEG),
            'sun_azel': ((-neg_zen_az / DEG) % 360., zen_el / DEG),
        }
        if self.sun_time_shift != 0:
            results['WARNING'] = 'Fake Sun Position is in use!'

        if az is not None:
            qtel = coords.CelestialSightLine.naive_az_el(
                t, az * DEG, el * DEG).Q
            r = quat.decompose_iso(~qtel * qsun)[0]
            results['sun_dist'] = r / DEG
        return results

    def show_map(self, axes=None, show=True):
        """Plot the Sun Safety Map and Sun Distance Map on the provided axes
        (a list)."""
        if axes is None:
            fig, axes = pl.subplots(2, 1)
            fig.tight_layout()
        else:
            fig = None

        imgs = []
        for axi, ax in enumerate(axes):
            if axi == 0:
                # Sun safe time
                x = self.sun_times / HOUR
                x[x == NO_TIME] = np.nan
                title = 'Sun safe time (hours)'
            elif axi == 1:
                # Sun distance
                x = self.sun_dist
                title = 'Sun distance (degrees)'
            im = ax.imshow(x, origin='lower', cmap='Oranges')
            ji = self._azel_pix(0, np.array([90.]))
            ax.scatter(ji[1], ji[0], marker='x', color='white')
            ax.set_title(title)
            pl.colorbar(im, ax=ax)
            imgs.append(im)

        if show:
            pl.show()

        return fig, axes, imgs

    def analyze_paths(self, az0, el0, az1, el1, t=None,
                      plot_file=None, dodging=True):
        """Design and analyze a number of different paths between (az0, el0)
        and (az1, el1).  Return the list, for further processing and
        choice.

        """
        if t is None:
            t = self._now()

        if plot_file:
            assert (t == self.base_time)  # Can only plot "now" results.
            fig, axes, imgs = self.show_map(show=False)
            last_el = None

        # Test all trajectories with intermediate el.
        all_moves = []

        base = {
            'req_start': (az0, el0),
            'req_stop': (az1, el1),
            'req_time': t,
            'travel_el': (el0 + el1) / 2,
            'travel_el_confined': True,
            'direct': True,
        }

        # Suitable list of test els.
        el_lims = [self.policy[_k] for _k in ['min_el', 'max_el']]
        if el0 == el1:
            el_nodes = [el0]
        else:
            el_nodes = sorted([el0, el1])
        if dodging and (el_lims[0] < el_nodes[0]):
            el_nodes.insert(0, el_lims[0])
        if dodging and (el_lims[1] > el_nodes[-1]):
            el_nodes.append(el_lims[1])

        el_sep = 1.
        el_cands = []
        for i in range(len(el_nodes) - 1):
            n = math.ceil((el_nodes[i + 1] - el_nodes[i]) / el_sep)
            assert (n >= 1)
            el_cands.extend(list(
                np.linspace(el_nodes[i], el_nodes[i + 1], n + 1)[:-1]))
        el_cands.append(el_nodes[-1])

        for iel in el_cands:
            detail = dict(base)
            detail.update({
                'direct': False,
                'travel_el': iel,
                'travel_el_confined': (iel >= min(el0, el1)) and (iel <= max(el0, el1)),
            })
            moves = MoveSequence(az0, el0, az0, iel, az1, iel, az1, el1, simplify=True)

            detail['moves'] = moves
            traj_info = self.check_trajectory(*moves.get_traj(), t=t)
            detail.update(traj_info)
            all_moves.append(detail)
            if plot_file and (last_el is None or abs(last_el - iel) > 5):
                c = 'black'
                for j, i in self._azel_pix(*moves.get_traj(), round=True, segments=True):
                    for ax in axes:
                        a, = ax.plot(i, j, color=c, lw=1)
                last_el = iel

        # Include the direct path, but put in "worst case" details
        # based on all "confined" paths computed above.
        direct = dict(base)
        direct['moves'] = MoveSequence(az0, el0, az1, el1, simplify=True)
        traj_info = self.check_trajectory(*direct['moves'].get_traj(), t=t)
        direct.update(traj_info)
        conf = [m for m in all_moves if m['travel_el_confined']]
        if len(conf):
            for k in ['sun_time', 'sun_dist_min', 'sun_dist_mean']:
                direct[k] = min([m[k] for m in conf])
            all_moves.append(direct)

        if plot_file:
            # Add the direct traj, in blue.
            segments = self._azel_pix(*direct['moves'].get_traj(), round=True, segments=True)
            for ax in axes:
                for j, i in segments:
                    ax.plot(i, j, color='blue')
                for seg, rng, mrk in [(segments[0], slice(0, 1), 'o'),
                                      (segments[-1], slice(-1, None), 'x')]:
                    ax.scatter(seg[1][rng], seg[0][rng], marker=mrk, color='blue')
            # Add the selected trajectory in green.
            selected = self.select_move(all_moves)[0]
            if selected is not None:
                traj = selected['moves'].get_traj()
                segments = self._azel_pix(*traj, round=True, segments=True)
                for ax in axes:
                    for j, i in segments:
                        ax.plot(i, j, color='green')

            pl.savefig(plot_file)
        return all_moves

    def find_escape_paths(self, az0, el0, t=None,
                          debug=False):
        """Design and analyze a number of different paths that move from (az0,
        el0) to a sun safe position.  Return the list, for further
        processing and choice.

        """
        if t is None:
            t = self._now()

        az_cands = []
        _az = math.ceil(self.policy['min_az'] / 180) * 180
        while _az <= self.policy['max_az']:
            az_cands.append(_az)
            _az += 180.

        # Clip el0 into the allowed range.
        el0 = np.clip(el0, self.policy['min_el'], self.policy['max_el'])

        # Preference is to not change altitude; but allow for lowering.
        n_els = math.ceil(el0 - self.policy['min_el']) + 1
        els = np.linspace(el0, self.policy['min_el'], n_els)

        path = None
        for el1 in els:
            paths = [self.analyze_paths(az0, el0, _az, el1, t=t, dodging=False)
                     for _az in az_cands]
            best_paths = [self.select_move(p)[0] for p in paths]
            best_paths = [p for p in best_paths if p is not None]
            if len(best_paths):
                path = self.select_move(best_paths)[0]
                if debug:
                    cands, _ = self.select_move(best_paths, raw=True)
                    return cands
            if path is not None:
                return path

        return None

    def select_move(self, moves, raw=False):
        """Given a list of possible "moves", select the best one.
        The "moves" should be like the ones returned by
        ``analyze_paths``.

        The best move is determined by first screening out dangerous
        paths (ones that pass close to Sun, move closer to Sun
        unnecessarily, violate axis limits, etc.) and then identifying
        paths that minimize danger (distance to Sun; Sun time) and
        path length.

        If raw=True, a debugging output is returned; see code.

        Returns:
          (dict, list): (best_move, decisions)

          ``best_move`` -- the element of moves that is safest.  If no
          safe move was found, None is returned.

          ``decisions`` - List of dicts, in one-to-one correspondence
          with ``moves``.  Each decision dict has entries 'rejected'
          (True or False) and 'reason' (string description of why the
          move was rejected outright).

        """
        _p = self.policy

        decisions = [{'rejected': False,
                      'reason': None} for m in moves]

        def reject(d, reason):
            d['rejected'] = True
            d['reason'] = reason

        # According to policy, reject moves outright.
        for m, d in zip(moves, decisions):
            if d['rejected']:
                continue

            els = m['req_start'][1], m['req_stop'][1]

            if _p['axes_sequential'] and m['moves'].includes_mixed_moves():
                reject(d, 'Path includes simultaneous az+el legs (forbidden in policy).')
                continue

            if (m['sun_time_start'] < _p['min_sun_time']):
                # If the path is starting in danger zone, then only
                # enforce that the move takes the platform to a better place.

                # Test > res, rather than > 0... near the minimum this
                # can be noisy.
                if m['sun_dist_start'] - m['sun_dist_min'] > self.res / DEG:
                    reject(d, 'Path moves even closer to sun.')
                    continue
                if m['sun_time_stop'] < _p['min_sun_time']:
                    reject(d, 'Path does not end in sun-safe location.')
                    continue

            elif m['sun_time'] < _p['min_sun_time']:
                reject(d, 'Path too close to sun.')
                continue

            if m['travel_el'] < _p['min_el']:
                reject(d, 'Path goes below minimum el.')
                continue

            if m['travel_el'] > _p['max_el']:
                reject(d, 'Path goes above maximum el.')
                continue

            if not _p['el_dodging']:
                if m['travel_el'] < min(*els):
                    reject(d, 'Path dodges (goes below necessary el range).')
                    continue
                if m['travel_el'] > max(*els):
                    reject(d, 'Path dodges (goes above necessary el range).')

        cands = [m for m, d in zip(moves, decisions)
                 if not d['rejected']]
        if len(cands) == 0:
            return None, decisions

        def metric_func(m):
            # Sorting key for move proposals.  More preferable paths
            # should have higher sort order.
            azs = m['req_start'][0], m['req_stop'][0]
            els = m['req_start'][1], m['req_stop'][1]
            return (
                # Low sun_time is bad, though anything longer
                # than response_time is equivalent.
                m['sun_time'] if m['sun_time'] < _p['response_time'] else _p['response_time'],

                # Single leg moves are preferred, for simplicity.
                m['direct'],

                # Higher minimum sun distance is preferred.
                m['sun_dist_min'],

                # Shorter paths (less total az / el motion) are preferred.
                -(abs(m['travel_el'] - els[0]) + abs(m['travel_el'] - els[1])),
                -abs(azs[1] - azs[0]),

                # Larger mean Sun distance is preferred.  But this is
                # subdominant to path length; otherwise spinning
                # around a bunch of times can be used to lower the
                # mean sun dist!
                m['sun_dist_mean'],

                # Prefer higher elevations for the move, all else being equal.
                m['travel_el'],
            )
        cands.sort(key=metric_func)
        if raw:
            return [(c, metric_func(c)) for c in cands], decisions
        return cands[-1], decisions


class MoveSequence:
    def __init__(self, *args, simplify=False):
        """Container for a series of (az, el) positions.  Pass the
        positions to the constructor as (az, el) tuples::

          MoveSequence((60, 180), (60, 90), (50, 90))

        or equivalently as individual arguments::

          MoveSequence(60, 180, 60, 90, 50, 90)

        If simplify=True is passed, then any immediate position
        repetitions are deleted.

        """
        self.nodes = []
        if len(args) == 0:
            return
        is_tuples = [isinstance(a, tuple) for a in args]
        if all(is_tuples):
            pass
        elif any(is_tuples):
            raise ValueError('Constructor accepts tuples or az, el, az, el; not a mix.')
        else:
            assert (len(args) % 2 == 0)
            args = [(args[i], args[i + 1]) for i in range(0, len(args), 2)]
        for (az, el) in args:
            self.nodes.append((float(az), float(el)))
        if simplify:
            # Remove repeated nodes.
            idx = 0
            while idx < len(self.nodes) - 1:
                if self.nodes[idx] == self.nodes[idx + 1]:
                    self.nodes.pop(idx + 1)
                else:
                    idx += 1

    def get_legs(self):
        """Iterate over the legs of the MoveSequence; yields each ((az_start,
        el_start), (az_end, az_end)).

        """
        for i in range(len(self.nodes) - 1):
            yield self.nodes[i:i + 2]

    def get_traj(self, res=0.5):
        """Return (az, el) vectors with the full path for the MoveSequence.
        No step in az or el will be greater than res.

        """
        if len(self.nodes) == 1:
            return np.array([self.nodes[0][0]]), np.array([self.nodes[0][1]])

        xx, yy = [], []
        for (x0, y0), (x1, y1) in self.get_legs():
            n = max(2, math.ceil(abs(x1 - x0) / res), math.ceil(abs(y1 - y0) / res))
            xx.append(np.linspace(x0, x1, n))
            yy.append(np.linspace(y0, y1, n))
        return np.hstack(tuple(xx)), np.hstack(tuple(yy))

    def includes_mixed_moves(self):
        """Returns True if any of the legs include simultaneous
        changes in az and el.

        """
        for (x0, y0), (x1, y1) in self.get_legs():
            if (x0 != x1) and (y0 != y1):
                return True
        return False
