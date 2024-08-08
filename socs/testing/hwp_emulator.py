"""
HWP Emulation module
"""
import argparse
import logging
import threading
import time
from dataclasses import dataclass, field

import pytest

from socs.agents.hwp_pid.drivers.pid_controller import PID
from socs.testing import device_emulator


def hex_str_to_dec(hex_value, decimal=3):
    """Converts a hex string to a decimal float"""
    return float(int(hex_value, 16)) / 10**decimal


@dataclass
class PMXState:
    """State of the PMX Emulator"""
    output: bool = False
    current: float = 0
    current_limit: float = 10.0
    voltage_limit: float = 10.0
    voltage: float = 0
    source: str = "volt"


@dataclass
class PIDState:
    """State of the PID Emulator"""
    direction: str = "forward"
    freq_setpoint: float = 0.0


@dataclass
class HWPState:
    """State of the HWP Emulator"""
    cur_freq: float = 0.0
    pmx: PMXState = field(default_factory=PMXState)
    pid: PIDState = field(default_factory=PIDState)
    lock = threading.Lock()


def _create_logger(name, log_level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    if len(logger.handlers) == 0:
        formatter = logging.Formatter("%(name)s: %(message)s")
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def lerp(start, end, t):
    return (1 - t) * start + t * end


class HWPEmulator:
    def __init__(self, pid_port=None, pmx_port=None, log_level=logging.INFO):
        self.pid_port = pid_port
        self.pmx_port = pmx_port

        self.state = HWPState()

        self.pid_device = device_emulator.DeviceEmulator([])
        self.pid_device.get_response = self.process_pid_msg
        self.pid_device.logger = _create_logger("PID", log_level=log_level)

        self.pmx_device = device_emulator.DeviceEmulator([])
        self.pmx_device.get_response = self.process_pmx_msg
        self.pmx_device.logger = _create_logger("PMX", log_level=log_level)

        self.update_thread = threading.Thread(target=self.update_loop)
        self.run_update = False

        self.logger = _create_logger("HWP", log_level=log_level)

    def start(self):
        """Start up TCP Sockets and update loop"""
        if self.pid_port is not None:
            self.pid_device.create_tcp_relay(self.pid_port)
        if self.pmx_port is not None:
            self.pmx_device.create_tcp_relay(self.pmx_port)

        self.update_thread.start()

    def shutdown(self):
        """Shutdown TCP Sockets and update loop"""
        self.run_update = False
        self.pid_device.shutdown()
        self.pmx_device.shutdown()
        self.update_thread.join()

    def update_loop(self):
        """Update HWP state"""
        self.run_update = True
        s = self.state
        self.logger.info("Starting update thread")

        while self.run_update:
            with s.lock:
                if s.pmx.source == "volt":
                    s.cur_freq = lerp(s.cur_freq, s.pid.freq_setpoint, 0.3)
            time.sleep(1)

    def process_pmx_msg(self, data):
        """Process messages for PMX emulator"""
        cmd = data.split(" ")[0].strip()
        self.logger.debug(cmd)
        with self.state.lock:
            # Output commands
            if cmd == "output":
                val = int(data.split(" ")[1].strip())
                self.logger.info("Setting output to %d", val)
                self.state.pmx.output = bool(val)
            elif cmd == "output:protection:clear":
                self.logger.info("Commanded to clear alarms")
            elif cmd == "output?":
                return str(int(self.state.pmx.output))

            # Current (limit) commands
            elif cmd == "curr":
                val = float(data.split(" ")[1].strip())
                self.logger.info("Setting current to %.3f", val)
                self.state.pmx.current = val
            elif cmd == "curr:prot":
                val = float(data.split(" ")[1].strip())
                self.logger.info("Setting current limit to %.3f", val)
                self.state.pmx.current_limit = val
            elif cmd == "curr?":
                return f"{self.state.pmx.current}\n"
            elif cmd == "curr:prot?":
                return f"{self.state.pmx.current_limit}\n"
            elif cmd == "meas:curr?":
                return f"{self.state.pmx.current}\n"

            # Voltage (limit) commands
            elif cmd == "volt":
                val = float(data.split(" ")[1].strip())
                self.logger.info("Setting current to %.3f", val)
                self.state.pmx.voltage = val
            elif cmd == "volt:prot":
                val = float(data.split(" ")[1].strip())
                self.logger.info("Setting voltage limit to %.3f", val)
                self.state.pmx.voltage_limit = val
            elif cmd == "volt:prot?":
                return f"{self.state.pmx.voltage_limit}\n"
            elif cmd == "volt?":
                return f"{self.state.pmx.voltage}\n"
            elif cmd == "meas:volt?":
                return f"{self.state.pmx.voltage}\n"

            # Error codes
            elif cmd == ":system:error?":  # Error codes
                return '0,"No error"\n'
            elif cmd == "stat:ques?":  # Status Codes
                return "0"
            elif cmd == "volt:ext:sour?":
                return f"{self.state.pmx.source}\n"
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
                return f"R01{PID._convert_to_hex(self.state.pid.freq_setpoint, 3)}"
            elif cmd == "*R02":  # Get Direction
                if self.state.pid.direction == "forward":
                    return "R02400000"
                else:
                    return "R02401388"
            else:
                self.logger.info("Unknown cmd: %s", cmd)
                return "unknown"


def create_hwp_emulator_fixture(**kwargs):
    """
    Creates a fixture for the HWP Emulator to use in tests.
    """

    @pytest.fixture()
    def create_emulator():
        em = HWPEmulator(**kwargs)
        em.start()
        yield em
        em.shutdown()

    return create_emulator


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid-port", type=int, default=5025)
    parser.add_argument("--pmx-port", type=int, default=5026)
    args = parser.parse_args()

    hwp_em = HWPEmulator(pid_port=args.pid_port, pmx_port=args.pmx_port)
    try:
        hwp_em.start()
        while True:
            time.sleep(1)
    finally:
        hwp_em.shutdown()
