import os
from unittest import mock

import numpy as np
import pytest
import txaio
from ocs.ocs_agent import OpSession

from socs.agents.pysmurf_controller.agent import PysmurfController, make_parser

os.environ['SLOT'] = '2'

txaio.use_twisted()

# Number of channels in mock pysmurf system
NCHANS = 1000


# Mocks and fixures
def mock_pysmurf(*args, **kwargs):
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
    S.C.writepv = ''
    S.get_cryo_card_relays.return_value = 80000
    S._rtm_slow_dac_bit_to_volt = (2 * 10. / (2**20))
    S._rtm_slow_dac_nbits = 20
    S.rtm_spi_max_root = ''
    S._rtm_slow_dac_data_array_reg = ''
    S.get_tes_bias_bipolar.return_value = 10.
    S.get_tes_bias_bipolar_array.return_value = np.full((12, ), 10.)

    # Mock cfg and edit attributes
    cfg = mock.MagicMock()
    exp_defaults = {
        # General stuff
        'downsample_factor': 20, 'coupling_mode': 'dc', 'synthesis_scale': 1,
        'active_bands': [0, 1, 2, 3, 4, 5, 6, 7],
        'active_bgs': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],

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

        # Biasing
        'rfrac': [0.3, 0.6],
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
    outdict = {'noise_pars': np.zeros((10, 3), dtype=float),
               'bands': 0,
               'channels': 0,
               'band_medians': 0,
               'f': 0,
               'axx': 0,
               'bincenters': 0,
               'lowfn': 0,
               'low_f_10mHz': 0}
    return am, outdict


def mock_ivanalysis(**kwargs):
    """Mock an IVAnalysis (iva) object typically returned by sodetlib
    operations.

    """
    iva = mock.MagicMock()
    # iva.load.return_value = iva
    iva.R = np.full((NCHANS, 12), 1)
    iva.R_n = np.full(NCHANS, 7e-3)
    iva.bgmap = np.zeros(NCHANS)
    iva.v_bias = np.full((12, ), 2)
    return iva


def mock_set_current_mode(S, bgs, mode, const_current=True):
    """mock_set_current_mode()

    **Mock** - Mock set_current_mode() in sodetlib.
    """
    return mock.MagicMock()


def mock_biasstepanalysis():
    """Mock Bias Step Analysis (bsa) object typically returned by sodetlib
    operations.

    """
    bsa = mock.MagicMock()
    bsa.sid = 0
    bsa.filepath = 'bias_step_analysis.npy'
    bsa.bgmap = np.zeros(NCHANS)
    bsa.Rfrac = np.full(NCHANS, 0.5)
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


def mock_uxm_setup(S, cfg, bands, **kwargs):
    """Mock a typical valid response from uxm_relock."""
    summary = {'timestamps': [('setup_amps', 1671048272.6197276),
                              ('load_tune', 1671048272.6274314),
                              ('tracking_setup', 1671048272.6286802),
                              ('noise', 1671048272.7402556),
                              ('end', 1671048272.7404766)],
               'amps': {'success': True},
               'reload_tune': None,
               'tracking_setup_results': mock.MagicMock(),
               'noise': {'noise_pars': 0,
                         'bands': 0,
                         'channels': 0,
                         'band_medians': 0,
                         'f': 0,
                         'axx': 0,
                         'bincenters': 0,
                         'lowfn': 0,
                         'low_f_10mHz': 0,
                         'am': mock.MagicMock()}}
    return True, summary


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('socs.agents.pysmurf_controller.smurf_subprocess_util.get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.operations.uxm_setup.uxm_setup', mock_uxm_setup)
def test_uxm_setup(agent):
    """test_uxm_setup()

    **Test** - Tests uxm_setup task.
    """
    session = create_session('uxm_setup')
    params = {
        'bands': [0], 'kwargs': None, 'run_in_main_process': True
    }
    res = agent.uxm_setup(session, params)
    assert res[0] is True


def mock_uxm_relock(S, cfg, bands, **kwargs):
    """Mock a typical valid response from uxm_relock."""
    summary = {'timestamps': [('setup_amps', 1671048272.6197276),
                              ('load_tune', 1671048272.6274314),
                              ('tracking_setup', 1671048272.6286802),
                              ('noise', 1671048272.7402556),
                              ('end', 1671048272.7404766)],
               'amps': {'success': True},
               'reload_tune': None,
               'tracking_setup_results': mock.MagicMock(),
               'noise': {'noise_pars': 0,
                         'bands': 0,
                         'channels': 0,
                         'band_medians': 0,
                         'f': 0,
                         'axx': 0,
                         'bincenters': 0,
                         'lowfn': 0,
                         'low_f_10mHz': 0,
                         'am': mock.MagicMock()}}

    return True, summary


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('socs.agents.pysmurf_controller.smurf_subprocess_util.get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.operations.uxm_relock.uxm_relock', mock_uxm_relock)
def test_uxm_relock(agent):
    """test_uxm_relock()

    **Test** - Tests uxm_relock task.
    """
    session = create_session('uxm_relock')
    res = agent.uxm_relock(session, {'bands': [0], 'kwargs': None, 'run_in_main_process': True})
    assert res[0] is True


