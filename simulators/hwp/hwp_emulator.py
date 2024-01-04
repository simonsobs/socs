"""
HWP Emulation module
"""
import logging
import threading
import time
from copy import deepcopy
from dataclasses import dataclass

from socs.testing import device_emulator


def hex_str_to_dec(hex_value, decimal=3):
    """Converts a hex string to a decimal float"""
    return float(int(hex_value, 16)) / 10**decimal


def float_to_hex_str(value, decimal=3):
    """Converts a decimal float to a hex string"""
    return "0000" + str(hex(int(value * 10**decimal)))[2:]


@dataclass
class PMXState:
    output: bool = False
    current: float = 0
    current_limit: float = 10.0
    voltage_limit: float = 10.0
    voltage: float = 0
    source: str = "volt"


@dataclass
class PIDState:
    direction: str = "forward"
    freq_setpoint: float = 0.0


@dataclass
class HWPState:
    cur_freq: float = 0.0
    pmx: PMXState = PMXState()
    pid: PIDState = PIDState()
    lock = threading.Lock()


def _create_logger(name, log_level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    formatter = logging.Formatter("%(name)s: %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def lerp(start, end, t):
    return (1 - t) * start + t * end


class HWPEmulator:
    def __init__(self, pid_addr=("localhost", 8003), pmx_addr=("localhost", 8004)):
        self.pid_addr = pid_addr
        self.pmx_addr = pmx_addr

        self.state = HWPState()

        self.pid_device = device_emulator.DeviceEmulator([])
        self.pid_device._get_response = self.process_pid_msg
        self.pid_device.logger = _create_logger("PID")

        self.pmx_device = device_emulator.DeviceEmulator([])
        self.pmx_device._get_response = self.process_pmx_msg
        self.pmx_device.logger = _create_logger("PMX")

        self.logger = _create_logger("HWP")

    def start(self):
        """Start up TCP Sockets"""
        self.pid_device.create_tcp_relay(self.pid_addr[1])
        self.pmx_device.create_tcp_relay(self.pmx_addr[1])

    def shutdown(self):
        """Shutdown TCP Sockets"""
        self.pid_device.shutdown()
        self.pmx_device.shutdown()

    def update(self):
        """Update HWP state"""
        s = self.state
        with s.lock:
            if s.pmx.source == "volt":
                s.cur_freq = lerp(s.cur_freq, s.pid.freq_setpoint, 0.3)

    def process_pmx_msg(self, data):
        """Process messages for PMX emulator"""
        cmd = data.split(" ")[0].strip()
        self.logger.debug(cmd)
        with self.state.lock:

            # Output commands
            if cmd == 'output':
                val = int(data.split(" ")[1].strip())
                self.logger.info("Setting output to %d", val)
                self.state.pmx.output = bool(val)
            elif cmd == 'output:protection:clear':
                self.logger.info("Commanded to clear alarms")
            elif cmd == 'output?':
                return str(int(self.state.pmx.output))

            # Current (limit) commands
            elif cmd == 'curr':
                val = float(data.split(" ")[1].strip())
                self.logger.info("Setting current to %.3f", val)
                self.state.pmx.current = val
            elif cmd == 'curr:prot':
                val = float(data.split(" ")[1].strip())
                self.logger.info("Setting current limit to %.3f", val)
                self.state.pmx.current_limit = val
            elif cmd == 'curr?':
                return f"{self.state.pmx.current}\n"
            elif cmd == 'curr:prot?':
                return f"{self.state.pmx.current_limit}\n"
            elif cmd == "meas:curr?":
                return f"{self.state.pmx.current}\n"

            # Voltage (limit) commands
            elif cmd == 'volt':
                val = float(data.split(" ")[1].strip())
                self.logger.info("Setting current to %.3f", val)
                self.state.pmx.voltage = val
            elif cmd == 'volt:prot':
                val = float(data.split(" ")[1].strip())
                self.logger.info("Setting voltage limit to %.3f", val)
                self.state.pmx.voltage_limit = val
            elif cmd == 'volt:prot?':
                return f"{self.state.pmx.voltage_limit}\n"
            elif cmd == 'volt?':
                return f"{self.state.pmx.voltage}\n"
            elif cmd == "meas:volt?":
                return f"{self.state.pmx.voltage}\n"

            # Error codes
            elif cmd == ':system:error?': # Error codes
                return '0,"No error"\n'
            elif cmd == 'stat:ques?': # Status Codes
                return '0'
            elif cmd == 'volt:ext:sour?':
                return f'{self.state.pmx.source}\n'
            else:
                self.logger.info("Unknown cmd: %s", data)
                if "?" in cmd:
                    return "unknown"

    def process_pid_msg(self, data):
        """Process messages for PID emulator"""
        logger = self.pid_device.logger
        cmd = data.split(" ")[0].strip()
        with self.state.lock:
            # self.logger.debug(cmd)
            if cmd == "*W02400000":
                self.state.pid.direction = "forward"
                logger.info("Setting direction: forward")
                return "asdfl"
            elif cmd == "*W02401388":
                self.state.pid.direction = "reverse"
                logger.info("Setting direction: reverse")
                return "asdfl"
            elif cmd.startswith("*W014"):
                setpt = hex_str_to_dec(cmd[5:], 3)
                logger.info("SETPOINT %s Hz", setpt)
                self.state.pid.freq_setpoint = setpt
                return "sdflsf"
            elif cmd == "*X01":  # Get frequency
                return f"X01{self.state.cur_freq:0.3f}"
            elif cmd == "*R01":  # Get Target
                return f"R{float_to_hex_str(self.state.pid.freq_setpoint, 3)}"
            else:
                self.logger.info("Unknown cmd: %s", cmd)
                return "unknown"


try:
    # pmx_server = PMXEmulator('localhost', 8002)
    hwp_em = HWPEmulator()
    hwp_em.start()

    while True:
        hwp_em.update()
        time.sleep(1)
finally:
    hwp_em.shutdown()
