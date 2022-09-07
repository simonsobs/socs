package_name = 'socs'
agents = {
    'ACUAgent': {'module': 'socs.agents.acu.agent', 'entry_point': 'main'},
    'BlueforsAgent': {'module': 'socs.agents.bluefors.agent', 'entry_point': 'main'},
    'CryomechCPAAgent': {'module': 'socs.agents.cryomech_cpa.agent', 'entry_point': 'main'},
    'FTSAerotechAgent': {'module': 'socs.agents.fts_aerotech.agent', 'entry_point': 'main'},
    'Lakeshore240Agent': {'module': 'socs.agents.lakeshore240.agent', 'entry_point': 'main'},
    'Lakeshore372Agent': {'module': 'socs.agents.lakeshore372.agent', 'entry_point': 'main'},
    'RotationAgent': {'module': 'socs.agents.hwp_rotation.agent', 'entry_point': 'main'},
}
