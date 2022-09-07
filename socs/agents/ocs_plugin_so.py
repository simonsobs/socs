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
        ('CryomechCPAAgent', 'cryomech_cpa/agent.py'),
        ('FTSAerotechAgent', 'fts_aerotech/agent.py'),
        ('Lakeshore240Agent', 'lakeshore240/agent.py'),
        ('Lakeshore336Agent', 'lakeshore336/agent.py'),
        ('Lakeshore370Agent', 'lakeshore370/agent.py'),
        ('Lakeshore372Agent', 'lakeshore372/agent.py'),
        ('Lakeshore425Agent', 'lakeshore425/agent.py'),
        ('RotationAgent', 'hwp_rotation/agent.py'),
]:
    ocs.site_config.register_agent_class(n, os.path.join(root, f))
