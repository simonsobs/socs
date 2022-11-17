import socs.agents.ocs_plugin_so as ocs_plugin_so


def test_agent_script_reg():
    reg = ocs_plugin_so.ocs.site_config.agent_script_reg
    print(reg)
    assert reg != {}
