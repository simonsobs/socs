import re
import subprocess as sp
import time
from dataclasses import dataclass

import numpy as np
import yaml


def ping_host(hostname):
    base = {'hostname': hostname,
            'timestamp': time.time(),
            'error': False}
    p = sp.run(["ping", "-c 1", "-W 0.2", hostname],
               capture_output=True)
    if p.returncode != 0:
        return base | {
            'error': True,
            'message': 'Ping command failed.',
        }
    text = p.stdout.decode("utf8")
    m = None
    for line in text.split("\n"):
        m = re.match(
            r"(?P<packet_size>\d+) bytes from (?P<host_string>.*): icmp_seq=(\d+) "
            r"ttl=(?P<ttl>\d+) time=(?P<ping_time_ms>\d+\.\d+) ms",
            line)
        if m is not None:
            break
    else:
        return base | {
            'error': True,
            'message': 'Could not parse ping stdout: {text}',
        }
    data = m.groupdict()
    for k, v in data.items():
        for cast in [int, float]:
            try:
                data[k] = cast(v)
                break
            except BaseException:
                continue
    return base | data


@dataclass
class PingTarget:
    name: str
    ip: str = None


class PingTrack:
    def __init__(self, target: PingTarget):
        self.hostname = target.name
        self.data = None
        self.clear()

    def __repr__(self):
        return f'PingTrack<{self.hostname},{len(self.data["t"])}>'

    def clear(self):
        self.data = {
            't': [],
            'ok': [],
            'ping_ms': [],
        }

    def add_record(self, data):
        rec = {'t': data['timestamp'],
               'ok': False,
               'ping_ms': 0,
               }
        if not data['error']:
            rec['ok'] = True
            rec['ping_ms'] = data['ping_time_ms']
        for k, v in rec.items():
            self.data[k].append(v)

    def get_stats(self, lookback=None):
        if lookback is None:
            lookback = 60
        unpack_ret = not hasattr(lookback, '__len__')
        if unpack_ret:
            lookback = [lookback]
        vects = {k: np.array(v) for k, v in self.data.items()}
        results = []
        for lb in lookback:
            ref_time = time.time() - lb
            mask = vects['t'] >= ref_time
            if len(mask) == 0 or mask.sum() == 0:
                results.append({})
                continue
            up_frac = (vects['ok'][mask].sum() / mask.sum()).item()
            if up_frac > 0:
                ping_ms = vects['ping_ms'][mask].mean().round(3).item()
            else:
                ping_ms = 0.
            results.append({
                'count': mask.sum(),
                'up_fraction': up_frac,
                'ping_ms': ping_ms,
            })
        if unpack_ret:
            return results[0]
        return results


class Pinger:
    def __init__(self):
        self.data = {}
        self.intervals = []

    def set_intervals(self, intervals):
        self.intervals = intervals

    def add_targets(self, targets):
        for t in targets:
            assert t.name not in self.data
            self.data[t.name] = PingTrack(t)

    def poll(self):
        for k, pt in self.data.items():
            r = ping_host(pt.hostname)
            pt.add_record(r)

    def get_stats(self):
        per_host = {}
        for k, pt in self.data.items():
            per_host[k] = pt.get_stats(self.intervals)
        per_interval = []
        for i, ival in enumerate(self.intervals):
            out = {'window_size': ival,
                   'hosts': {}}
            for h, stats in per_host.items():
                out['hosts'][h] = stats[i]
            per_interval.append(out)
        return per_interval


@dataclass
class PingConfig:
    intervals: list[float]
    hosts: list[PingTarget]

    @classmethod
    def from_file(cls, filename):
        data = yaml.safe_load(open(filename, 'rb'))
        complex = {'hosts': [PingTarget(**host) for host in data.pop('hosts', [])]}
        return cls(**(data | complex))
