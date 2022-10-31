import sys
sys.path.insert(0, '../agents/pysmurf_controller/')
from pysmurf_controller import PysmurfController, make_parser

from ocs.ocs_agent import OpSession

import pytest
from unittest import mock
import numpy as np

import txaio
txaio.use_twisted()


# Mocks and fixures
def mock_pysmurf(self, session=None, load_tune=False, **kwargs):
    """mock_pysmurf()

    **Mock** - Mock a pysmurf instance. Used to patch _get_smurf_control() in the PysmurfController.

    Returns
    -------
    S : mock.MagicMock()
        Mocked pysmurf instance with defined return values for attributes of S.
    cfg : mock.MagicMock()
        Mocked DetConfig of sodetlib with defined return values for attributes of cfg.
    """

    # Mock S and edit attributes
    S = mock.MagicMock()
    S.C.get_fw_version.return_value = [4, 1, 1]
    S.C.read_ps_en.return_value = 3
    S.C.list_of_c02_amps = ['50k', 'hemt']
    S.C.list_of_c04_amps = ['50k1', '50k2', 'hemt1', 'hemt2']
    S.estimate_phase_delay.side_effect = [[15, 15], [15, 15], [15, 15], [15, 15],
                                          [15, 15], [15, 15], [15, 15], [15, 15]]
    S._pic_to_bias_group = np.array([[0, 0], [1, 1], [2, 2], [3, 3], [4, 4], [5, 5], [6, 6], [7, 7], [8, 8], [9, 9], [10, 10], [11, 11],
                                     [12, 12], [13, 13], [14, 14], [15, 15]])
    S._bias_group_to_pair = np.array([[0, 1, 2], [1, 3, 4], [2, 5, 6], [3, 7, 8], [4, 9, 10], [5, 11, 12], [6, 13, 14], [7, 15, 16],
                                      [8, 17, 18], [9, 19, 20], [10, 21, 22], [11, 23, 24], [12, 25, 26], [13, 27, 28], [14, 29, 30]])
    S._n_bias_groups = 15
    sync_flag_array = []
    tracking_array = []
    for i in range(8):
        sync_flag_array.append([0, 1])
        tracking_array.append([np.array([np.array([0]), np.array([0])]), np.array([np.array([0]), np.array([0])]), np.array([np.array([0]), np.array([0])])])
    S.tracking_setup.side_effect = tracking_array
    S.make_sync_flag.side_effect = sync_flag_array
    S._caget.return_value = 0
    S.high_low_current_ratio = 6.08
    S.C.relay_address = 0x2
    S.get_cryo_card_relays.return_value = 80000
    S._rtm_slow_dac_bit_to_volt = (2 * 10. / (2**20))
    S.get_tes_bias_bipolar.return_value = 10.
    S.get_tes_bias_bipolar_array.return_value = np.full((12, ), 10.)

    # Mock cfg and edit attributes
    cfg = mock.MagicMock()
    exp_defaults = {
        # General stuff
        'downsample_factor': 20, 'coupling_mode': 'dc', 'synthesis_scale': 1,

        # Amp stuff
        "amps_to_bias": ['hemt', 'hemt1', 'hemt2', '50k', '50k1', '50k2'],
        "amp_enable_wait_time": 10.0, "amp_step_wait_time": 0.2,

        "amp_50k_init_gate_volt": -0.5, "amp_50k_drain_current": 15.0,
        "amp_50k_gate_volt": None, "amp_50k_drain_current_tolerance": 0.2,
        "amp_hemt_init_gate_volt": -1.0, "amp_hemt_drain_current": 8.0,
        "amp_hemt_gate_volt": None, "amp_hemt_drain_current_tolerance": 0.2,

        "amp_50k1_init_gate_volt": -0.5, "amp_50k1_drain_current": 15.0,
        "amp_50k1_gate_volt": None, "amp_50k1_drain_current_tolerance": 0.2,
        "amp_50k1_drain_volt": 4,
        "amp_50k2_init_gate_volt": -0.5, "amp_50k2_drain_current": 15.0,
        "amp_50k2_gate_volt": None, "amp_50k2_drain_current_tolerance": 0.2,
        "amp_50k2_drain_volt": 4,

        "amp_hemt1_init_gate_volt": -1.0, "amp_hemt1_drain_current": 8.0,
        "amp_hemt1_gate_volt": None, "amp_hemt1_drain_current_tolerance": 0.2,
        "amp_hemt1_drain_volt": 0.6,
        "amp_hemt2_init_gate_volt": -1.0, "amp_hemt2_drain_current": 8.0,
        "amp_hemt2_gate_volt": None, "amp_hemt2_drain_current_tolerance": 0.2,
        "amp_hemt2_drain_volt": 0.6,

        # Find freq
        'res_amp_cut': 0.01, 'res_grad_cut': 0.01,

        # Tracking stuff
        "flux_ramp_rate_khz": 4, "init_frac_pp": 0.4, "nphi0": 5,
        "f_ptp_range": [10, 200], "df_ptp_range": [0, 50], "r2_min": 0.9,
        "min_good_tracking_frac": 0.8,
        'feedback_start_frac': 0.02, 'feedback_end_frac': 0.98,

        # Misc files
        "tunefile": None, "bgmap_file": None, "iv_file": None,
        "res_fit_file": None,
    }
    cfg.dev.exp.__getitem__.side_effect = exp_defaults.__getitem__

    return S, cfg


