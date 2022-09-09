"""
Register our agents in ocs central.  In order for this script to
be imported by site_config.scan_for_agents(), it must be in the python
path and called something like ocs_plugin_*.
"""

import ocs
import os
root = os.path.abspath(os.path.split(__file__)[0])

for n, f in [
        ('ACUAgent', 'acu/agent.py'),
        ('BlueforsAgent', 'bluefors/agent.py'),
        ('CrateAgent', 'smurf_crate_monitor/agent.py'),
        ('CryomechCPAAgent', 'cryomech_cpa/agent.py'),
        ('FTSAerotechAgent', 'fts_aerotech/agent.py'),
        ('HWPBBBAgent', 'hwp_encoder/agent.py'),
        ('Lakeshore240Agent', 'lakeshore240/agent.py'),
        ('Lakeshore336Agent', 'lakeshore336/agent.py'),
        ('Lakeshore370Agent', 'lakeshore370/agent.py'),
        ('Lakeshore372Agent', 'lakeshore372/agent.py'),
        ('Lakeshore425Agent', 'lakeshore425/agent.py'),
        ('LATRtXYStageAgent', 'xy_stage/agent.py'),
        ('PfeifferAgent', 'pfeiffer_tpg366/agent.py'),
        ('RotationAgent', 'hwp_rotation/agent.py'),
        ('ScpiPsuAgent', 'scpi_psu/agent.py'),
        ('SmurfStreamSimulator', 'smurf_stream_simulator/agent.py'),
        ('SynaccessAgent', 'synacc/agent.py'),
        ('TektronixAWGAgent', 'tektronix3021c/agent.py'),
        ('VantagePro2Agent', 'vantagepro2/agent.py'),
        ('WiregridEncoderAgent', 'wiregrid_encoder/agent.py'),
        ('WiregridKikusuiAgent', 'wiregrid_kikusui/agent.py'),
]:
    ocs.site_config.register_agent_class(n, os.path.join(root, f))
