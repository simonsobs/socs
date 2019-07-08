import socket
import argparse
import numpy as np
import logging

BUFF_SIZE = 1024


class Lakeshore240_Simulator:

    def __init__(self, port, num_channels=8, sn="LSSIM"):
        self.log = logging.getLogger()

        self.port = port
        self.sn = sn
        self.modname = "SIM_MODULE"

        self.num_channels = num_channels
        self.channels = [ChannelSim(i+1, "Channel {}".format(i+1))
                         for i in range(self.num_channels)]

        self.cmds = {
            "*IDN?": self.get_idn,
            "CRDG?": lambda x: self.get_reading(*x, unit='C'),
            "FRDG?": lambda x: self.get_reading(*x, unit='F'),
            "KRDG?": lambda x: self.get_reading(*x, unit='K'),
            "SRDG?": lambda x: self.get_reading(*x, unit='S'),
            "MODNAME": self.set_modname,
            "MODNAME?": self.get_modname,
            "INNAME": self.set_channel_name,
            "INNAME?": self.get_channel_name,
            "INTYPE": self.set_channel_intype,
            "INTYPE?": self.get_channel_intype,
            "SET_VALUE": self.set_channel_value
        }

    def set_modname(self, name):
        self.modname = name

    def get_modname(self):
        return self.modname

    def set_channel_value(self, chan, value):
        chan_index = int(chan) - 1
        if not 0 <= chan_index < self.num_channels:
            self.log.warning(f"chan num must be between 1 and {self.num_channels}")
            return

        self.channels[chan_index].set_value(value)

    def get_channel_intype(self, chan):
        chan_index = int(chan) - 1
        if not 0 <= chan_index < self.num_channels:
            self.log.warning(f"chan num must be between 1 and {self.num_channels}")
            return

        return self.channels[chan_index].get_intype()

    def set_channel_intype(self, chan, *args):
        chan_index = int(chan) - 1
        if not 0 <= chan_index < self.num_channels:
            self.log.warning(f"chan num must be between 1 and {self.num_channels}")
            return

        args = map(int, args)
        self.channels[chan_index].set_intype(*args)

    def get_channel_name(self, chan):
        if not 0 < int(chan) <= self.num_channels:
            self.log.warning(f"chan num must be between 1 and {self.num_channels}")
            return

        return self.channels[int(chan)-1].name

    def set_channel_name(self, chan, name):
        if not 0 < int(chan) <= self.num_channels:
            self.log.warning(f"chan num must be between 1 and {self.num_channels}")
            return

        self.channels[int(chan)-1].name = name

    def run(self):

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Checks self.port plus the next ten to see if they're open
        for p in range(self.port, self.port+10):
            try:
                self.log.info(f"Trying to listen on port {p}")
                sock.bind(('localhost', p))
                break
            except OSError as e:
                if e.errno == 48:
                    self.log.warning(f"Address {p} is already in use")
                else:
                    raise(e)
        else:
            print(f"Could not connect to ports in {range(self.port, self.port+5)}")

        sock.listen(1)

        while True:
            self.log.info('waiting for a connection....')
            conn, client_address = sock.accept()
            self.log.info(f"Made connection with {client_address}")
            with conn:

                # Main data loop
                while True:
                    data = conn.recv(BUFF_SIZE)

                    if not data:
                        self.log.info("Connection closed by client")
                        break

                    self.log.debug("Command: {}".format(data))
                    # Only takes first command in case multiple commands are s
                    cmds = data.decode().split(';')

                    for c in cmds:
                        if c.strip() == '':
                            continue

                        cmd_list = c.strip().split(' ')

                        if len(cmd_list) == 1:
                            cmd, args = cmd_list[0], []
                        else:
                            cmd, args = cmd_list[0], cmd_list[1].split(',')
                        self.log.debug(f"{cmd} {args}")

                        try:
                            cmd_fn = self.cmds.get(cmd)
                            if cmd_fn is None:
                                self.log.warning(f"Command {cmd} is not registered")
                                continue

                            resp = cmd_fn(*args)

                        except TypeError as e:
                            self.log.error(f"Command error: {e}")
                            continue

                        if resp is not None:
                            conn.send(resp.encode())

    def get_idn(self):
        return ','.join([
            "Lakeshore",
            "LSSIM_{}P".format(self.num_channels),
            self.sn,
            'v0.0.0'
        ])

    def get_reading(self, channel_num, unit='S'):
        chan_index = int(channel_num) - 1
        if not 0 <= chan_index < self.num_channels:
            self.log.warning(f"chan num must be between 1 and {self.num_channels}")
            return

        return self.channels[chan_index].get_reading(unit=unit)