def mock_np_save():
    """mock_np_save()

    **Mock** - Mock save() in numpy to avoid actually saving files.
    """
    return mock.MagicMock()


def mock_plt_savefig():
    """mock_plt_savefig()

    **Mock** - Mock savefig() in matplotlib to avoid actually saving figures.
    """
    return mock.MagicMock()


def mock_take_noise(S, cfg, acq_time, **kwargs):
    """mock_take_noise()

    **Mock** - Mock take_noise() in sodetlib.
    """
    am = mock.MagicMock()
    outdict = {'noise_pars': 0,
               'bands': 0,
               'channels': 0,
               'band_medians': 0,
               'f': 0,
               'axx': 0,
               'bincenters': 0,
               'lowfn': 0,
               'low_f_10mHz': 0}
    return am, outdict


def mock_ivanalysis(S, cfg, run_kwargs, sid, start_times, stop_times):
    """mock_ivanalysis()

    **Mock** - Mock IVAnalysis class in sodetlib.
    """
    iva = mock.MagicMock()
    # iva.load.return_value = iva
    iva.R = np.full((2, 12), 1)
    iva.R_n = np.full((2, ), 2)
    iva.bgmap = np.zeros((12, 2))
    iva.v_bias = np.full((12, ), 2)
    return iva


def mock_set_current_mode(S, bgs, mode, const_current=True):
    """mock_set_current_mode()

    **Mock** - Mock set_current_mode() in sodetlib.
    """
    return mock.MagicMock()


def mock_biasstepanalysis(S, cfg, bgs, run_kwargs):
    """mock_biasstepanalysis()

    **Mock** - Mock BiasStepAnalysis class in sodetlib.
    """
    bsa = mock.MagicMock()
    bsa.sid = 0
    bsa.filepath = 'bias_step_analysis.npy'
    bsa.bgmap = np.zeros((12, 2))
    return bsa


def create_session(op_name):
    """Create an OpSession with a mocked app for testing."""
    mock_app = mock.MagicMock()
    session = OpSession(1, op_name, app=mock_app)

    return session


@pytest.fixture
def agent():
    """Test fixture to setup a mocked OCSAgent."""
    mock_agent = mock.MagicMock()
    log = txaio.make_logger()
    txaio.start_logging(level='debug')
    mock_agent.log = log
    log.info('Initialized mock OCSAgent')
    parser = make_parser()
    args = parser.parse_args(args=[
        '--monitor-id', 'pysmurf-controller-s2',
        '--slot', '2',
        '--poll-interval', '10'
    ])
    agent = PysmurfController(mock_agent, args)

    return agent


