import serial
import os
import time
import argparse
import txaio
import time
# For logging
txaio.use_twisted()

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock


def decode_list(byte_list):
    """UTF decodes each element of a list

    Parameters
    ----------
    byte_list: list
        List to decode
    """
    return [item.decode('utf-8') for item in byte_list]


def parse_raw_point(string):
    """Converts the string response of the magnetometer into a float

    Parameters
    ----------
    string: str
        String from magnetometer representing one data point
    """
    try:
        val = int(string[1:].replace(',', ''))
        if string[0] == '-':
            val *= -1
    except:
        val = 0
        print(f"Bad val {val}, returning 0")
    return val


def parse_raw_data(raw_data):
    """Converting raw magnetometer output into usable floats

    Parameters
    ----------
    raw_data: list
        Raw magnetometer data
    """
    if not raw_data:
        print("No data")
    raw_data = decode_list(raw_data)[0][:-2]
    # Get rid of unwanted characters at the end
    raw_points = raw_data.split('\r')
    Bxs, Bys, Bzs = [], [], []
    for raw_point in raw_points:
        Bx = parse_raw_point(raw_point[0:7])  # in ASCII
        By = parse_raw_point(raw_point[9:16])
        Bz = parse_raw_point(raw_point[18:25])
        Bxs.append(Bx/15000)  # in gauss
        Bys.append(By/15000)
        Bzs.append(Bz/15000)

    return Bxs, Bys, Bzs


def set_sample_rate(ser, rate):
    """Sets the magnetometer sample rate

    Parameters
    ----------
    ser: object
        serial object for the magnetometer
    rate: int
        Sample rate
    """
    ser.write(f'*00R={rate}\r'.encode())
    reply = decode_list(ser.readlines())
    print(f"Setting sample rate to {rate} hz")

    return reply


def write_serial_command(ser, command, write_enabled=False):
    """Writes any serial command to the magnetometer
       (see the manual for list of commands)

    Parameters
    ----------
    ser: object
        serial object for the magnetometer
    command: str
        String command to pass to magnetometer
    write_enabled: bool
        Some commands require write-enabled (see the manual)
    """
    if write_enabled:
        ser.write(f'*00WE\r'.encode())
        print(f"Write enabled {decode_list(ser.readlines())}")
    ser.write(f'{command}\r'.encode())
    reply = decode_list(ser.readlines())
    print(f"Sent command {command}, reply is {reply}")
    return reply


def get_setup_parameters(ser):
    """Get the basic magnetometer parameters

    Parameters
    ----------
    ser: object
        serial object for the magnetometer"""
    ser.write('*00Q\r'.encode())
    reply = decode_list(ser.readlines())

    return reply


