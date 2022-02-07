import sys
sys.path.insert(0, '../agents/')
import ocs_plugin_so


def test_agent_script_reg():
    reg = ocs_plugin_so.ocs.site_config.agent_script_reg
    print(reg)
    assert reg != {}
