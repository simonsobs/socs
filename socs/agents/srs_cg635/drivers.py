# This device uses the Prologix GPIB interface
from socs.common.prologix_interface import PrologixInterface


class SRSCG635Interface(PrologixInterface):
    """
    This device driver is written for the SRS CG635 clock used for the timing system.
    """

    def __init__(self, ip_address, gpibAddr, verbose=False, **kwargs):
        self.verbose = verbose
        super().__init__(ip_address, gpibAddr, **kwargs)

    def get_freq(self):
        """
        Queries the clock for its current output frequency in Hz.

        Returns the frequency as a float.
        """

        self.write("FREQ?")
        freq = self.read()

        return float(freq)

    def get_stdc(self):
        """
        Queries the clock for the current Standard CMOS (STDC) output setting.

        The query returns an int with the int representing the CMOS output setting.
        The outputs are represented in volts between the CMOS low and CMOS high with CMOS low = 0V.

        The standard CMOS output settings this query can return are are::

            -1 = Not a standard CMOS Output
             0 = 1.2V
             1 = 1.8V
             2 = 2.5V
             3 = 3.3V (The default for our current setup)
             4 = 5.0V

        """

        self.write("STDC?")
        stdc = self.read()

        return int(stdc)

    def get_runs(self):
        """
        Queries the clock for the current Running State (RUNS).

        Returns an int which represents the following running states::

            0 = Not Running (Output is off)
            1 = Running (Output is on)

        """

        self.write("RUNS?")
        runs = self.read()

        return int(runs)

    def get_timebase(self):
        """
        Queries the clock for the current timebase (TIMB).

        Returns an int which represents the following states::

            0 = Internal timebase
            1 = OCXO timebase
            2 = Rubidium timebase
            3 = External timebase

        """

        self.write("TIMB?")
        timb = self.read()

        return int(timb)

    def get_lock_statuses(self):
        """
        Queries the clock for the Lock Status Registers (LCKR).

        The lock registers represent whether the bits have been set since the
        register was last read for following registers::

            RF_UNLOCK
            19MHZ_UNLOCK
            10MHZ_UNLOCK
            RB_UNLOCK
            OUT_DISABLED
            PHASE_SHIFT

        Returns a dict of the registers and registers statuses with the keys being
        the registers and the values being an int representing the register changes::

            0 = False (this register has NOT changed since the last read)
            1 = True (this register has changed since the last read)

        """
        self.write("LCKR?")
        lckr = self.read()

        # The LCKR is a 8 bit register with each register status represented by a single bit.
        # The LCKR? query returns a single int representation of the register bits
        # The decode_lckr function finds the register bit for all registers
        lckr_status = self._decode_lckr(lckr)

        return lckr_status

    def _decode_lckr(self, lckr):
        """
        Takes the int representation of the lock register (lckr) and translates it into dict form.
        The dict keys are the register names and the values are the register status::
            0 = False
            1 = True

        The incoming lckr int should always be <256 because its a int representation of an 8 bit reigster.

        The lock register bits are as follows::
            0 = RF_UNLOCK
            1 = 19MHZ_UNLOCK
            2 = 10MHZ_UNLOCK
            3 = RB_UNLOCK
            4 = OUT_DISABLED
            5 = PHASE_SHIFT
            6 = Reserved
            7 = Reserved
        """

        registers = {"RF_UNLOCK": None,
                     "19MHZ_UNLOCK": None,
                     "10MHZ_UNLOCK": None,
                     "RB_UNLOCK": None,
                     "OUT_DISABLED": None,
                     "PHASE_SHIFT": None}

        try:
            lckr = int(lckr)

            if not 0 <= lckr <= 255:
                # If the lckr register is outside of an 8 bit range
                raise ValueError

            # Decode the lckr int by performing successive int division and subtractionof 2**(5-i)
            for i, register in enumerate(list(registers)[::-1]):
                register_bit = int(lckr / (2**(5 - i)))
                registers[register] = int(register_bit)
                lckr -= register_bit * (2**(5 - i))

        except ValueError:
            print("Invalid LCKR returned, cannot decode")

        return registers