# LabJack agent class
class HoneywellHMR2300Agent:
    def __init__(self, agent, ip, port, sample_rate, acq_chunk, baudrate=9600):
        """
        baudrate: int
            Either 9600 or 19200. 9600 is the default after power restart,
            but 19200 is required to run at sample rates 40Hz or 50Hz.
        port: int
            Serial device port.
        ip: str
            serial device port.
        sample_rate: int
            Sample rate in Hz. Must be 10, 20, 30, 40, or 50
        acq_chunk: int
            Number of seconds to continuously take data
        """
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False
        self.ip = ip
        self.port = port
        self.sample_rate = sample_rate
        self.baudrate = baudrate
        self.acq_chunk = acq_chunk
        # Set connection parameters
        ser = serial.serial_for_url(url=f"socket://{self.ip}:{self.port}", baudrate=self.baudrate, timeout=3)
        ser.write(chr(27).encode())
        # Send stop streaming command in case still streaming
        setup = get_setup_parameters(ser)
        self.log.info(f"Setup parameters: {setup}")
        self.log.info(f"Connected to HMR2300 on ip{ip}, port {port}, with baudrate {baudrate}")

        # Register main feed. Exclude influx due to potentially high scan rate
        agg_params = {
            'frame_length': 60,
            'exclude_influx': True
        }
        self.agent.register_feed('mag_field',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

        # Register downsampled feed for influx.
        agg_params_downsampled = {
            'frame_length': 60
        }
        self.agent.register_feed('mag_field_downsampled',
                                 record=True,
                                 agg_params=agg_params_downsampled,
                                 buffer_time=1)

    def start_acq(self, session, params=None):
        """
        Task to start data acquisition.

        Parameters
        ----------
        sample_rate: int
            Sample rate in Hz. Must be 10, 20, 30, 40, or 50
        acq_chunk: int
            Number of seconds to continuously take data
        """
        if params is None:
            params = {}

        baudrate = params.get("baudrate", self.baudrate)
        port = params.get("port", self.port)
        ip = params.get("ip", self.ip)
        sample_rate = int(params.get("sample_rate", self.sample_rate))
        acq_chunk = int(params.get("acq_chunk", self.acq_chunk))

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            self.log.info(f"Started streaming at {sample_rate} Hz")
            self.take_data = True

        with serial.serial_for_url(url=f"socket://{self.ip}:{self.port}", baudrate=baudrate, timeout=3) as ser:
            ser.write(chr(27).encode())
            # Send stop streaming command in case still streaming
            set_sample_rate(ser, sample_rate)  # Set sample rate
            ser.write('*00C\r'.encode())  # Start streaming
            while self.take_data:
                    cur_time = time.time()
                    time.sleep(acq_chunk)
                    ser.write(chr(27).encode())  # Stop streaming to read data
                    raw_data = ser.readlines()
                    ser.write('*00C\r'.encode())  # Start streaming

                    data = {
                            'block_name': 'mag_field',
                            'data': {}
                        }
                    Bxs, Bys, Bzs = parse_raw_data(raw_data)
                    timestamps = [cur_time+i/sample_rate for i in range(len(Bxs))]
                    data['data']['Bx'] = Bxs
                    data['data']['By'] = Bys
                    data['data']['Bz'] = Bzs
                    data['timestamps'] = timestamps
                    self.agent.publish_to_feed('mag_field', data)

                    # Publish to the downsampled data feed only the first
                    # timestamp and data point for each channel.
                    data_downsampled = {
                            'block_name': 'mag_field',
                            'data': {},
                            'timestamps': timestamps[::sample_rate]
                        }
                    data_downsampled['data']['Bx'] = Bxs[::sample_rate]
                    data_downsampled['data']['By'] = Bys[::sample_rate]
                    data_downsampled['data']['Bz'] = Bzs[::sample_rate]
                    self.agent.publish_to_feed('mag_field_downsampled', data_downsampled)
            # Stop the data stream
            ser.write(chr(27).encode())

            return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """Stop data acquisition"""
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    def send_serial_command(self, session, params=None):
        """Writes any serial command to the magnetometer
           (see the manual for list of commands)

        Parameters
        ----------
        command: str
            String command to pass to magnetometer
        write_enabled: bool (optional)
            Some commands require write-enabled (see the manual). Default=True
        baudrate: int (optional)
            Either 9600 or 19200. Default=set during agent initialization
        port: int (optional)
            Serial device port. Default=set during agent initialization
        ip: str (optional)
            serial device port. Default=set during agent initialization
        """
        if params is None:
            params = {}

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start send_serial_command because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            baudrate = params.get("baudrate", self.baudrate)
            port = params.get("port", self.port)
            ip = params.get("ip", self.ip)

            command = params['command']
            write_enabled = params.get('write_enabled', False)

            with serial.serial_for_url(url=f'socket://{ip}:{port}',
                                       baudrate=baudrate, timeout=3) as ser:
                if write_enabled:
                    ser.write(f'*00WE\r'.encode())
                    self.log.info(f"Write enabled {decode_list(ser.readlines())}")
                ser.write(f'{command}\r'.encode())
                reply = decode_list(ser.readlines())
            self.log.info(f"Sent command {command}, reply is {reply}")

        return True, reply

    def set_baudrate(self, session, params=None):
        """Set the baudrate of the serial communication.

        Parameters
        ----------
        baudrate: int
            Either 9600 or 19200.
        """
        if params is None:
            params = {}

        baudrate = params['baudrate']

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            with serial.serial_for_url(url=f'socket://{self.ip}:{self.port}',
                                       baudrate=baudrate, timeout=3) as ser:
                if baudrate == 9600:
                    write_serial_command(ser, "*99!BR=S", write_enabled=True)
                elif baudrate == 19200:
                    write_serial_command(ser, "*99!BR=F", write_enabled=True)
                else:
                    print("Baudrate must be 9600 or 19200")
                self.baudrate = baudrate
                self.log.info
                ("May need to change baudrate in serial to ethernet converter")

        return True, f"Baudrate set to {baudrate}"


def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--acq", default=True, type=bool,
                        help="Automatically start data acqusition")
    pgroup.add_argument("--ip", help="ip address of the serial/ethernet converter")
    pgroup.add_argument("--port", help="Port on the serial/ethernet converter")
    pgroup.add_argument("--baudrate", default=9600, help="Baudrate for serial connection")
    pgroup.add_argument("--sample-rate", default=10, help="Sampling frequency (Hz) for B field")
    pgroup.add_argument("--acq-chunk", default=10,
                        help="Amount of time (s) to continuously sample")

    return parser


if __name__ == '__main__':
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    args = parser.parse_args()

    site_config.reparse_args(args, "HoneywellHMR2300Agent")

    agent, runner = ocs_agent.init_site_agent(args)

    listener = HoneywellHMR2300Agent(agent,
                                     args.ip,
                                     args.port,
                                     args.sample_rate,
                                     args.acq_chunk,
                                     args.baudrate)

    agent.register_task('send_serial_command', listener.send_serial_command)
    agent.register_task('set_baudrate', listener.set_baudrate)
    agent.register_process('acq', listener.start_acq, listener.stop_acq, startup=bool(args.acq))

    runner.run(agent, auto_reconnect=True)

    