"""
Register our agents in ocs central.  In order for this script to
be imported by site_config.scan_for_agents(), it must be in the python
path and called something like ocs_plugin_*.
"""

import ocs
import os
root = os.path.abspath(os.path.split(__file__)[0])

for n, f in [
        ('Lakeshore372Agent', 'lakeshore372/LS372_agent.py'),
        ('Lakeshore370Agent', 'lakeshore370/LS370_agent.py'),
        ('Lakeshore240Agent', 'lakeshore240/LS240_agent.py'),
        ('Keithley2230G-PSU', 'keithley2230G-psu/keithley_agent.py'),
        ('PysmurfController', 'pysmurf_controller/pysmurf_controller.py'),
        ('BlueforsAgent', 'bluefors/bluefors_log_tracker.py'),
        ('CryomechCPAAgent', 'cryomech_cpa/cryomech_cpa_agent.py'),
        ('LATRtXYStageAgent', 'xy_stage/xy_latrt_agent.py'),
        ('ACUAgent', 'acu/acu_agent.py'),
        ('FTSAerotechAgent', 'fts_aerotech_stage/fts_aerotech_agent.py'),
        ('VantagePro2Agent', 'vantagePro2_agent/vantage_pro2_agent.py'),
        ('HWPPicoscopeAgent', 'hwp_picoscope/pico_agent.py'),
        ('FPGAAgent', 'holo_fpga/roach_agent.py'),
        ('SynthAgent', 'holo_synth/synth_agent.py'),
        ('SupRsync', 'suprsync/suprsync.py'),
]:
    ocs.site_config.register_agent_class(n, os.path.join(root, f))
