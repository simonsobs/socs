# Built-in python modules
import time as tm

# Control modules
from socs.common import moxa_serial as mx


class DWL:
    """
    The DWL object is for communicating with the DWL-5000XY gravity sensor

    Args:
    tcp_ip (str): TCP IP address
    tcp_port (int): TCP port
    """
    waittime = 0.05  # sec

    def __init__(self, tcp_ip=None, tcp_port=None, timeout=None, isSingle=False, verbose=0):
        self.tcp_ip = tcp_ip
        self.tcp_port = tcp_port
        self.isSingle = isSingle
        self.verbose = verbose

        # Connect to device
        msg = self.__conn(tcp_ip, tcp_port, timeout)
        print(msg)

    def __del__(self):
        print(f"Disconnecting from TCP IP {self.tcp_ip} at port {self.tcp_port}")
        self.ser.close()
        return

    def get_angle(self):
        """ Measure the single-axis or two-axis angle """
        self.clean_serial()
        if self.isSingle:
            command = b"\x06\x01\x01\xAA\x00\x00\x00\x00\x00\x00\x00\x00"
        else:
            command = b"\x06\x01\x02\xAA\x00\x00\x00\x00\x00\x00\x00\x00"
        if self.verbose > 0:
            print(f'get_angle() command = {command}')

        read = []
        SIZE = 12

        # write and read serial
        self.ser.write(command)
        read_hex = self.ser.read(SIZE)
        read = [hex(r) for r in read_hex]
        if self.verbose > 0:
            print(f'read_hex = {read_hex}')
            print(f'read = {read}')

        # check the size of the string read
        if not len(read) == SIZE:
            msg = 'The size of the string read does not match with the expected size 12.'
            if self.isSingle:
                val = (-999)
            else:
                val = (-999, 999)
            return msg, val

        # check header matching and calculate the angles
        if self.isSingle:
            header = ['0x61', '0x11']
        else:
            header = ['0x61', '0x22']
        if read[0:2] == header:
            readInt = []
            val = ()
            for c in read:
                readInt.append((int)(c, 16))
            if self.isSingle:
                nums = [readInt[5], readInt[4], readInt[3], readInt[2]]
                angleX = (nums[0] << 24) + (nums[1] << 16) + (nums[2] << 8) + (nums[3])
                angleX = (angleX - 1800000) / 10000.
                val = (angleX)
                msg = f"Measured angle (1-axis) = {val}"
                if self.verbose > 0:
                    print(readInt)
                    print(nums)
                    print((nums[1] << 16) / 1e+4, (nums[2] << 8) / 1e+4, (nums[3]) / 1e+4)
                    print('angle X = {}'.format(angleX))
            else:
                readInt1 = readInt[5:8]
                readInt2 = readInt[2:5]
                readInt11 = readInt1
                readInt12 = readInt2
                numsX = [readInt11[2], readInt11[1], readInt11[0]]
                numsY = [readInt12[2], readInt12[1], readInt12[0]]
                angleX = (numsX[0] << 16) + (numsX[1] << 8) + (numsX[2])
                angleX = (angleX - 300000) / 10000.
                angleY = (numsY[0] << 16) + (numsY[1] << 8) + (numsY[2])
                angleY = (angleY - 300000) / 10000.
                val = (angleX, angleY)
                msg = f"Measured angle (2-axis) = {val}"
                if self.verbose > 0:
                    print(readInt)
                    print('numsX', numsX)
                    print((numsX[0] << 16) / 1e+4, (numsX[1] << 8) / 1e+4, (numsX[2]) / 1e+4)
                    print('numsY', numsY)
                    print((numsY[0] << 16) / 1e+4, (numsY[1] << 8) / 1e+4, (numsY[2]) / 1e+4)
                    print('angle X = {angleX}')
                    print('angle Y = {angleY}')
        else:
            msg = 'header NOT matching'
            if self.isSingle:
                val = -999
            else:
                val = (-999, -999)
        if self.verbose > 0:
            print(msg)
        return msg, val

    # ***** Helper Methods *****
    def __conn(self, tcp_ip=None, tcp_port=None, timeout=None):
        """
        Connect to the tilt sensor module

        Args:
        tcp_ip (str): TCP IP address
        tcp_port (int): TCP port
        """
        if tcp_ip is None or tcp_port is None:
            raise Exception(
                "Aborted DWL._conn() due to no "
                "TCP port specified")
        elif tcp_ip is not None and tcp_port is not None:
            self.ser = mx.Serial_TCPServer((tcp_ip, tcp_port), timeout, encoded=False)
            self.tcp_ip = tcp_ip
            self.tcp_port = int(tcp_port)
            self.using_tcp = True
            msg = "Connected to TCP IP %s at port %d" % (tcp_ip, tcp_port)
            command = b"\x06\x24\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # initialization command
            if self.verbose > 0:
                print('initialization command = {}'.format(command))
            self.ser.write(command)
            self.wait()
        else:
            raise Exception(
                "Aborted DWL._conn() due to unknown error")
        return msg

    def wait(self):
        """ Sleep """
        tm.sleep(self.waittime)
        return True

    def clean_serial(self):
        """ Flush the serial buffer """
        self.ser.flushInput()
        self.wait()
        return True
