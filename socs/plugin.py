package_name = 'socs'
agents = {
    'ACUAgent': {'module': 'socs.agents.acu.agent', 'entry_point': 'main'},
    'BLHAgent': {'module': 'socs.agents.orientalmotor_blh.agent', 'entry_point': 'main'},
    'BlueforsAgent': {'module': 'socs.agents.bluefors.agent', 'entry_point': 'main'},
    'CrateAgent': {'module': 'socs.agents.smurf_crate_monitor.agent', 'entry_point': 'main'},
    'CryomechCPAAgent': {'module': 'socs.agents.cryomech_cpa.agent', 'entry_point': 'main'},
    'dS378Agent': {'module': 'socs.agents.devantech_dS378.agent', 'entry_point': 'main'},
    'FPGAAgent': {'module': 'socs.agents.holo_fpga.agent', 'entry_point': 'main'},
    'FlowmeterAgent': {'module': 'socs.agents.ifm_sbn246_flowmeter.agent', 'entry_point': 'main'},
    'FTSAerotechAgent': {'module': 'socs.agents.fts_aerotech.agent', 'entry_point': 'main'},
    'GeneratorAgent': {'module': 'socs.agents.generator.agent', 'entry_point': 'main'},
    'Hi6200Agent': {'module': 'socs.agents.hi6200.agent', 'entry_point': 'main'},
    'HTTPCameraAgent': {'module': 'socs.agents.http_camera.agent', 'entry_point': 'main'},
    'HWPBBBAgent': {'module': 'socs.agents.hwp_encoder.agent', 'entry_point': 'main'},
    'HWPGripperAgent': {'module': 'socs.agents.hwp_gripper.agent', 'entry_point': 'main'},
    'HWPPCUAgent': {'module': 'socs.agents.hwp_pcu.agent', 'entry_point': 'main'},
    'HWPPicoscopeAgent': {'module': 'socs.agents.hwp_picoscope.agent', 'entry_point': 'main'},
    'HWPPIDAgent': {'module': 'socs.agents.hwp_pid.agent', 'entry_point': 'main'},
    'HWPPMXAgent': {'module': 'socs.agents.hwp_pmx.agent', 'entry_point': 'main'},
    'HWPSupervisor': {'module': 'socs.agents.hwp_supervisor.agent', 'entry_point': 'main'},
    'ibootbarAgent': {'module': 'socs.agents.ibootbar.agent', 'entry_point': 'main'},
    'LabJackAgent': {'module': 'socs.agents.labjack.agent', 'entry_point': 'main'},
    'Lakeshore240Agent': {'module': 'socs.agents.lakeshore240.agent', 'entry_point': 'main'},
    'Lakeshore336Agent': {'module': 'socs.agents.lakeshore336.agent', 'entry_point': 'main'},
    'Lakeshore370Agent': {'module': 'socs.agents.lakeshore370.agent', 'entry_point': 'main'},
    'Lakeshore372Agent': {'module': 'socs.agents.lakeshore372.agent', 'entry_point': 'main'},
    'Lakeshore425Agent': {'module': 'socs.agents.lakeshore425.agent', 'entry_point': 'main'},
    'LATRtXYStageAgent': {'module': 'socs.agents.xy_stage.agent', 'entry_point': 'main'},
    'LDMonitorAgent': {'module': 'socs.agents.ld_monitor.agent', 'entry_point': 'main'},
    'MagpieAgent': {'module': 'socs.agents.magpie.agent', 'entry_point': 'main'},
    'MeinbergM1000Agent': {'module': 'socs.agents.meinberg_m1000.agent', 'entry_point': 'main'},
    'MeinbergSyncboxAgent': {'module': 'socs.agents.meinberg_syncbox.agent', 'entry_point': 'main'},
    'PCR500MAAgent': {'module': 'socs.agents.kikusui_pcr500ma.agent', 'entry_point': 'main'},
    'PfeifferAgent': {'module': 'socs.agents.pfeiffer_tpg366.agent', 'entry_point': 'main'},
    'PfeifferTC400Agent': {'module': 'socs.agents.pfeiffer_tc400.agent', 'entry_point': 'main'},
    'PysmurfController': {'module': 'socs.agents.pysmurf_controller.agent', 'entry_point': 'main'},
    'PysmurfMonitor': {'module': 'socs.agents.pysmurf_monitor.agent', 'entry_point': 'main'},
    'RTSPCameraAgent': {'module': 'socs.agents.rtsp_camera.agent', 'entry_point': 'main'},
    'ScpiPsuAgent': {'module': 'socs.agents.scpi_psu.agent', 'entry_point': 'main'},
    'SmurfFileEmulator': {'module': 'socs.agents.smurf_file_emulator.agent', 'entry_point': 'main'},
    'SmurfStreamSimulator': {'module': 'socs.agents.smurf_stream_simulator.agent', 'entry_point': 'main'},
    'SmurfTimingCardAgent': {'module': 'socs.agents.smurf_timing_card.agent', 'entry_point': 'main'},
    'SupRsync': {'module': 'socs.agents.suprsync.agent', 'entry_point': 'main'},
    'SynaccessAgent': {'module': 'socs.agents.synacc.agent', 'entry_point': 'main'},
    'SynthAgent': {'module': 'socs.agents.holo_synth.agent', 'entry_point': 'main'},
    'TektronixAWGAgent': {'module': 'socs.agents.tektronix3021c.agent', 'entry_point': 'main'},
    'ThorlabsMC2000BAgent': {'module': 'socs.agents.thorlabs_mc2000b.agent', 'entry_point': 'main'},
    'UCSCRadiometerAgent': {'module': 'socs.agents.ucsc_radiometer.agent', 'entry_point': 'main'},
    'UPSAgent': {'module': 'socs.agents.ups.agent', 'entry_point': 'main'},
    'VantagePro2Agent': {'module': 'socs.agents.vantagepro2.agent', 'entry_point': 'main'},
    'WiregridActuatorAgent': {'module': 'socs.agents.wiregrid_actuator.agent', 'entry_point': 'main'},
    'WiregridEncoderAgent': {'module': 'socs.agents.wiregrid_encoder.agent', 'entry_point': 'main'},
    'WiregridKikusuiAgent': {'module': 'socs.agents.wiregrid_kikusui.agent', 'entry_point': 'main'},
    'WiregridTiltSensorAgent': {'module': 'socs.agents.wiregrid_tiltsensor.agent', 'entry_point': 'main'},
}
