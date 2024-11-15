"""
temporary automation for telescope platforms.

"""

import argparse
import math
import random
import time

import ocs
import yaml
from ocs.ocs_client import OCSClient


def assert_ok(result):
    if result.status != ocs.base.OK:
        print('RESULT!=OK!', result)
        raise RuntimeError()


def wait_verbosely(target, timeout=5, msg=' ... still going '):
    last_stop = 0
    while True:
        # Watch for process exit
        result = target.wait(timeout=timeout)
        if result.status == ocs.base.TIMEOUT:
            print(msg, get_pos())
        elif result.status == ocs.base.ERROR:
            raise RuntimeError('Operation failed.')
        else:
            break
        # Detect az fault
        if get_faults()['az_summary'] and time.time() - last_stop > 10:
            print(' -- az summary fault detected, stop&clear.')
            assert_ok(c.stop_and_clear())
            last_stop = time.time()

    return True


def safe_get_status():
    # dodge a race condition
    for i in range(10):
        try:
            return c.monitor.status().session['data']['StatusDetailed']
        except KeyError:
            time.sleep(0.01)
    raise KeyError("Could not read StatusDetailed!")


def get_pos():
    status = safe_get_status()
    return (status['Azimuth current position'],
            status['Elevation current position'])


def get_faults():
    status = safe_get_status()
    return {
        'az_summary': status['Azimuth summary fault'],
        'local_mode': not status['ACU in remote mode'],
        'safe_lock': status['Safe'],
    }


def clear_faults():
    c.clear_faults.start()
    c.clear_faults.wait()


def set_boresight(angle):
    assert_ok(c.set_boresight.start(target=angle))
    wait_verbosely(c.set_boresight, msg=' ... setting boresight...')


def steps(targets=[], **kw):
    for az, el in targets:
        _az, _el = get_pos()
        if az is None:
            az = _az
        if el is None:
            el = _el
        assert_ok(c.go_to.start(az=az, el=el))
        wait_verbosely(c.go_to, msg=' ... moving')


def scan(az, el, throw,
         v_az=1.,
         a_az=1.,
         num_scans=3,
         step_time=1.,
         wait_to_start=10.,
         init='mid',
         init_az=None,
         ramp_up=0,
         ):
    if init_az is None:
        init_az = az
    print(f'Going to {init_az}, {el}')
    assert_ok(c.go_to.start(az=init_az, el=el))
    wait_verbosely(c.go_to, msg=' ... still go_to-ing')

    # assert(init == 'end')
    # ramp_up = az - throw - init_az
    # print(ramp_up)

    print('Checking positions ...')
    az1, el1 = get_pos()
    assert (abs(az1 - init_az) < .1 and abs(el1 - el) < .1)

    print('Stop and clear.')
    assert_ok(c.stop_and_clear())

    assert_ok(
        c.generate_scan.start(
            az_endpoint1=az - throw,
            az_endpoint2=az + throw,
            az_speed=v_az,
            az_accel=a_az,
            el_endpoint1=el,
            el_endpoint2=el,
            num_scans=num_scans,
            az_start=init)
    )

    wait_verbosely(c.generate_scan, msg=' ... still scanning ...')

    print('Finally we are at', get_pos())
    # time.sleep(2)
    time.sleep(5)

    print('Stop + clear')
    assert_ok(c.stop_and_clear())


def plan_scan(az, el, throw, v_az=1, a_az=1, init='end',
              full_ramp=False, num_scans=1):
    # Initialize arguments suitable for passing to scan() ...
    plan = {
        'az': az,
        'el': el,
        'throw': throw,
        'v_az': v_az,
        'a_az': a_az,
        'init': init,
        'init_az': az,
        'num_scans': num_scans,
    }
    info = {}

    # Point separation?  At least 5 points per leg, preferably 10.
    dt = 2 * abs(throw / v_az) / 10
    dt = min(max(dt, 0.1), 1.0)
    assert (2 * abs(throw / v_az) / dt >= 5)
    plan['step_time'] = dt

    # Turn around prep distance? 5 point periods, times the vel.
    az_prep = 5 * dt * v_az

    # Ramp-up distance needed
    a0 = 1.  # Peak accel of ramp-up...
    az_rampup = v_az**2 / a0
    info['az_prep'] = az_prep
    info['az_rampup'] = az_rampup

    # Any az ramp-up prep required?
    if full_ramp:
        ramp_up = az_rampup
    elif init == 'mid':
        ramp_up = max(az_prep + az_rampup - abs(throw), 0)
    elif init == 'end':
        ramp_up = max(az_prep + az_rampup - 2 * abs(throw), 0)
    else:
        raise  # init in ['mid', 'end']
    plan['ramp_up'] = ramp_up

    # Set wait time (this comes out a little lower than its supposed to...)
    # plan['wait_time'] = v_az / a0 * 2
    info['pre_time'] = v_az / a0
    plan['wait_to_start'] = max(5, info['pre_time'] * 1.2)

    # Fill out some other useful info...
    plan['init_az'] = az - math.copysign(ramp_up, throw)
    if init == 'end':
        plan['init_az'] -= throw

    info['total_time'] = (
        num_scans * (2 * abs(throw) / v_az + 2 * v_az / a_az)
        + ramp_up / v_az * 2
        + plan['wait_to_start'])

    return plan, info


class _Plan:
    code = 'something'

    def __iter__(self):
        self.index = 0
        return self

    def __next__(self):
        X = self.get_plan(self.index)
        self.index += 1
        return X


class ScanPlan(_Plan):
    pass


class PointPlan(_Plan):
    pass


