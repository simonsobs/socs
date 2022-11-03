# HP 8563E Spectrum Analyzer: Output Trace Data

__author__ = "Christopher Ellis"
__editor__ = "Max Silva-Feaver"
__producer__ = "Arnold Lab"
__license__ = "UCSD"
__version__ = "Release 1.3.9"

"""
----------------------------------------

This is basic code to control the:

    HP8563E Spectrum Analyzer
    Agilent 83752A Synthesized Sweeper
    Anrutsu Vector Network Analyzer

*The spectrum analyzer and RF synthesizer can be controlled on LINUX.
*The VNA MUST be controlled using WINDOWS (todo: pyVISA on LINUX Mint)

----------------------------------------

CHECK YOUR CONNECTIONS AND NETWORK SETTINGS!
CHANGING THE ETHERNET CABLE PORT CONNECTIONS AND SWAPPING BETWEEN LINUX/WINDOWS MAY CHANGE SETTINGS

    For Ethernet-GPIB connections:
            Add          Netmask         Gateway
        192.168.1.1 | 255.255.255.0 | 255.255.255.0

    For Ethernet-VNA connection:
            Add             Netmask         Gateway
        169.254.166.83 | 255.255.255.0 | -------------

    Internet connection: Automatic IPv4

    Linux: Possible need to reset the network.
           In terminal $ sudo systemctl restart NetworkManager.service

---------------------------------------

Helpful code and definitions to use:

    To use this code:

        import interfaceMedley as intmed

    Linux Terminal:

        anaconda-navigator

        cd ~/ucsd_lab_software/prologix
----------------------------------------

        For controlling the RF Synthesizer/Sweeper:

            intmed.rf_powerON() - sets the RF signal output state to ON.

            intmed.rf_powerOFF() - sets the RF signal output state to OFF.

            intmed.rf_cwFrequency("5 GHZ") - sets the continuous wave frequency.

            intmed.rf_amplitude("-2 dBm") - sets the RF signal amplitude.

----------------------------------------

Writing your own modules; how to use prologixInterface.py

    Three basic functions to use:

        prologixInterface.connect()
            Connects and verifys integrity of connected devices (using GPIB), prevents front
            panel access on the connected devices.

        prologixInterface.writeGpib(Gpib_Adress,"Command")
            Commands from the device with Gpib_Address, a specific "Command".
            Commands will be syntax specific to its device, and can be found in the
            programming manual/section of the device (it will be a copy and paste of
            the provided BASIC argument).

        prologixInterface.read()
            Returns/Queries the data most previously rememebered by device. Example: Use
            the writeGpib() function to ask for the starting frequency, use the read()
            function to return this starting frequency value (to print, store, etc.)

        See pyVISA documentation and VNA programming manual for VNA interfacing.

    Spectrum anlyzer has address 19
    RF synthesizer has address 28

    User and programming manuals for all instruments can be found in the prologix\\Manuals folder.

    Questions and Comments: Christopher Ellis, chellis@ucsd.edu or harleyellis5@gmail.com

---------------------------------------
"""

import time

from prologixInterface import prologixInterface


# Connects to HP8563E spectrum analyzer and Agilent 83752A via Prologix Interface
# Example use: --> pi.writeGpib(19,"CF 10MHZ;SP 10GHZ;TDF P;TRA?;AUNITS?;")
#       then: --> pi.read()
class agilentRFInterface:

    def __init__(self, ip_address, gpib_address):

        self.ip_address = ip_address
        self.gpib_address = gpib_address

        self.connect()

    def connect(self):
        self.session = prologixInterface(self.ip_address, self.gpib_address)
        self.session.connSocket()  # Connect to agilent83752A

    def identify(self):
        self.session.write('*idn?')
        return self.session.read()

    # Changes the continuous wave frequency of the RF synthesizer; intmed.rf_cwFrequency("3 MHZ")

    def set_cwFrequency(self, contWave0):

        contWave = "FREQ:CW " + str(contWave0)  # Want pi.writeGpib(28,"FREQ:CW 3 MHZ")
        self.session.write(contWave)

        # pi.write("FREQ:CW?")
        #actualContWave = pi.read()

        #print("Continuous Wave frequency set to", actualContWave + " HZ")

        return

    # Changes the RF synthesizer output amplitude of the RF synthesizer; intmed.rf_amplitude("-5 dBm")
    def set_power(self, amp0):
        amp = "POWER:LEVEL " + str(amp0)
        self.session.write(amp)  # Want pi.writeGpib(28,"POWER:LEVEL -5 dBm)

        # pi.write("POWER:LEVEL?")
        #actualAmp = pi.read()

        #print("Synthesizer amplitude set to", actualAmp + "dBm")

        return

    # Changes the RF synthesizer signal to an ON output state; intmed.rf_powerON()

    def set_output(self, state):
        self.session.write("POWER:STATE " + str(int(state)))

        #print("RF Output is ON")

        return
