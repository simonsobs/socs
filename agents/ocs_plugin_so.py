"""
Register our agents in ocs central.  In order for this script to
be imported by site_config.scan_for_agents(), it must be in the python
path and called something like ocs_plugin_*.
"""

import ocs
import os
root = os.path.abspath(os.path.split(__file__)[0])

for n,f in [
        ('BlueforsAgent', 'bluefors/bluefors_log_tracker.py'),
        ('HWPBBBAgent', 'chwp/hwpbbb_agent.py'),
        ('CryomechCPAAgent', 'cryomech_cpa/cryomech_cpa_agent.py'),
        ('HWPSimulatorAgent', 'hwp_sim/hwp_simulator_agent.py'),
        ('LabJackAgent', 'labjack/labjack_agent.py'),
        ('Lakeshore240Agent', 'lakeshore240/LS240_agent.py'),
        ('Lakeshore372Agent', 'lakeshore372/LS372_agent.py'),
        ('MeinbergM1000Agent', 'meinberg_m1000/meinberg_m1000_agent.py'),
        ('PfeifferAgent', 'pfeiffer_tpg366/pgeiffer_tpg366_agent.py'),
        ('PysmurfArchiverAgent', 'pysmurf_archiver/pysmurf_archiver_agent.py'),
        ('PysmurfController', 'pysmurf_controller/pysmurf_controller.py'),
        ('PysmurfMonitor', 'pysmurf_monitor/pysmurf_monitor.py'),
        ('ScpiPsuAgent', 'scpi_psu/scpi_psu_agent.py'),
        ('CrateAgent', 'smurf_crate_monitor/smurf_crate_monitor.py'),
        ('SmurfRecorder', 'smurf_recorder/smurf_recorder.py'),
        ('SmurfStreamSimulator', 'smurf_stream_simulator/smurf_stream_simulator.py'),
        ('SynAccAgent', 'synacc/synacc.py'),
        ('TektronixAWGAgent', 'tektronix3021c/tektronix_agent.py'),
]:
    ocs.site_config.register_agent_class(n, os.path.join(root, f))