class GridPlan(ScanPlan):
    DEFAULT_DURATION = 1200
    code = 'grid'

    def __init__(self, **kw):
        self.config = {
            'els': [50., 55., 60.],
            'azs': [0, 50, 90, 140, 180, 220, 270, 310],
            'az_throw': 20,
            'num_scans': 7,
            # 'num_scans': 1,
            'v_az': 1.,
            'a_az': 1.,
        }
        self.config.update(kw)
        self.index = 0

    def get_plan(self, index):
        c = self.config
        superphase = index // len(c['azs']) % 2
        step = 1 - 2 * superphase

        def get_mod(entry):
            return entry[index % len(entry)]

        plan, info = plan_scan(get_mod(c['azs'][::step]), get_mod(c['els']),
                               c['az_throw'] * step,
                               v_az=c['v_az'], a_az=c['a_az'],
                               num_scans=c['num_scans'])
        return plan, info


class ElNod(PointPlan):
    DEFAULT_DURATION = 60
    code = 'elnod'

    def __init__(self, **kw):
        self.repeat = kw.get('repeat', 1)

    def get_plan(self, index):
        t = {'targets': [(None, 20), (None, 90)] * self.repeat}
        return t, {}


class SchedulePlan(ScanPlan):
    DEFAULT_DURATION = 1200
    code = 'mock-sched'

    def __init__(self, sched_files, format='toast3',
                 dedup=True, dwell_time=None):
        if isinstance(sched_files, str):
            sched_files = [sched_files]
        if dwell_time is None:
            dwell_time = 300
        rows = []
        row_track = set()
        for filename in sched_files:
            skip = 3
            for line in open(filename):
                if skip > 0:
                    skip -= 1
                    continue
                w = line.split()
                row = {
                    'mjd0': float(w[4]),  # mjd start
                    'mjd1': float(w[5]),  # mjd end
                    'boresight': float(w[6]),  # boresight rotation
                    'az_min': float(w[8]),  # az min
                    'az_max': float(w[9]),  # az max
                    'el': float(w[10]),  # el
                }
                # rebranch
                row['az_max'] = row['az_min'] + (row['az_max'] - row['az_min']) % 360
                row['az'] = (row['az_max'] + row['az_min']) / 2
                row['az_throw'] = (row['az_max'] - row['az_min']) / 2

                # enrich
                row['v_az'] = 1. / math.cos(row['el'] * math.pi / 180)
                row['a_az'] = 2.
                row['num_scans'] = (dwell_time // (row['az_throw'] / row['v_az'])) + 1
                if dedup:
                    key = tuple([row[k] for k in ['az', 'az_throw', 'el']])
                    if key in row_track:
                        continue
                    row_track.add(key)
                rows.append(row)
        self.rows = rows

    def get_plan(self, index):
        row = self.rows[index % len(self.rows)]
        kw = {k: row[k] for k in ['v_az', 'a_az', 'num_scans']}
        return plan_scan(row['az'], row['el'], row['az_throw'],
                         **kw)


class GreasePlan(ScanPlan):
    DEFAULT_DURATION = 120
    code = 'grease'

    def __init__(self, phase=None):
        self.n = 4
        self.el_n = 9
        if phase is None:
            phase = int(random.random() * self.n)
        self.phase = phase

    def get_plan(self, index):
        phase = (self.phase + index) % self.n
        el = 30 + 40 * (index % self.el_n) / (self.el_n - 1)
        limits = [-80 + phase * 5, 440 + (phase - self.n - 1) * 5]
        print(limits)
        return plan_scan((limits[0] + limits[1]) / 2, el, (limits[1] - limits[0]) / 2,
                         v_az=2, a_az=0.5, num_scans=2, init='end')


def get_plan(config):
    if isinstance(config, str):
        config = yaml.safe_load(open(config, 'rb').read())
    for i, step in enumerate(config['steps']):
        if step['type'] == 'grease':
            driver = GreasePlan()
        elif step['type'] == 'schedule':
            driver = SchedulePlan(step['files'], dwell_time=step.get('dwell_time'))
        elif step['type'] == 'grid':
            driver = GridPlan()
        elif step['type'] == 'elnod':
            driver = ElNod(**step)
        else:
            raise ValueError('Invalid step type "%s"' % step['type'])
        plan = {'driver': driver,
                'duration': step.get('duration', driver.DEFAULT_DURATION),
                }
        config['steps'][i] = plan  # replace
    return config


def set_client(instance_id, args=None):
    # It's a good idea to pass in args in case user has overridden the
    # default site config file.
    global c
    c = OCSClient(instance_id, args=args)
    return c


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('instance_id', help="e.g. acu-sat1")
    parser.add_argument('--hours', type=float)
    args = parser.parse_args()

    if args.config is not None:
        # Get the plan.
        super_plan = get_plan(args.config)

    c = OCSClient(args.instance_id)
    now = time.time()
    stop_at = None
    if args.hours:
        stop_at = now + args.hours * 3600.

    plan_idx = 1
    while stop_at is None or time.time() < stop_at:
        t0 = time.time()
        t = t0
        active_plan = super_plan['steps'][plan_idx]
        print(active_plan['driver'])
        for plan, info in active_plan['driver']:
            if isinstance(plan, ScanPlan):
                scan(**plan)
            elif isinstance(plan, PointPlan):
                steps(**plan)
            else:
                raise ValueError
            if time.time() - t0 > active_plan['duration']:
                break
        plan_idx += 1
        if plan_idx >= len(super_plan['steps']):
            if super_plan.get('loop', True):
                plan_idx = 0
