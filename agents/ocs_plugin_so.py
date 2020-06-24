"""
Register our agents in ocs central.  In order for this script to
be imported by site_config.scan_for_agents(), it must be in the python
path and called something like ocs_plugin_*.
"""

import ocs
import os
root = os.path.abspath(os.path.split(__file__)[0])

for n,f in [
        ('Lakeshore372Agent', 'lakeshore372/LS372_agent.py'),
        ('Lakeshore240Agent', 'lakeshore240/LS240_agent.py'),
        ('Keithley2230G-PSU', 'keithley2230G-psu/keithley_agent.py'),
        ('PysmurfController', 'smurf/pysmurf_control.py'),
        ('BlueforsAgent', 'bluefors/bluefors_log_tracker.py'),
        ('HWPSimulatorAgent', 'hwp_sim/hwp_simulator_agent.py'),
        ('CryomechCPAAgent', 'cryomech_cpa/cryomech_cpa_agent.py'),
]:
    ocs.site_config.register_agent_class(n, os.path.join(root, f))