@mock.patch('pysmurf_controller.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('numpy.save', mock_np_save())
@mock.patch('matplotlib.figure.Figure.savefig', mock_plt_savefig())
@mock.patch('sodetlib.noise.take_noise', mock_take_noise)
@mock.patch('time.sleep', mock.MagicMock())
def test_uxm_setup(agent):
    """test_uxm_setup()

    **Test** - Tests uxm_setup task.
    """
    session = create_session('uxm_setup')
    res = agent.uxm_setup(session, {'bands': [0], 'kwargs': None})
    assert res[0] is True


@mock.patch('pysmurf_controller.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('numpy.save', mock_np_save())
@mock.patch('matplotlib.figure.Figure.savefig', mock_plt_savefig())
@mock.patch('sodetlib.noise.take_noise', mock_take_noise)
@mock.patch('time.sleep', mock.MagicMock())
def test_uxm_relock(agent):
    """test_uxm_relock()

    **Test** - Tests uxm_relock task.
    """
    session = create_session('uxm_relock')
    res = agent.uxm_relock(session, {'bands': [0], 'kwargs': None})
    assert res[0] is True


@mock.patch('pysmurf_controller.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.set_current_mode', mock_set_current_mode)
@mock.patch('sodetlib.operations.bias_steps.BiasStepAnalysis', mock_biasstepanalysis)
@mock.patch('matplotlib.figure.Figure.savefig', mock_plt_savefig())
@mock.patch('time.sleep', mock.MagicMock())
def test_take_bgmap(agent):
    """test_take_bgmap()

    **Test** - Tests take_bgmap task.
    """
    session = create_session('take_bgmap')
    res = agent.take_bgmap(session, {'kwargs': {'high_current_mode': False}})
    assert res[0] is True


@mock.patch('pysmurf_controller.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('matplotlib.figure.Figure.savefig', mock_plt_savefig())
@mock.patch('sodetlib.operations.iv.IVAnalysis', mock_ivanalysis)
@mock.patch('time.sleep', mock.MagicMock())
def test_take_iv(agent):
    """test_take_iv()

    **Test** - Tests take_iv task.
    """
    session = create_session('take_iv')
    res = agent.take_iv(session, {'kwargs': {'run_analysis': False}})
    assert res[0] is True


@mock.patch('pysmurf_controller.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.set_current_mode', mock_set_current_mode)
@mock.patch('sodetlib.operations.bias_steps.BiasStepAnalysis', mock_biasstepanalysis)
@mock.patch('time.sleep', mock.MagicMock())
def test_take_bias_steps(agent):
    """test_take_bias_steps()

    **Test** - Tests take_bias_steps task.
    """
    session = create_session('take_bias_steps')
    res = agent.take_bias_steps(session, {'kwargs': None})
    assert res[0] is True


@mock.patch('pysmurf_controller.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.noise.take_noise', mock_take_noise)
@mock.patch('time.sleep', mock.MagicMock())
def test_take_noise(agent):
    """test_take_noise()

    **Test** - Tests take_noise task.
    """
    session = create_session('take_noise')
    res = agent.take_noise(session, {'duration': 30, 'kwargs': None})
    assert res[0] is True


@mock.patch('pysmurf_controller.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.set_current_mode', mock_set_current_mode)
@mock.patch('time.sleep', mock.MagicMock())
def test_bias_dets(agent):
    """test_bias_dets()

    **Test** - Tests bias_dets task.
    """
    session = create_session('bias_dets')
    mm = mock.MagicMock()
    res = agent.bias_dets(session, {'rfrac': (0.3, 0.6),
                                    'kwargs': {'iva': mock_ivanalysis(S=mm, cfg=mm, run_kwargs=mm,
                                                                      sid=mm, start_times=mm, stop_times=mm)}})
    assert res[0] is True


@mock.patch('pysmurf_controller.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('time.sleep', mock.MagicMock())
def test_stream(agent):
    """test_stream()

    **Test** - Tests stream process.
    """
    session = create_session('stream')
    res = agent.stream(session, {'duration': None, 'load_tune': False, 'kwargs': None, 'test_mode': True})
    assert res[0] is True


@mock.patch('pysmurf_controller.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('time.sleep', mock.MagicMock())
def test_check_state(agent):
    """test_check_state()

    **Test** - Tests check_state process.
    """
    session = create_session('check_state')
    res = agent.check_state(session, {'poll_interval': 10, 'test_mode': True})
    assert res[0] is True