def mock_take_bgmap(S, cfg, **kwargs):
    """Mock a typical valid response from bias_steps.take_bgmap."""
    bsa = mock_biasstepanalysis()
    return bsa


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('socs.agents.pysmurf_controller.smurf_subprocess_util.get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.operations.bias_steps.take_bgmap', mock_take_bgmap)
def test_take_bgmap(agent):
    """test_take_bgmap()

    **Test** - Tests take_bgmap task.
    """
    session = create_session('take_bgmap')
    params = {
        'kwargs': {'high_current_mode': False}, 'tag': None,
        'run_in_main_process': True,
    }
    res = agent.take_bgmap(session, params)
    print(session.data)
    assert res[0] is True
    assert session.data['nchans_per_bg'] == [NCHANS, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert session.data['filepath'] == 'bias_step_analysis.npy'


def mock_take_iv(S, cfg, **kwargs):
    """Mock a typical valid response from iv.take_iv."""
    iva = mock_ivanalysis()
    iva.bands = np.zeros(NCHANS)
    iva.channels = np.arange(NCHANS)
    iva.bgmap = np.zeros(NCHANS)
    iva.filepath = 'test_file.npy'
    return iva


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('socs.agents.pysmurf_controller.smurf_subprocess_util.get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.operations.iv.take_iv', mock_take_iv)
def test_take_iv(agent):
    """test_take_iv()

    **Test** - Tests take_iv task.
    """
    session = create_session('take_iv')
    params = {
        'run_analysis': False, 'kwargs': {'run_analysis': False}, 'tag': None,
        'run_in_main_process': True
    }
    res = agent.take_iv(session, params)
    assert res[0] is True
    assert session.data['filepath'] == 'test_file.npy'


def mock_take_bias_steps(S, cfg, **kwargs):
    """Mock a typical valid response from bias_steps.take_bias_steps."""
    bsa = mock_biasstepanalysis()
    return bsa


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('socs.agents.pysmurf_controller.smurf_subprocess_util.get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.operations.bias_steps.take_bias_steps', mock_take_bias_steps)
def test_take_bias_steps(agent):
    """test_take_bias_steps()

    **Test** - Tests take_bias_steps task.
    """
    session = create_session('take_bias_steps')
    params = {
        'kwargs': None, 'rfrac_range': (0.3, 0.9), 'tag': None,
        'run_in_main_process': True
    }
    res = agent.take_bias_steps(session, params)
    assert res[0] is True
    assert session.data['filepath'] == 'bias_step_analysis.npy'


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.noise.take_noise', mock_take_noise)
@mock.patch('socs.agents.pysmurf_controller.smurf_subprocess_util.get_smurf_control', mock_pysmurf)
@mock.patch('time.sleep', mock.MagicMock())
def test_take_noise(agent):
    """test_take_noise()

    **Test** - Tests take_noise task.
    """
    session = create_session('take_noise')
    params = {
        'duration': 30, 'kwargs': None, 'tag': None,
        'run_in_main_process': True
    }
    res = agent.take_noise(session, params)
    assert res[0] is True


def mock_bias_to_rfrac_range(*args, **kwargs):
    biases = np.full((12,), 10.)
    return biases


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.operations.bias_dets.bias_to_rfrac_range', mock_bias_to_rfrac_range)
def test_bias_dets(agent):
    """test_bias_dets()

    **Test** - Tests bias_dets task.
    """
    session = create_session('bias_dets')
    mm = mock.MagicMock()
    res = agent.bias_dets(session, {'rfrac': None,
                                    'kwargs': {'iva': mock_ivanalysis(S=mm, cfg=mm, run_kwargs=mm,
                                                                      sid=mm, start_times=mm, stop_times=mm)}})
    assert res[0] is True
    assert session.data['biases'] == np.full((12,), 10.).tolist()


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('time.sleep', mock.MagicMock())
def test_stream(agent):
    """test_stream()

    **Test** - Tests stream process.
    """
    session = create_session('stream')
    res = agent.stream(session, {'duration': None, 'load_tune': False,
                                 'kwargs': None, 'test_mode': True, 'tag': None,
                                 'stream_type': 'obs', 'subtype': None})
    assert res[0] is True


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('time.sleep', mock.MagicMock())
def test_check_state(agent):
    """test_check_state()

    **Test** - Tests check_state process.
    """
    session = create_session('check_state')
    res = agent.check_state(session, {'poll_interval': 10, 'test_mode': True})
    assert res[0] is True


def mock_overbias_dets(S, cfg, **kwargs):
    return


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
@mock.patch('sodetlib.overbias_dets', mock_overbias_dets)
def test_overbias_tes(agent):
    """test_overbias_tes()

    **Test** - Tests overbias_tes task.
    """
    session = create_session('overbias_tes')
    res = agent.overbias_tes(session, {'bgs': [0, 1, 2], 'kwargs': None})
    assert res[0] is True


@mock.patch('socs.agents.pysmurf_controller.agent.PysmurfController._get_smurf_control', mock_pysmurf)
def test_all_off(agent):
    """test_all_off()

    **Test** - Tests the all_off task.
    """
    session = create_session('overbias_tes')
    res = agent.all_off(session, {'disable_amps': True, 'disable_tones': True})
    assert res[0] is True
