import random
import selectors
import socket
import struct

STX = '\x02'
ADDR = '\x10'
CMD = '\x80'
CR = '\x0D'
DATA_WRITE = '\x61'
DATA_READ = '\x63'
ESC = '\x07'
ESC_STX = '\x30'
ESC_CR = '\x31'
ESC_ESC = '\x32'


class PTC:
    def __init__(self, ip_address, port=502, timeout=10, fake_errors=False):
        self.fake_errors = fake_errors

        self.model = None
        self.serial = None
        self.software_revision = None

        self.ip_address = ip_address
        self.port = int(port)
        self.timeout = timeout
        self.comm = self._connect((self.ip_address, self.port))

    def _connect(self, address):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(address)
        except TimeoutError:
            print(f"Connection not established within {self.timeout}.")
            return
        except OSError as e:
            print(f"Unable to connect. {e}")
            return
        except Exception as e:
            print(f"Caught unexpected {type(e).__name__} while connecting:")
            print(f"  {e}")
            return
        return sock

    def reset(self):
        print("Resetting the connection to the compressor.")
        self.comm = self._connect((self.ip_address, self.port))

    def _write(self, msg):
        if self.comm is None:
            print("Connection not established. Unable to send command.")
            self.reset()
            return

        try:
            self.comm.sendall(msg)
            return
        except (BrokenPipeError, ConnectionResetError) as e:
            print(f"Connection error: {e}")
            self.reset()
        except TimeoutError as e:
            print(f"Timeout error while writing: {e}")
            self.reset()
        except Exception as e:
            print(f"Caught unexpected {type(e).__name__} during write:")
            print(f"  {e}")
            self.reset()

        # Try a second time before giving up
        try:
            self.comm.sendall(msg)
        except (BrokenPipeError, ConnectionResetError) as e:
            print(f"Connection error: {e}")
            raise ConnectionError
        except TimeoutError as e:
            print(f"Timeout error while writing: {e}")
            raise ConnectionError
        except AttributeError:
            raise ConnectionError("Unable to reset connection.")
        except Exception as e:
            print(f"Caught unexpected {type(e).__name__} during write:")
            print(f"  {e}")
            raise ConnectionError

    def _check_ready(self):
        """Check socket is ready to read from."""
        if self.comm is None:
            raise ConnectionError("Connection not established, not ready to read.")

        sel = selectors.DefaultSelector()
        sel.register(self.comm, selectors.EVENT_READ)
        if not sel.select(self.timeout):
            raise ConnectionError

    def _read(self):
        self._check_ready()
        data = self.comm.recv(1024)
        return data

    def get_data(self):
        """
        Gets the raw data from the ptc and returns it in a usable format.
        """
        self._write(self.buildRegistersQuery())
        data = self._read()
        data_flag, brd = self.breakdownReplyData(data)

        return data_flag, brd

    @staticmethod
    def buildRegistersQuery():
        query = bytes([0x09, 0x99,  # Message ID
                       0x00, 0x00,  # Unused
                       0x00, 0x06,  # Message size in bytes
                       0x01,        # Slave Address
                       0x04,        # Function Code
                       0x00, 0x01,   # The starting Register Number
                       0x00, 0x35])  # How many to read
        return query

    def power(self, state):
        """Turn the PTC on or off.

        Parameters
        ----------
        state : str
            Desired power state of the PTC, either 'on', or 'off'.

        """
        command = [0x09, 0x99,  # Message ID
                   0x00, 0x00,  # Unused
                   0x00, 0x06,  # Message size in bytes
                   0x01,        # Slave Address
                   0x06,        # Function Code
                   0x00, 0x01]   # Register Number

        if state.lower() == 'on':
            command.extend([0x00, 0x01])
        elif state.lower() == 'off':
            command.extend([0x00, 0xff])
        else:
            raise ValueError(f"Invalid state: {state}")

        self.comm.sendall(bytes(command))
        self.comm.recv(1024)  # Discard the echoed command

    def breakdownReplyData(self, rawdata):
        """Take in raw ptc data, and return a dictionary.

        The dictionary keys are the data labels, the dictionary values are the
        data in floats or ints.

        Returns
        -------
        data_flag : bool
            False if data is valid, True if output could not be interpretted.
        data : dict
            Data dictionary already formatted for passing to OCS Feed.

        """

        # Associations between keys and their location in rawData
        keyloc = {"Operating_State": [9, 10],
                  "Compressor_State": [11, 12],
                  "Warning_State": [15, 16, 13, 14],
                  "Alarm_State": [19, 20, 17, 18],
                  "Coolant_In_Temp": [23, 24, 21, 22],
                  "Coolant_Out_Temp": [27, 28, 25, 26],
                  "Oil_Temp": [31, 32, 29, 30],
                  "Helium_Temp": [35, 36, 33, 34],
                  "Low_Pressure": [39, 40, 37, 38],
                  "Low_Pressure_Average": [43, 44, 41, 42],
                  "High_Pressure": [47, 48, 45, 46],
                  "High_Pressure_Average": [51, 52, 49, 50],
                  "Delta_Pressure_Average": [55, 56, 53, 54],
                  "Motor_Current": [59, 60, 57, 58],
                  "Hours_of_Operation": [63, 64, 61, 62],
                  "Pressure_Unit": [65, 66],
                  "Temperature_Unit": [67, 68],
                  "Serial_Number": [69, 70],
                  "Model": [71, 72],
                  "Software_Revision": [73, 74]}

        # Iterate through all keys and return the data in a usable format.
        # If there is an error in the string format, print the
        # error to logs, return an empty dictionary, and flag the data as bad
        data = {}

        # If fake_errors=True, then randomly output the string 'FAKE ERROR'
        # instead of the actual data 50% of the time
        if self.fake_errors:
            if random.random() < 0.5:
                rawdata = "FAKE ERROR"

        try:
            for key in keyloc.keys():
                locs = keyloc[key]
                wkrBytes = bytes([rawdata[loc] for loc in locs])

                # four different data formats to unpack
                # Big endian unsigned integer 16 bits
                if key in [
                    "Operating_State",
                    "Compressor_State",
                    "Pressure_Unit",
                    "Temperature_Unit",
                    "Serial_Number",
                ]:
                    state = struct.unpack(">H", wkrBytes)[0]
                    # Serial number is an attribute, not publishable data
                    if key == "Serial_Number":
                        self.serial = state
                    else:
                        data[key] = state
                # 32bit signed integer which is actually stored as a
                # 32bit IEEE float (silly)
                elif key in ["Warning_State", "Alarm_State"]:
                    state = int(struct.unpack(">f", wkrBytes)[0])
                    data[key] = state
                # 2 x 8-bit lookup tables.
                elif key in ["Model"]:
                    model_major = struct.unpack(
                        ">B", bytes([rawdata[locs[0]]]))[0]
                    model_minor = struct.unpack(
                        ">B", bytes([rawdata[locs[1]]]))[0]
                    # Model is an attribute, not publishable data
                    self.model = str(model_major) + "_" + str(model_minor)
                elif key in ["Software_Revision"]:
                    version_major = struct.unpack(
                        ">B", bytes([rawdata[locs[0]]]))[0]
                    version_minor = struct.unpack(
                        ">B", bytes([rawdata[locs[1]]]))[0]
                    self.software_revision = str(version_major) + "." + str(version_minor)
                # 32 bit Big endian IEEE floating point
                else:
                    data[key] = struct.unpack(">f", wkrBytes)[0]

            data_flag = False

        except BaseException:
            data_flag = True
            print("Compressor output could not be converted to numbers."
                  f"Skipping this data block. Bad output string is {rawdata}")

        return data_flag, data

    def __del__(self):
        """
        If the PTC class instance is destroyed, close the connection to the
        ptc.
        """
        self.comm.close()
