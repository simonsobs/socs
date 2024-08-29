import struct

from pyModbusTCP.client import ModbusClient


class Hi6200Interface():
    """
    Connects to the Hi6200 weight sensor using a TCP ModbusClient with pyModbusTCP.
    The Modbus Client uses a socket connection to facillitate Modbus communications.
    ModbusClient requires an IP address and port to connect.

    The Gross and Net weight sensors are always available to read on the 8,9
    and 6,7 registers respectively.

    ModbusClient will not throw errors upon incorrect ip_address!

    ModbusClient auto-reconnects upon socket failure if auto_open is True.

    """

    def __init__(self, ip_address, tcp_port, verbose=False, **kwargs):
        self.scale = ModbusClient(host=ip_address,
                                  port=tcp_port,
                                  auto_open=True,
                                  auto_close=False)

    def _decode_scale_weight_registers(self, register_a, register_b):
        """
        Decodes the scales weight registers and returns a single weight value
        (float).

        The scale holds both the net and gross weights in permanent holding
        registers. Each weight is held across 2 registers in 4 hex bits (2 hex
        bits/4 bits per register, 8 bits total). The hex bits must be
        concatenated and converted to a float.

        """
        # Strip the '0x' hex bit
        # We must have 8 total bits to convert, so we zfill until each register
        # value is 4 bits
        hex_a = hex(register_b)[2:].zfill(4)
        hex_b = hex(register_b)[2:].zfill(4)

        # Concatenate the hex bits in cdab order.
        hex_weight = hex_b + hex_a

        # This struct function converts the concatenated hex bits to a float.
        return struct.unpack('!f', bytes.fromhex(hex_weight))[0]

    def read_scale_gross_weight(self):
        """
        Returns:
            float: The current gross weight reading of the scale in the sensors
            chosen unit (kg).

        """
        try:
            # The gross weight is always available on the 8,9 registers.
            # Reading these registers will return an int.
            a, b = self.scale.read_holding_registers(8, 2)

            return self._decode_scale_weight_registers(a, b)

        except AttributeError:
            return None

    def read_scale_net_weight(self):
        """
        Returns:
            float: The current net weight reading of the scale in the sensors
            chosen unit (kg).

        """
        try:
            # The gross weight is always available on the 6,7 registers.
            # Reading these registers will return an int.
            a, b = self.scale.read_holding_registers(6, 2)

            return self._decode_scale_weight_registers(a, b)

        except AttributeError:
            return None
