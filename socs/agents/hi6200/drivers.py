from pyModbusTCP.client import ModbusClient
import struct


class Hi6200Interface():

    """
    The Hi6200 Weight Processor uses a Modbus TCP Interface to communicate.
    The Gross and Net weight sensors are always available to read on the 8,9 and 6,7 registers respectively.
    """

    def __init__(self, ip_address, tcp_port, verbose=False, **kwargs):
        """
            Connects to the Hi6200 weight sensor using a TCP Modbus Client with pyModbusTCP.
            This works ~similarly to a socket connection using a IP and port.
            ModbusClient will not throw errors upon incorrect ip_address!
            ModbusClient will also allow multiple recconects unlike a socket.
        """

        self.scale = ModbusClient(host=ip_address, port=tcp_port, auto_open=True, auto_close=False)

    def read_scale_gross_weight(self):
        """
            Returns the current gross weight reading of the scale in the sensors chosen unit (kg)
        """

        # The gross weight is always available on the 8,9 registers.
        # Reading these registers will return an int.
        a, b = self.scale.read_holding_registers(8, 2)

        # The ints read on the registers must be converted to hex.
        # The hex bits are then concatenated and converted to float as CDAB

        # Strip the '0x' hex bit prefix as it is not useful.
        # Then concatenate the bits
        hex_a = hex(a)[2:]
        while len(hex_a) < 4:
            hex_a = '0' + hex_a

        hex_b = hex(b)[2:]
        while len(hex_b) < 4:
            hex_b = '0' + hex_b

        hex_weight = hex_b + hex_a

        # This struct function converts the concatenated hex bits to a float.
        return struct.unpack('!f', bytes.fromhex(hex_weight))[0]

    def read_scale_net_weight(self):
        """
            Returns the current net weight reading of the scale in the sensors chosen unit (kg)
        """

        # The gross weight is always available on the 6,7 registers.
        # Reading these registers will return an int.
        a, b = self.scale.read_holding_registers(6, 2)

        # The ints read on the registers must be converted to hex.
        # The hex bits are then concatenated and converted to float as CDAB.

        # Strip the '0x' hex bit prefix as it is not useful.
        # Then concatenate the bits
        hex_a = hex(a)[2:]
        while len(hex_a) < 4:
            hex_a = '0' + hex_a

        hex_b = hex(b)[2:]
        while len(hex_b) < 4:
            hex_b = '0' + hex_b

        hex_weight = hex_b + hex_a

        # This struct function converts the concatenated hex bits to a float.
        return struct.unpack('!f', bytes.fromhex(hex_weight))[0]
