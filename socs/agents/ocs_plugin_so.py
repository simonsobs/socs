"""
Register our agents in ocs central.  In order for this script to
be imported by site_config.scan_for_agents(), it must be in the python
path and called something like ocs_plugin_*.
"""

import os

import ocs

root = os.path.abspath(os.path.split(__file__)[0])

for n, f in [
        ('ACUAgent', 'acu/agent.py'),
        ('BlueforsAgent', 'bluefors/agent.py'),
        ('CrateAgent', 'smurf_crate_monitor/agent.py'),
        ('CryomechCPAAgent', 'cryomech_cpa/agent.py'),
        ('FPGAAgent', 'holo_fpga/agent.py'),
        ('FTSAerotechAgent', 'fts_aerotech/agent.py'),
        ('HWPBBBAgent', 'hwp_encoder/agent.py'),
        ('HWPPicoscopeAgent', 'hwp_picoscope/agent.py'),
        ('ibootbarAgent', 'ibootbar/agent.py'),
        ('LabJackAgent', 'labjack/agent.py'),
        ('Lakeshore240Agent', 'lakeshore240/agent.py'),
        ('Lakeshore336Agent', 'lakeshore336/agent.py'),
        ('Lakeshore370Agent', 'lakeshore370/agent.py'),
        ('Lakeshore372Agent', 'lakeshore372/agent.py'),
        ('Lakeshore425Agent', 'lakeshore425/agent.py'),
        ('LATRtXYStageAgent', 'xy_stage/agent.py'),
        ('MagpieAgent', 'magpie/agent.py'),
        ('MeinbergM1000Agent', 'meinberg_m1000/agent.py'),
        ('PfeifferAgent', 'pfeiffer_tpg366/agent.py'),
        ('PfeifferTC400Agent', 'pfeiffer_tc400/agent.py'),
        ('PysmurfController', 'pysmurf_controller/agent.py'),
        ('PysmurfMonitor', 'pysmurf_monitor/agent.py'),
        ('RotationAgent', 'hwp_rotation/agent.py'),
        ('ScpiPsuAgent', 'scpi_psu/agent.py'),
        ('SmurfFileEmulator', 'smurf_file_emulator/agent.py'),
        ('SmurfStreamSimulator', 'smurf_stream_simulator/agent.py'),
        ('SupRsync', 'suprsync/agent.py'),
        ('SynaccessAgent', 'synacc/agent.py'),
        ('SynthAgent', 'holo_synth/agent.py'),
        ('TektronixAWGAgent', 'tektronix3021c/agent.py'),
        ('ThorlabsMC2000BAgent', 'thorlabs_mc2000b/agent.py'),
        ('VantagePro2Agent', 'vantagepro2/agent.py'),
        ('WiregridActuatorAgent', 'wiregrid_actuator/agent.py'),
        ('WiregridEncoderAgent', 'wiregrid_encoder/agent.py'),
        ('WiregridKikusuiAgent', 'wiregrid_kikusui/agent.py'),
]:
    ocs.site_config.register_agent_class(n, os.path.join(root, f))
