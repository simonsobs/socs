"""Sun Avoidance

This module provides code to support Sun Avoidance in the ACU Agent.
The basic idea is to create a map in equatorial coordinates where the
value of the map indicates when that region of the sky will next be
within the Sun Exclusion Zone (likely defined as some radius around
the Sun).

Using that pre-computed map, any az-el pointings can be checked for
Sun safety (i.e. whether they are safe positoins), at least for the
following 24 hours.  The map can be used to identify safest routes
between two az-el pointings.

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
}


class SunTracker:
    """Provide guidance on what horizion coordinate positions are
    sun-safe.

    Key concepts:
    - Sun Safety Map
    - Az-el trajectory

    Args:
      exclusion_radius (float, deg): radius of circle around the Sun
        to consider as "unsafe".
      map_res (float, deg): resolution to use for the Sun Safety Map.
      site (str or None): Site to use (so3g site, defaults to so_lat).

    """

    def __init__(self, policy=None, site=None,
                 map_res=.5, sun_time_shift=0., fake_now=None,
                 compute=True, base_time=None):
        # Note res is stored in radians.
        self.res = map_res * DEG
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
        base_time of t - 24 hours or later.

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
            'sun_azel': (-neg_zen_az / DEG, zen_el / DEG),
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

        # Include the "direct" path.
        direct = dict(base)
        direct['moves'] = MoveSequence(az0, el0, az1, el1)
        traj_info = self.check_trajectory(*direct['moves'].get_traj(), t=t)
        direct.update(traj_info)
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
                          plot_file=None):
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
            best_paths = [self.select_move(p, escape=True)[0] for p in paths]
            best_paths = [p for p in best_paths if p is not None]
            if len(best_paths):
                path = self.select_move(best_paths, escape=True)[0]
            if path is not None:
                return path

        return None

    def select_move(self, moves, escape=False):
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

            if escape and (m['sun_time_start'] < _p['min_sun_time']):
                # Test > res, rather than > 0... near the minimum this
                # can be noisy.
                if m['sun_dist_start'] - m['sun_dist_min'] > self.res / DEG:
                    reject(d, 'Path moves even closer to sun.')
                    continue
                if m['sun_time_stop'] < _p['min_sun_time']:
                    reject(d, 'Path does not end in sun-safe location.')
                    continue
            else:
                if m['sun_time'] < _p['min_sun_time']:
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

        def priority_func(m):
            # Sorting key for move proposals.
            azs = m['req_start'][0], m['req_stop'][0]
            els = m['req_start'][1], m['req_stop'][1]
            return (
                m['sun_time'] if m['sun_time'] < _p['response_time'] else _p['response_time'],
                m['direct'],
                m['sun_dist_min'],
                m['sun_dist_mean'],
                -(abs(m['travel_el'] - els[0]) + abs(m['travel_el'] - els[1])),
                -abs(azs[1] - azs[0]),
                m['travel_el'],
            )
        cands.sort(key=priority_func)
        return cands[-1], decisions


class MoveSequence:
    def __init__(self, *args, simplify=False):
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
            self.nodes.append((az, el))
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
        xx, yy = [], []
        for (x0, y0), (x1, y1) in self.get_legs():
            n = max(2, math.ceil(abs(x1 - x0) / res), math.ceil(abs(y1 - y0) / res))
            xx.append(np.linspace(x0, x1, n))
            yy.append(np.linspace(y0, y1, n))
        return np.hstack(tuple(xx)), np.hstack(tuple(yy))


class RollingMinimum:
    def __init__(self, window, fallback=None):
        self.window = window
        self.subwindow = window / 10
        self.fallback = fallback
        self.records = []

    def append(self, val, t=None):
        if t is None:
            t = time.time()
        # Remove old data
        while len(self.records) and (t - self.records[0][0]) > self.window:
            self.records.pop(0)
        # Add this to existing subwindow?
        if len(self.records):
            # Consider values up to subwindow ago.
            _t, _val = self.records[-1]
            if t - _t < self.subwindow:
                if val <= _val:
                    self.records[-1] = (t, val)
                return
        # Or start a new subwindow.
        self.records.append((t, val))

    def get(self, lookback=None):
        if lookback is None:
            lookback = self.window
        recs = [v for t, v in self.records if (time.time() - t < lookback)]
        if len(recs):
            return min(recs)
        return self.fallback