class ChannelSim:
    def __init__(self, channel_num, name):
        self.log = logging.getLogger()

        self.channel_num = channel_num
        self.name = name

        self.sensor_type = 1
        self.autorange = 0
        self.range = 0
        self.current_reversal = 0
        self.units = 3
        self.enabled = 0
        self.value = 100

    def get_intype(self):
        return ','.join([
            str(self.sensor_type),
            str(self.autorange),
            str(self.range),
            str(self.current_reversal),
            str(self.units),
            str(self.enabled),
        ])

    def set_intype(self, sensor_type, autorange, rng, current_reversal, units, enabled):
        if sensor_type in [1,2,3]:
            self.log.debug(f"Setting sensor type to {sensor_type}")
            self.sensor_type = sensor_type

        if autorange in [0,1]:
            self.autorange = autorange

        if (self.sensor_type in [1,2] and rng in [0]) or \
            (self.sensor_type == 3 and rng in range(9)):
            self.range = rng

        if self.sensor_type in [2,3] and current_reversal in [0,1]:
            self.log.debug(f"Setting chan {self.channel_num} "
                           f"current_reversal to {current_reversal}")
            self.current_reversal = current_reversal

        if units in [1,2,3,4]:
            self.log.debug(f"Setting chan {self.channel_num} units to {units}")
            self.units = units

        if enabled in [0,1]:
            self.log.debug(f"Setting chan {self.channel_num} enabled to {enabled}")
            self.enabled = enabled

    def set_value(self, value):
        self.log.debug(f"Setting value to {value}")
        self.value = float(value)

    def get_reading(self, unit='S'):
        if not self.enabled:
            rv = 0
        else:
            rv = np.random.normal(self.value)

        return str(rv)


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--port', type=int, default=1094,
                        help="Port which simulator will wait for a connection."
                             "If taken, it will test several consecutive ports"
                             "until it finds one that is free.")
    parser.add_argument('--num-channels', type=int, default=8,
                        help="Number of channels which the simulator will have.")
    parser.add_argument('--sn', type=str, default='LS_SIM',
                        help="Serial number for the device")
    parser.add_argument('--log-file', type=str, default=None,
                        help="File where logs are written")
    parser.add_argument('--log-level',
                        choices=['debug', 'info', 'warning', 'error'],
                        default='info',
                        help="Minimum log level to be displayed")
    parser.add_argument('-o', '--log-stdout', action="store_true",
                        help="Log to stdout")
    return parser


if __name__ == '__main__':

    parser = make_parser()
    args = parser.parse_args()

    log_level = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR
    }[args.log_level]

    format_string = '%(asctime)-15s [%(levelname)s]:  %(message)s'
    # logging.basicConfig(level=log_level, format=format_string)
    formatter = logging.Formatter(format_string)
    log = logging.getLogger()
    log.setLevel(log_level)

    if args.log_file is None or args.log_stdout:
        consoleHandler = logging.StreamHandler()
        consoleHandler.setFormatter(formatter)
        log.addHandler(consoleHandler)

    if args.log_file is not None:
        fileHandler = logging.FileHandler(args.log_file)
        fileHandler.setFormatter(formatter)
        log.addHandler(fileHandler)

    ls = Lakeshore240_Simulator(args.port,
                                num_channels=args.num_channels,
                                sn=args.sn)

    ls.run()
