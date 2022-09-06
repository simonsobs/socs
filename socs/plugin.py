package_name = 'socs'
agents = {
    'ACUAgent': {'module': 'socs.agents.acu.agent', 'entry_point': 'main'},
    'BlueforsAgent': {'module': 'socs.agents.bluefors.agent', 'entry_point': 'main'},
    'CryomechCPAAgent': {'module': 'socs.agents.cryomech_cpa.agent', 'entry_point': 'main'},
    'FTSAerotechAgent': {'module': 'socs.agents.fts_aerotech.agent', 'entry_point': 'main'},
}
