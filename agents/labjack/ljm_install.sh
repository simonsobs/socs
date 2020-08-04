#!/bin/sh
tar -zvxf labjack_ljm_software_2019_07_16_x86_64.tar.gz
cd labjack_ljm_software_2019_07_16_x86_64
/bin/sh ./labjack_ljm_installer.run || true
