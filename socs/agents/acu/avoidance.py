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
      time_res (float, s): Time resolution at which to evaluate Sun
        trajectory.
      site (str or None): Site to use (so3g site, defaults to so_lat).

    """

    def __init__(self, exclusion_radius=20., map_res=0.5,
                 time_res=300., site=None, horizon=0.):
        # Store in radians.
        self.exclusion_radius = exclusion_radius * DEG
        self.res = map_res * DEG
        self.time_res = time_res
        self.horizon = horizon

        if site is None:
            # This is close enough.
            site = coords.SITES['so_lat']
        site_eph = ephem.Observer()
        site_eph.lon = site.lon * DEG
        site_eph.lat = site.lat * DEG
        site_eph.elevation = site.elev
        self._site = site_eph
        self.base_time = None
        self.fake_now = None

    def _now(self):
        if self.fake_now:
            return self.fake_now
        return time.time()

    def reset(self, base_time=None, staleness=None):
        """Compute and store the Sun Safety Map for a specific
        timestamp.

        This basic computation is required prior to calling other
        functions that use the Sun Safety Map.

        If staleness is provided, then the map is only updated if it
        has not yet been computed, or if the requested base_time is
        earlier than the base_time of the currently stored map, or if
        the requested base_time is more than staleness seconds in the
        future from the currently store map.

        """
        # Set a reference time -- the map of sun times is usable from
        # this reference time to at least 12 hours in the future.
        if base_time is None:
            base_time = self._now()

        if self.base_time is not None and staleness is not None:
            if ((base_time - self.base_time) > 0
                    and (base_time - self.base_time) < staleness):
                return False

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

        self._site.date = \
            datetime.datetime.utcfromtimestamp(base_time + 0)
        v = ephem.Sun(self._site)

        # Get the map of angular distance to the Sun.
        qsun = quat.rotation_lonlat(v.ra, v.dec)
        sun_dist[:] = (quat.decompose_iso(~qsun * map_q)[0]
                       .reshape(sun_dist.shape) / coords.DEG)

        # Get the map where each pixel says the time delay between
        # base_time and when the time when the sky coordinate will be
        # in the Sun mask.  This is not terribly fast.  The Sun moves
        # slowly enough that one could do a decent job of filling in
        # the rest of the map based on the t=0 footprint.  Fix me.
        for dt in np.arange(0, 24 * HOUR, self.time_res):
            qsun = quat.rotation_lonlat(v.ra - dt / HOUR * 15. * DEG, v.dec)
            qoff = ~qsun * map_q
            r = quat.decompose_iso(qoff)[0].reshape(sun_times.shape)
            mask = (sun_times < 0) * (r < self.exclusion_radius)
            sun_times[mask] = dt

        # Fill in remaining -1 with NO_TIME.
        sun_times[sun_times < 0] = NO_TIME

        # Store the sun_times map and stuff.
        self.base_time = base_time
        self.sun_times = sun_times
        self.sun_dist = sun_dist
        self.map_q = map_q
        return True

    def _save(self, filename):
        import pickle

        # Pickle results of "reset"
        pickle.dump((self.base_time, self.map_q, self.sun_dist.wcs,
                     self.sun_dist, self.sun_times),
                    open(filename, 'wb'))

    def _load(self, filename):
        import pickle
        X = pickle.load(open(filename, 'rb'))
        self.base_time = X[0]
        self.sun_times = enmap.ndmap(X[4], wcs=X[2])
        self.sun_dist = enmap.ndmap(X[3], wcs=X[2])
        self.map_q = X[1]

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
        occur at time t, get the minimum value of the Sun Safety Map
        traversed by that trajectory.  Also get the minimum value of
        the Sun Distance map.

        This requires the Sun Safety Map to have been computed with a
        base_time of t - 24 hours or later.

        Returns the Sun Safety time for the trajectory, in seconds,
        and nearest Sun approach, in degrees.

        """
        if t is None:
            t = self.base_time
        j, i = self._azel_pix(az, el, dt=t - self.base_time)
        sun_delta = self.sun_times[j, i]
        sun_dists = self.sun_dist[j, i]

        # If sun is below horizon, rail sun_dist to 180 deg.
        if self.get_sun_pos(t=t)['sun_azel'][1] < self.horizon:
            sun_dists[:] = 180.

        if raw:
            return sun_delta, sun_dists
        return {
            'sun_time': sun_delta.min(),
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
        self._site.date = \
            datetime.datetime.utcfromtimestamp(t)
        v = ephem.Sun(self._site)
        qsun = quat.rotation_lonlat(v.ra, v.dec)

        qzen = coords.CelestialSightLine.naive_az_el(t, 0, np.pi / 2).Q
        neg_zen_az, zen_el, _ = quat.decompose_lonlat(~qzen * qsun)

        results = {
            'sun_radec': (v.ra / DEG, v.dec / DEG),
            'sun_azel': (-neg_zen_az / DEG, zen_el / DEG),
        }
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
                      plot_file=None, policy=None):
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
        if el0 == el1:
            el_nodes = [el0]
        else:
            el_nodes = sorted([el0, el1])
        if 10. < el_nodes[0]:
            el_nodes.insert(0, 10.)
        if 90. > el_nodes[-1]:
            el_nodes.append(90.)

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
            selected = None
            if policy is not None:
                selected = select_move(all_moves, policy)[0]
            if selected is not None:
                traj = selected['moves'].get_traj()
                segments = self._azel_pix(*traj, round=True, segments=True)
                for ax in axes:
                    for j, i in segments:
                        ax.plot(i, j, color='green')

            pl.savefig(plot_file)
        return all_moves


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


DEFAULT_POLICY = {
    'min_el': 0,
    'max_el': 90,
    'el_dodging': True,
    'min_sun_time': HOUR,
    'response_time': HOUR * 4,
}


def select_move(moves, policy):
    for k in policy.keys():
        assert k in DEFAULT_POLICY
    _p = dict(DEFAULT_POLICY)
    _p.update(policy)

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
        els = m['req_start'][1], m['req_stop'][1]
        return (
            m['sun_time'] if m['sun_time'] < _p['response_time'] else _p['response_time'],
            m['direct'],
            m['sun_dist_min'],
            m['sun_dist_mean'],
            -(abs(m['travel_el'] - els[0]) + abs(m['travel_el'] - els[1])),
            m['travel_el'],
        )
    cands.sort(key=priority_func)
    return cands[-1], decisions
