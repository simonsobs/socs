"""
HWP Emulation module
"""

import argparse
import logging
import pickle as pkl
import socket
import threading
import time
import traceback as tb
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pytest

from socs.agents.hwp_pid.drivers.pid_controller import PID
from socs.testing import device_emulator


def _find_open_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def hex_str_to_dec(hex_value, decimal=3):
    """Converts a hex string to a decimal float"""
    return float(int(hex_value, 16)) / 10**decimal


@dataclass
class PMXState:
    """
    State of the PMX Emulator
    """

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


NUM_PCU_RELAYS = 8


@dataclass
class PCUState:
    """State of PCU emulator"""

    relays: List[bool] = field(
        default_factory=lambda: [False for _ in range(NUM_PCU_RELAYS)]
    )


# Gripper state information, taken from sobonelib: https://github.com/simonsobs/sobonelib/blob/main/hwp_gripper/control/state_monitor.py


COLD_LIMIT_POS = 13.0  # mm
WARM_LIMIT_POS = 10.0  # mm
LIMIT_TOLERANCE = 1.0  # mm


@dataclass
class LimitState:
    state: bool = False


@dataclass
class ActuatorState:
    axis: int
    limits: Dict[str, LimitState] = field(
        default_factory=lambda: {
            "cold_grip": LimitState(),
            "warm_grip": LimitState(),
        }
    )
    pos: float = 0
    brake: bool = False
    emg: bool = False

    def update(self) -> None:
        self.limits["cold_grip"].state = self.pos >= COLD_LIMIT_POS - LIMIT_TOLERANCE
        self.limits["warm_grip"].state = self.pos >= WARM_LIMIT_POS - LIMIT_TOLERANCE


@dataclass
class JXCState:
    setup: bool = False
    svon: bool = False
    busy: bool = False
    seton: bool = False
    inp: bool = False
    svre: bool = False
    alarm: bool = False
    out: int = 0

    @property
    def status(self):
        """
        Current status of the controller determined from JXC input pins.
        Described on page 43 of the JXC manual:
            https://www.smcworld.com/assets/manual/en-jp/files/SFOD-OMT0010.pdf
        """

        # Bit string that we can use to easily check current state
        status_bits = [self.busy, self.inp, self.svre, self.seton]
        bit_rep = "".join([str(int(s)) for s in status_bits])

        if self.out == 0:
            if bit_rep == "0000":
                return "powered_down_servo_off"
            elif bit_rep == "0010":
                return "powered_down_servo_on"
            elif bit_rep == "0100":
                return "return_to_origin"
            elif bit_rep == "0111":
                return "home"
        else:
            # This contains a number of different cases, but from the docs they
            # don't seem to be 1-to-1 to bit_rep
            return f"output_step_{self.out}"


@dataclass
class GripperState:
    actuators: Tuple[ActuatorState, ActuatorState, ActuatorState] = field(
        default_factory=lambda: (
            ActuatorState(axis=1),
            ActuatorState(axis=2),
            ActuatorState(axis=3),
        )
    )
    jxc: JXCState = field(default_factory=JXCState)
    last_packet_received: float = 0.0
    last_limit_received: float = 0.0
    last_encoder_received: float = 0.0
    calibrated: bool = False
    calibrated_at: float = 0
    powered: bool = True
    # If is_cold, use cold limit switch to stop pos, else use warm limit
    is_cold: bool = False

    _expiration_time: float = 10.0
    _last_enc_state: Optional[int] = None
    _left_home: bool = False

    @property
    def expired(self):
        """Returns True if the gripper state has not been updated in a while"""
        return time.time() - self.last_packet_received > self._expiration_time

    def update(self) -> None:
        now = time.time()
        self.last_packet_received = now
        self.last_limit_received = now
        self.last_encoder_received = now
        for act in self.actuators:
            act.update()


@dataclass
class HWPState:
    """State of the HWP Emulator"""

    cur_freq: float = 0.0
    pmx: PMXState = field(default_factory=PMXState)
    pid: PIDState = field(default_factory=PIDState)
    pcu: PCUState = field(default_factory=PCUState)
    gripper: GripperState = field(default_factory=GripperState)
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


BB_CLOCK_FREQ = 200e6  # Hz
NUM_SLITS = 570  # Slits per rotation
ENC_COUNTER_LEN = 120


