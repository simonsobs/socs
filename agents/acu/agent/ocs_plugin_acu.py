"""
Register our FakeDataAgent launcher script.
"""

import ocs
import os
root = os.path.abspath(os.path.split(__file__)[0])
ocs.site_config.register_agent_class(
    'ACUAgent', os.path.join(root, 'acu_agent.py'))
