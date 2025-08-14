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

    def get_all_status(self):
        self.write("FREQ?;STDC?;RUNS?;TIMB?")
        output = self.read()

        try:
            freq, stdc, runs, timb = output.split(';')
            return float(freq), int(stdc), int(runs), int(timb)
        except ValueError:
            self.clear()
            return self.get_freq(), self.get_stdc(), self.get_runs(), self.get_timebase()

    def clear(self):
        """Clear all the event registers and error queue."""
        self.write("*CLS")
        return True
