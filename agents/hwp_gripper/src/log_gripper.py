# Built-in python modules
import time as tm
import datetime as dt
import os


class Logging:
    """ The Logging object saves logging messages """
    def __init__(self):
        now = dt.datetime.now()
        date = "%04d_%02d_%02d" % (now.year, now.month, now.day)
        fname = "log_%s.txt" % (date)
        log_dir = os.path.join(os.path.dirname(__file__), "..", "LOG")
        f = os.path.join(log_dir, fname)
        if os.path.exists(f):
            self._log_file = open(f, 'a')
        else:
            self._log_file = open(f, 'w')
        self.log("Logging to file '%s'" % (f))

    def __del__(self):
        self._log_file.close()

    # ***** Public Methods *****
    def log(self, msg):
        print(msg)
        wrmsg = self._wrmsg(msg)
        self._log_file.write(wrmsg + '\n')
        return

    def err(self, msg):
        wrmsg = self._wrmsg(msg)
        self._log_file.write(wrmsg + '\n')
        print(wrmsg)
        return

    def out(self, msg):
        wrmsg = self._wrmsg(msg)
        self._log_file.write(wrmsg + '\n')
        print(wrmsg)
        return

    # ***** Helper Methods *****
    def _wrmsg(self, msg):
        now = dt.datetime.now()
        wrmsg = (
            "[%04d-%02d-%02d %02d:%02d:%02d] %s"
            % (now.year, now.month, now.day, now.hour,
               now.minute, now.second, msg))
        return wrmsg
