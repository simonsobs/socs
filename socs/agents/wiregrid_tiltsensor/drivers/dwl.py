# Built-in python modules
import time as tm

import serial as sr

# Control modules
from socs.common import moxa_serial as mx


class DWL:
    """
    The DWL object is for communicating with the DWL-5000XY gravity sensor

    Args:
    rtu_port (str): Serial RTU port
    tcp_ip (str): TCP IP address
    tcp_port (int): TCP port
    """
    waittime = 0.05  # sec

    def __init__(self, rtu_port=None, tcp_ip=None, tcp_port=None, timeout=None, isSingle=False, verbose=0):
        self.isSingle = isSingle
        self.verbose = verbose
        if rtu_port is not None:
            self.using_rtu = True
            self.using_tcp = None
        if tcp_ip is not None:
            self.using_rtu = None
            self.using_tcp = True

        # Connect to device
        msg = self.__conn(rtu_port, tcp_ip, tcp_port, timeout)
        print(msg)

    def __del__(self):
        if not self.using_tcp:
            print(
                "Disconnecting from RTU port %s"
                % (self.rtu_port))
        else:
            print(
                "Disconnecting from TCP IP %s at port %d"
                % (self.tcp_ip, self.tcp_port))
            pass
        self.ser.close()
        return

    def get_angle(self):
        """ Measure the single-axis angle """
        self.clean_serial()
        if self.isSingle:
            command = b"\x06\x01\x01\xAA\x00\x00\x00\x00\x00\x00\x00\x00"
        else:
            command = b"\x06\x01\x02\xAA\x00\x00\x00\x00\x00\x00\x00\x00"
            pass
        if self.verbose > 0:
            print(f'get_angle() command = {command}')
            pass
        self.ser.write(command)
        self.wait()

        read = []
        SIZE = 12
        read_status = True
        start_read_time = tm.time()
        current_time = start_read_time

        while True:
            # check timeout for header mismatching
            current_time = tm.time()
            if current_time - start_read_time > 1.0:
                read_status = False
                if self.verbose > 0:
                    print('the header of read value did not match!')
                    print('interrupt reading')
                break
            # read serial
            read0 = self.ser.read(SIZE)
            size0 = len(read0)
            if self.verbose > 0:
                print(f'{size0}: "{read0}"')
                pass
            if size0 > 0:
                if self.verbose > 0:
                    print('read0 = {}'.format([hex(r) for r in read0]))
                    pass
                add = [hex(r) for r in read0]
                read += add
                if self.verbose > 0:
                    print(read)
                    pass
                pass
            # check header matching
            while len(read) > 0:
                if self.isSingle:
                    header = ['0x61', '0x11']
                    # header = ['0x61','0x12']
                else:
                    header = ['0x61', '0x22']
                    pass
                if read[0:2] == header:
                    break
                else:
                    read = read[1:]
                    pass
                pass

            if len(read) >= SIZE:
                break
            pass

        if read_status:
            size = len(read)
            if self.verbose > 0:
                print(f'read (size:{size}) = {read}')
                pass

            if size > 0:
                readInt = []
                val = ()
                for c in read:
                    readInt.append((int)(c, 16))
                    pass
                if self.isSingle:
                    nums = [readInt[5], readInt[4], readInt[3], readInt[2]]
                    angleX = (nums[0] << 24) + (nums[1] << 16) + (nums[2] << 8) + (nums[3])
                    angleX = (angleX - 1800000) / 10000.
                    val = (angleX)
                    if self.verbose > 0:
                        print(readInt)
                        print(nums)
                        print((nums[1] << 16) / 1e+4, (nums[2] << 8) / 1e+4, (nums[3]) / 1e+4)
                        print('angle X = {}'.format(angleX))
                        pass
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
                    if self.verbose > 0:
                        print(readInt)
                        print('numsX', numsX)
                        print((numsX[0] << 16) / 1e+4, (numsX[1] << 8) / 1e+4, (numsX[2]) / 1e+4)
                        print('numsY', numsY)
                        print((numsY[0] << 16) / 1e+4, (numsY[1] << 8) / 1e+4, (numsY[2]) / 1e+4)
                        print('angle X = {angleX}')
                        print('angle Y = {angleY}')
                        pass
                    pass
                pass

            if self.isSingle:
                msg = f"Measured angle (1-axis) = {val}"
            else:
                msg = f"Measured angle (2-axis) = {val}"
                pass
            if self.verbose > 0:
                print(msg)
                pass
            return read_status, msg, val
        else:
            msg = 'reading time out'
            val = (-999, -999)
            return read_status, msg, val

    # ***** Helper Methods *****

    def __conn(self, rtu_port=None, tcp_ip=None, tcp_port=None, timeout=None):
        """
        Connect to the PMX module

        Args:
        rtu_port (str): Serial RTU port
        tcp_ip (str): TCP IP address
        tcp_port (int): TCP port
        """
        print(rtu_port)
        if rtu_port is None and (tcp_ip is None or tcp_port is None):
            raise Exception(
                "Aborted PMX._conn() due to no RTU or "
                "TCP port specified")
        elif (rtu_port is not None
              and (tcp_ip is not None or tcp_port is not None)):
            raise Exception(
                "Aborted PMX._conn() due to RTU and TCP port both being "
                "specified. Can only have one or the other.")
        elif rtu_port is not None:
            self.ser = sr.Serial(
                port=rtu_port, baudrate=115200, bytesize=8,
                parity='N', stopbits=1, timeout=timeout)
            self.using_tcp = False
            msg = "Connected to RTU port %s" % (rtu_port)
            command = b"\x06\x24\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # initialization command
            if self.verbose > 0:
                print('initialization command = {}'.format(command))
                pass
            self.ser.write(command)
        elif tcp_ip is not None and tcp_port is not None:
            self.ser = mx.Serial_TCPServer((tcp_ip, tcp_port), timeout)
            self.tcp_ip = tcp_ip
            self.tcp_port = int(tcp_port)
            self.using_tcp = True
            msg = "Connected to TCP IP %s at port %d" % (tcp_ip, tcp_port)

            command = b"\x06\x24\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # initialization command
            if self.verbose > 0:
                print('initialization command = {}'.format(command))
                pass
            self.ser.write(command)
            self.wait()
        else:
            raise Exception(
                "Aborted PMX._conn() due to unknown error")
        return msg

    def wait(self):
        """ Sleep """
        tm.sleep(self.waittime)
        return True

    def clean_serial(self):
        """ Flush the serial buffer """
        self.ser.flushInput()

        command = b"\x06\x24\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # initialization command
        self.ser.write(command)
        self.wait()
        return True
