import json
import os
import sys
import traceback
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Dict, List, Optional

import numpy as np
import sodetlib as sdl
from sodetlib.det_config import DetConfig
from sodetlib.operations import (bias_steps, bias_wave, iv, uxm_relock,
                                 uxm_setup)
from twisted.internet import defer, protocol, reactor, threads

NBIASLINES = 12


def json_safe(data):
    """Convert data so it can be serialized and decoded on
    the other end.  This includes:

    - Converting numpy arrays and scalars to generic lists and
        Python basic types.
    - Converting NaN/inf to Num (0 or +/- large number)
    """
    if is_dataclass(data):
        return json_safe(asdict(data))
    if isinstance(data, dict):
        return {k: json_safe(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [json_safe(x) for x in data]
    if hasattr(data, 'dtype'):
        # numpy arrays and scalars.
        return json_safe(data.tolist())
    if isinstance(data, (str, int, bool)):
        return data
    if isinstance(data, float):
        return np.nan_to_num(data)
    if data is None:
        return None

    print(f"Unsure how to encode data of type {type(data)}...")
    print(f"data: {data}")
    # This could still be something weird but json.dumps will
    # probably reject it!
    return data


@dataclass
class QuantileData:
    name: str
    quantiles: List[float]
    values: List[float]
    total: int

    def to_block_data(self):
        "Format quantile data for OCS HK block"
        labels = [f'{self.name}_q{int(q)}' for q in self.quantiles]
        block_data = dict(zip(labels, self.values))
        block_data[f'{self.name}_total'] = self.total
        return block_data


def compute_quantiles(name: str, arr: np.ndarray, quantiles: List[float]):
    """
    Computes QuantileData object for a given array

    """
    quantiles = [float(q) for q in quantiles]
    if np.isnan(arr).all():
        return QuantileData(name, quantiles, [0 for _ in quantiles], 0)
    qs = [float(np.nan_to_num(np.nanquantile(arr, q / 100))) for q in quantiles]
    total = int(np.sum(~np.isnan(arr)))
    return QuantileData(name, quantiles, qs, total)


def encode_dataclass(obj):
    """
    Encodes a data-class into json, replacing any json-unsafe types with
    reasonable alternatives.
    """
    data = json_safe(obj)
    return json.dumps(data).encode()


def get_smurf_control():
    """
    Get the SMuRF control object and sodetlib configuration object for the
    current slot
    """
    slot = os.environ['SLOT']
    cfg = DetConfig()
    cfg.load_config_files(slot=slot)
    S = cfg.get_smurf_control()
    S.load_tune(cfg.dev.exp['tunefile'])
    return S, cfg


def take_noise(duration, kwargs=None):
    """Runs take_noise in sodetlib"""
    if kwargs is None:
        kwargs = {}
    S, cfg = get_smurf_control()
    _, res = sdl.noise.take_noise(S, cfg, duration, **kwargs)
    wls = res['noise_pars'][:, 0]
    qs = [10, 25, 50, 75, 90]
    return {
        'quantiles': {
            'white_noise_level': compute_quantiles('white_noise_level', wls, qs),
        }
    }


def take_bgmap(kwargs=None):
    if kwargs is None:
        kwargs = {}
    S, cfg = get_smurf_control()
    bsa = bias_steps.take_bgmap(S, cfg, **kwargs)

    nchans_per_bg = [0 for _ in range(NBIASLINES + 1)]
    for bg in range(NBIASLINES):
        nchans_per_bg[bg] = int(np.sum(bsa.bgmap == bg))
    nchans_per_bg[-1] = int(np.sum(bsa.bgmap == -1))
    return {
        'nchans_per_bg': nchans_per_bg,
        'filepath': bsa.filepath,
    }


def take_iv(iv_kwargs=None):
    """Runs and analyzes an IV curve"""
    S, cfg = get_smurf_control()
    if iv_kwargs is None:
        iv_kwargs = {}
    iva = iv.take_iv(S, cfg, **iv_kwargs)
    quantiles = [10, 25, 50, 75, 90]
    return {
        'filepath': iva.filepath,
        'quantiles': {
            'Rn': compute_quantiles('Rn', iva.R_n, quantiles),
            'p_sat': compute_quantiles('p_sat', iva.p_sat, quantiles)
        }
    }


def run_uxm_setup(bands=None, kwargs=None):
    """Runs through the UXM setup procedure"""
    if kwargs is None:
        kwargs = {}
    S, cfg = get_smurf_control()
    uxm_setup.uxm_setup(S, cfg, bands=bands, **kwargs)
    return None


def run_uxm_relock(bands=None, kwargs=None):
    """Runs through the UXM relock procedure"""
    if kwargs is None:
        kwargs = {}
    S, cfg = get_smurf_control()
    uxm_relock.uxm_relock(S, cfg, bands=bands, **kwargs)
    return None


def take_bias_steps(kwargs=None, rfrac_range=(0.2, 0.9)):
    """Takes bias steps and computes quantiles for various parameters"""
    if kwargs is None:
        kwargs = {}

    S, cfg = get_smurf_control()
    bsa = bias_steps.take_bias_steps(S, cfg, **kwargs)

    biased = np.logical_and.reduce([
        rfrac_range[0] < bsa.Rfrac,
        rfrac_range[1] > bsa.Rfrac
    ])
    qs = [10, 25, 50, 75, 90]
    data = {
        'filepath': bsa.filepath,
        'biased_total': int(np.sum(biased)),
        'biased_per_bg': [
            int(np.sum(biased[bsa.bgmap == bg])) for bg in range(12)
        ],
        'quantiles': {
            'Rfrac': compute_quantiles('Rfrac', bsa.Rfrac, qs),
            'Si': compute_quantiles('Si', bsa.Si, qs),
            'Rtes': compute_quantiles('Rtes', bsa.R0, qs),
        }
    }
    return data


def take_bias_waves(kwargs=None, rfrac_range=(0.2, 0.9)):
    if kwargs is None:
        kwargs = {}
    S, cfg = get_smurf_control()
    bwa = bias_wave.take_bias_waves(
        S, cfg, **kwargs
    )
    biased = np.logical_and.reduce([
        rfrac_range[0] < bwa.Rfrac,
        rfrac_range[1] > bwa.Rfrac
    ])
    qs = [10, 25, 50, 75, 90]
    data = {
        'filepath': bwa.filepath,
        'biased_total': int(np.sum(biased)),
        'biased_per_bg': [
            int(np.sum(biased[bwa.bgmap == bg])) for bg in range(12)
        ],
        'quantiles': {
            'Rfrac': compute_quantiles('Rfrac', bwa.Rfrac, qs),
            'Si': compute_quantiles('Si', bwa.Si, qs),
            'Rtes': compute_quantiles('Rtes', bwa.R0, qs),
        }
    }
    return data


def test():
    """Function for testing subprocess operation"""
    print("Inside test func")
    return {'test': 10}


runnable_funcs = [
    take_noise, take_iv, run_uxm_setup, run_uxm_relock, take_bias_steps,
    take_bias_waves, test, take_bgmap
]
func_map = {f.__name__: f for f in runnable_funcs}


@dataclass
class RunCfg:
    func_name: str
    "name of function to run"

    args: List = field(default_factory=list)
    "Args to pass to function"

    kwargs: Dict = field(default_factory=dict)
    "Kwargs to pass to function"

    slot: Optional[int] = None
    "Slot to setup smurf control for. If None, uses the slot from the environment variable 'SLOT'"

    run_in_main_process: bool = False
    "If true, run the function in the main process instead of a subprocess."

    def __post_init__(self):
        if self.func_name not in func_map:
            raise ValueError(f"Invalid function name: {self.func_name}")


@dataclass
class RunResult:
    success: bool
    "True if function returned succesfully"

    return_val: any = None
    "Return value from function"

    traceback: Optional[str] = None
    "Traceback if function raised an exception"


class FuncProtocol(protocol.ProcessProtocol):
    """
    Process protocol for running one of the above functions in a subprocess.
    After the subprocess is started, the RunCfg object is encoded and sent to
    the subprocess through stdin. Once the function is finished, the result is
    encoded and passed back through FD 3.
    """

    def __init__(self, cfg: RunCfg):
        self.cfg = cfg
        self.result = None

    def connectionMade(self):
        data = encode_dataclass(self.cfg)
        self.transport.write(data)
        self.transport.closeStdin()

    def childDataReceived(self, childFD, data):
        if childFD in [1, 2]:  # stdout or stderr:
            print(data.decode())

        if childFD == 3:
            self.result = json.loads(data.decode())

    def processExited(self, status):
        if self.result is None:
            raise RuntimeError("No result received from child process")

        self.deferred.callback(self.result)


@defer.inlineCallbacks
def _run_smurf_func_reactor(cfg: RunCfg) -> RunResult:
    """Helper function for run_smurf_func, that can assume reactor context"""
    prot = FuncProtocol(cfg)
    prot.deferred = defer.Deferred()
    childFDs = {0: 'w', 1: 'r', 2: 'r', 3: 'r'}  # Regular FDs plus 3 for sending results back
    env = os.environ.copy()
    if cfg.slot is not None:
        env['SLOT'] = str(cfg.slot)
    reactor.spawnProcess(
        prot, sys.executable, [sys.executable, '-u', __file__], childFDs=childFDs,
        env=env
    )
    result = yield prot.deferred
    return RunResult(**result)


def run_smurf_func(cfg: RunCfg) -> RunResult:
    """
    This function takes a RunCfg object, and runs the specified function in a
    subprocess. The result is returned as a RunResult object. This function
    must be run in a worker thread.

    Args
    -----
    cfg: RunCfg
        Configuration object to specify the function to run, and the arguments.
    """
    if cfg.run_in_main_process:
        try:
            result = RunResult(
                success=True,
                return_val=func_map[cfg.func_name](*cfg.args, **cfg.kwargs)
            )
        except Exception:
            exc = traceback.format_exc()
            print(f"Exception raised in smurf_func:\n{exc}")
            result = RunResult(
                success=False,
                traceback=exc,
            )
        return result

    return threads.blockingCallFromThread(
        reactor, _run_smurf_func_reactor, cfg)


def subprocess_main():
    """
    Starting point for subprocesses. Reads configuration info from stdin,
    runs the specified function, and returns the encoded result object through
    FD 3.
    """
    data = sys.stdin.read()
    cfg = RunCfg(**json.loads(data))
    print(f'Starting subprocess function call:\n {cfg}')
    try:
        return_val = func_map[cfg.func_name](*cfg.args, **cfg.kwargs)
        result = RunResult(success=True, return_val=return_val)
        return_data = encode_dataclass(result)
    except Exception:
        exc = traceback.format_exc()
        print(f"Exception raised in subprocess:\n{exc}")
        result = RunResult(
            success=False,
            traceback=exc,
        )
        return_data = encode_dataclass(result)
    os.write(3, return_data)


if __name__ == '__main__':
    subprocess_main()
