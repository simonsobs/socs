package_name = 'socs'
agents = {
    'ACUAgent': {'module': 'socs.agents.acu.agent', 'entry_point': 'main'},
    'BlueforsAgent': {'module': 'socs.agents.bluefors.agent', 'entry_point': 'main'},
    'CrateAgent': {'module': 'socs.agents.smurf_crate_monitor.agent', 'entry_point': 'main'},
    'CryomechCPAAgent': {'module': 'socs.agents.cryomech_cpa.agent', 'entry_point': 'main'},
    'FTSAerotechAgent': {'module': 'socs.agents.fts_aerotech.agent', 'entry_point': 'main'},
    'HWPBBBAgent': {'module': 'socs.agents.hwp_encoder.agent', 'entry_point': 'main'},
    'Lakeshore240Agent': {'module': 'socs.agents.lakeshore240.agent', 'entry_point': 'main'},
    'Lakeshore336Agent': {'module': 'socs.agents.lakeshore336.agent', 'entry_point': 'main'},
    'Lakeshore370Agent': {'module': 'socs.agents.lakeshore370.agent', 'entry_point': 'main'},
    'Lakeshore372Agent': {'module': 'socs.agents.lakeshore372.agent', 'entry_point': 'main'},
    'Lakeshore425Agent': {'module': 'socs.agents.lakeshore425.agent', 'entry_point': 'main'},
    'LATRtXYStageAgent': {'module': 'socs.agents.xy_stage.agent', 'entry_point': 'main'},
    'MagpieAgent': {'module': 'socs.agents.magpie.agent', 'entry_point': 'main'},
    'PfeifferAgent': {'module': 'socs.agents.pfeiffer_tpg366.agent', 'entry_point': 'main'},
    'PfeifferTC400Agent': {'module': 'socs.agents.pfeiffer_tc400.agent', 'entry_point': 'main'},
    'PysmurfMonitor': {'module': 'socs.agents.pysmurf_monitor.agent', 'entry_point': 'main'},
    'RotationAgent': {'module': 'socs.agents.hwp_rotation.agent', 'entry_point': 'main'},
    'ScpiPsuAgent': {'module': 'socs.agents.scpi_psu.agent', 'entry_point': 'main'},
    'SmurfStreamSimulator': {'module': 'socs.agents.smurf_stream_simulator.agent', 'entry_point': 'main'},
    'SupRsync': {'module': 'socs.agents.suprsync.agent', 'entry_point': 'main'},
    'SynaccessAgent': {'module': 'socs.agents.synacc.agent', 'entry_point': 'main'},
    'TektronixAWGAgent': {'module': 'socs.agents.tektronix3021c.agent', 'entry_point': 'main'},
    'VantagePro2Agent': {'module': 'socs.agents.vantagepro2.agent', 'entry_point': 'main'},
    'WiregridEncoderAgent': {'module': 'socs.agents.wiregrid_encoder.agent', 'entry_point': 'main'},
    'WiregridKikusuiAgent': {'module': 'socs.agents.wiregrid_kikusui.agent', 'entry_point': 'main'},
}