class HWPEmulator:
    def __init__(
        self,
        pid_port=0,
        pmx_port=0,
        gripper_port=0,
        pcu_port="./responder",
        log_level=logging.INFO,
        enc_port=0,
        lerp_frac=0.9,
    ):
        self.pid_port = pid_port
        self.pmx_port = pmx_port
        self.pcu_port = pcu_port
        self.enc_port = enc_port
        self.gripper_port = gripper_port

        self.state = HWPState()
        self.lerp_frac = lerp_frac

        self.pid_device = device_emulator.DeviceEmulator([])
        self.pid_device.get_response = self.process_pid_msg
        self.pid_device.logger = _create_logger("PID", log_level=log_level)

        self.pmx_device = device_emulator.DeviceEmulator([])
        self.pmx_device.get_response = self.process_pmx_msg
        self.pmx_device.logger = _create_logger("PMX", log_level=log_level)

        self.pcu_device = device_emulator.DeviceEmulator([])
        self.pcu_device.get_response = self.process_pcu_msg
        self.pcu_device.logger = _create_logger("PCU", log_level=log_level)

        self.gripper_device = device_emulator.DeviceEmulator([])
        self.gripper_device.get_response = self.process_gripper_msg
        self.gripper_device.encoding = None
        self.gripper_device.logger = _create_logger("GRIP", log_level=log_level)

        self.update_thread = threading.Thread(target=self.update_loop)
        self.run_update = False
        self.enc_thread = threading.Thread(target=self.encoder_thread_func)
        self.run_enc_thread = False

        if self.enc_port == 0:
            self.enc_port = _find_open_port()

        self.logger = _create_logger("HWP", log_level=log_level)

    def start(self):
        """Start up TCP Sockets and update loop"""
        if self.pid_port is not None:
            self.pid_device.create_tcp_relay(self.pid_port)
        if self.pmx_port is not None:
            self.pmx_device.create_tcp_relay(self.pmx_port)
        if self.gripper_port is not None:
            self.gripper_device.create_tcp_relay(self.gripper_port)
        if self.pcu_port is not None:
            self.pcu_device.create_serial_relay()

        self.logger.info(f"PID port: {self.pid_device.socket_port}")
        self.logger.info(f"PMX port: {self.pmx_device.socket_port}")
        # self.logger.info(f"PCU port: {self.pcu_device}")
        self.logger.info(f"Gripper port: {self.gripper_device.socket_port}")

        self.update_thread.start()
        self.enc_thread.start()

    def shutdown(self):
        """Shutdown TCP Sockets and update loop"""
        self.run_update = False
        self.run_enc_thread = False
        self.update_thread.join()
        self.enc_thread.join()
        self.pid_device.shutdown()
        self.pmx_device.shutdown()
        self.pcu_device.shutdown()
        self.gripper_device.shutdown()
        self.logger.info("Finished shutdown")

    def encoder_thread_func(self):
        # Function that sends UDP packets to be interpreted by the encoder agent.
        # This contains info about encoder edges.
        self.logger.info("Starting encoder thread...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        addr = ("", self.enc_port)

        # Header and quad info
        header = np.array([0x1EAF, 1], dtype=np.uint32)
        edge_count = np.arange(ENC_COUNTER_LEN, dtype=np.uint32)
        clock_full = np.empty(edge_count.shape, dtype=np.uint64)

        last_clock = 0
        self.run_enc_thread = True
        while self.run_enc_thread:
            f = self.state.cur_freq
            if f < 0.01:
                time.sleep(0.1)
                continue
            sleep_time = ENC_COUNTER_LEN / (f * NUM_SLITS)
            time.sleep(sleep_time)

            if f < 0.01:
                time.sleep(0.05)
                continue
            else:
                clock_step = BB_CLOCK_FREQ / (2 * self.state.cur_freq * NUM_SLITS)
                next_clock = last_clock + ENC_COUNTER_LEN * clock_step
                clock_full = np.linspace(
                    last_clock, next_clock, ENC_COUNTER_LEN, dtype=np.uint64
                )
                last_clock = next_clock
                edge_count += ENC_COUNTER_LEN
                clock = (clock_full & 0xFFFFFFFF).astype(np.uint32)
                clock_overflow = (clock_full >> 32).astype(np.uint32)
                byte_data = np.hstack(
                    [header, clock, clock_overflow, edge_count]
                ).tobytes()
                sock.sendto(byte_data, addr)

                time.sleep(ENC_COUNTER_LEN / (2 * self.state.cur_freq * NUM_SLITS))
        self.logger.info("Stopping encoder thread")

    def update_loop(self) -> None:
        """Update HWP state"""
        self.run_update = True
        s: HWPState = self.state
        self.logger.info("Starting update thread")

        while self.run_update:
            with s.lock:
                if s.pmx.source == "volt":
                    s.cur_freq = lerp(s.cur_freq, s.pid.freq_setpoint, self.lerp_frac)
                s.gripper.update()
            time.sleep(0.2)
        self.logger.info("Stopping update thread")

    def process_pcu_msg(self, data) -> str:
        self.logger.debug(data)
        try:
            _, cmd, chan_str = data.split(" ")
            chan = int(chan_str)
        except Exception:
            raise ValueError(f"Unable to parse message: {data}")

        assert chan < NUM_PCU_RELAYS
        assert cmd in ["read", "on", "off"]

        if cmd == "read":
            if self.state.pcu.relays[chan]:
                return f"{chan}\n\ron\n\r"
            else:
                return f"{chan}\n\roff\n\r"
        elif cmd == "on":
            self.state.pcu.relays[chan] = 1
        elif cmd == "off":
            self.state.pcu.relays[chan] = 0
        return "\n\r"

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
                return f"R0140{PID._convert_to_hex(self.state.pid.freq_setpoint, 3)}"
            elif cmd == "*R02":  # Get Direction
                if self.state.pid.direction == "forward":
                    return "R02400000"
                else:
                    return "R02401388"
            else:
                self.logger.info("Unknown cmd: %s", cmd)
                return "unknown"

    def process_gripper_msg(self, msg_bytes: bytes) -> bytes:
        msg = msg_bytes.decode()
        try:
            state: GripperState = self.state.gripper
            cmd = msg.strip().split(" ")
            self.logger.debug(f"Gripper: {msg}")

            def raise_error():
                raise ValueError(f"Unable to process msg: {msg}")

            if cmd[0] == "ON":
                state.powered = True
            elif cmd[0] == "OFF":
                state.powered = False
            elif cmd[0] == "HOME":
                for act in state.actuators:
                    act.pos = 0
            elif cmd[0] == "MOVE":
                act_idx = int(cmd[2]) - 1
                new_pos = state.actuators[act_idx].pos + float(cmd[3])
                if state.is_cold and new_pos >= COLD_LIMIT_POS:
                    state.actuators[act_idx].pos = COLD_LIMIT_POS
                    return pkl.dumps({"result": False, "log": []})
                elif (not state.is_cold) and new_pos >= WARM_LIMIT_POS:
                    state.actuators[act_idx].pos = WARM_LIMIT_POS
                    return pkl.dumps({"result": False, "log": []})
                else:
                    state.actuators[act_idx].pos = new_pos
                    return pkl.dumps({"result": True, "log": []})
            elif cmd[0] == "BRAKE":
                enabled = cmd[1] == "ON"
                if len(cmd) == 3:
                    act_idxs = [int(cmd[2]) - 1]
                else:
                    act_idxs = [0, 1, 2]
                for i in act_idxs:
                    state.actuators[i].brake = enabled
            elif cmd[0] == "EMG":
                enabled = cmd[1] == "ON"
                if len(cmd) == 3:
                    act_idxs = [int(cmd[2]) - 1]
                else:
                    act_idxs = [0, 1, 2]
                for i in act_idxs:
                    state.actuators[i].emg = enabled
            elif cmd[0] == "GET_STATE":
                return pkl.dumps({"result": asdict(state), "log": []})

            return pkl.dumps({"result": True, "log": []})
        except Exception:
            print(tb.format_exc())
            return b""


def create_hwp_emulator_fixture(**kwargs):
    """
    Creates a fixture for the HWP Emulator to use in tests.
    """

    @pytest.fixture()
    def create_emulator():
        em = HWPEmulator(**kwargs)
        try:
            em.start()
            yield em
        finally:
            em.shutdown()

    return create_emulator


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid-port", type=int, default=0)
    parser.add_argument("--pmx-port", type=int, default=0)
    args = parser.parse_args()

    hwp_em = HWPEmulator(pid_port=args.pid_port, pmx_port=args.pmx_port)
    try:
        hwp_em.start()
        while True:
            time.sleep(1)
    finally:
        hwp_em.shutdown()
