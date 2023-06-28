# To run the simulator: python3 ls372_simulator.py -p 7777
# (Since it automatically tries nearby ports, sometimes it will connect to 7778 when restarted,
# so you may need to temporarily change the port in Lakeshore372.py or just try running it again)
#
# To interact with the simulator:
# Connect 372 agent: python3 -i Lakeshore372.py 'localhost'

# There are two ways to communicate -- either by using specific functions from the agent, such as
# ls.get_autoscan(), ls.channels[1].get_input_setup(), ls.sample_heater.get_output_mode()

# or by using the ls.msg() function and the interface command formatting from the 372 manual, such as
# ls.msg('SCAN?'), ls.msg('INTYPE? 1'), ls.msg('OUTMODE? 0')


import argparse
import logging
import os
import socket
import time

import numpy as np

BUFF_SIZE = 4096

voltage_excitation_key = {1: 2.0e-6,
                          2: 6.32e-6,
                          3: 20.0e-6,
                          4: 63.2e-6,
                          5: 200.0e-6,
                          6: 632.0e-6,
                          7: 2.0e-3,
                          8: 6.32e-3,
                          9: 20.0e-3,
                          10: 63.2e-3,
                          11: 200.0e-3,
                          12: 632.0e-3}

current_excitation_key = {1: 1.0e-12,
                          2: 3.16e-12,
                          3: 10.0e-12,
                          4: 31.6e-12,
                          5: 100.0e-12,
                          6: 316.0e-12,
                          7: 1.0e-9,
                          8: 3.16e-9,
                          9: 10.0e-9,
                          10: 31.6e-9,
                          11: 100.0e-9,
                          12: 316.0e-9,
                          13: 1.0e-6,
                          14: 3.16e-6,
                          15: 10.0e-6,
                          16: 31.6e-6,
                          17: 100.0e-6,
                          18: 316.0e-6,
                          19: 1.0e-3,
                          20: 3.16e-3,
                          21: 10.0e-3,
                          22: 31.6e-3}


class Lakeshore372_Simulator:
    def __init__(self, port, num_channels=16, sn="LSASIM"):
        self.log = logging.getLogger()

        self.port = port
        self.sn = sn

        self.num_channels = num_channels
        self.channels = []
        for i in range(self.num_channels + 1):
            if i == 0:
                c = ChannelSim('A', "Channel A")
            else:
                c = ChannelSim(i, "Channel {}".format(i))
            self.channels.append(c)
            self.log.debug(f'Created channel "{self.channels[i].name}"')

        self.scanner = 1  # 0 = autoscan off; 1 = autoscan on
        self.active_channel = 1  # start on channel 1

        self.heaters = []
        for i in range(3):
            h = Heater(i)
            self.heaters.append(h)

        self.curves = []
        for i in range(60):
            v = Curve(i)
            self.curves.append(v)

        self.cmds = {
            # Lakeshore and channel commands
            "*IDN?": self.get_idn,
            "RDGK?": lambda x: self.get_reading(chan=x, unit='1'),
            "RDGR?": lambda x: self.get_reading(chan=x, unit='2'),
            "SRDG?": lambda x: self.get_reading(chan=x, unit='2'),
            "KRDG?": lambda x: self.get_reading(chan=x, unit='1'),
            "RDGST?": self.get_reading_status,
            "INNAME": self.set_channel_name,
            "INNAME?": self.get_channel_name,
            "INTYPE": self.set_channel_intype,
            "INTYPE?": self.get_channel_intype,
            "SET_VALUE": self.set_channel_value,
            "SCAN": self.set_scanner,
            "SCAN?": self.get_scanner,
            "INSET": self.set_input_parameters,
            "INSET?": self.get_input_parameters,
            "TLIMIT": self.set_tlimit,
            "TLIMIT?": self.get_tlimit,
            "RDGPWR?": self.get_rdgpwr,
            # Heater commands
            "OUTMODE?": self.get_outmode,
            "OUTMODE": self.set_outmode,
            "HTR?": self.get_htr,
            "HTRSET?": self.get_htrset,
            "HTRSET": self.set_htrset,
            "MOUT?": self.get_mout,
            "MOUT": self.set_mout,
            "RAMP?": self.get_ramp,
            "RAMP": self.set_ramp,
            "RAMPST": self.get_ramp_status,
            "RANGE?": self.get_heater_range,
            "RANGE": self.set_heater_range,
            "SETP?": self.get_setpoint,
            "SETP": self.set_setpoint,
            "STILL?": self.get_still,
            "STILL": self.set_still,
            "PID?": self.get_pid,
            "PID": self.set_pid,
            # Curve commands
            "CRVHDR?": self.get_curve_header,
            "CRVHDR": self.set_curve_header,
            "CRVPT?": self.get_curve_data,
            "CRVPT": self.set_curve_data,
            "CRVDEL": self.delete_curve,
        }

    def set_channel_value(self, chan, value):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        self.channels[chan_index].set_value(value)

    def get_channel_intype(self, chan):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        return self.channels[chan_index].get_intype()

    def set_channel_intype(self, chan, *args):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        args = map(int, args)
        self.channels[chan_index].set_intype(*args)

    def get_channel_name(self, chan):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        return self.channels[chan_index].name

    def set_channel_name(self, chan, name):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        self.channels[chan_index].name = name

    def run(self):

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Checks self.port plus the next ten to see if they're open
        for p in range(self.port, self.port + 10):
            try:
                self.log.info(f"Trying to listen on port {p}")
                sock.bind(('', p))
                break
            except OSError as e:
                if e.errno == 48:
                    self.log.warning(f"Address {p} is already in use")
                else:
                    raise (e)
        else:
            print(f"Could not connect to ports in {range(self.port, self.port + 5)}")

        sock.listen(1)

        while True:
            self.log.info('waiting for a connection....')
            conn, client_address = sock.accept()
            self.log.info(f"Made connection with {client_address}")
            with conn:

                # Main data loop
                while True:
                    data = conn.recv(BUFF_SIZE)
                    elapsed_time = time.time() - start_time
                    # self.log.debug('time:', elapsed_time)  # timestamp printed every time a command is received

                    if not data:
                        self.log.info("Connection closed by client")
                        break

                    clean_cmd = data.decode().strip()
                    self.log.info(f"Received command: {clean_cmd}")
                    self.log.debug("Raw Command: {}".format(data))
                    # Only takes first command in case multiple commands are s
                    cmds = data.decode().split(';')

                    if int(self.scanner) == 1:  # useful only if all channels have the same dwell and pause settings
                        channel_change = int(elapsed_time // (self.channels[int(self.active_channel)].dwell
                                                              + self.channels[int(self.active_channel)].pause))
                        # print(channel_change)
                        if 0 < channel_change < 16:
                            self.active_channel = 1 + channel_change
                        elif channel_change >= 16:
                            new_channel_change = int(channel_change % 16)
                            self.active_channel = 1 + new_channel_change

                        self.log.debug(f"Active channel: {self.active_channel}")

                    elif int(self.scanner) == 0:
                        pass

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
                            self.log.info(f"Sent response: {resp}")

                        except TypeError as e:
                            self.log.error(f"Command error: {e}")
                            continue

                        if resp is not None:
                            conn.send(resp.encode())

    def get_idn(self):
        return ','.join([
            "LSCI",
            "MODEL372",
            self.sn,
            '0.0'
        ])

    def get_reading(self, chan, unit='S'):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        return self.channels[chan_index].get_reading(unit=unit)

    def get_reading_status(self, chan):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        bit_string = "000"
        return bit_string

    def get_scanner(self):
        msg_string = '{:02d},{} '.format(int(self.active_channel), str(self.scanner))
        self.log.debug(f"get_scanner: {msg_string}")
        return msg_string

    def set_scanner(self, chan, auto):
        if not 0 <= int(chan) <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        self.active_channel = int(chan)
        self.scanner = int(auto)

    def get_input_parameters(self, chan):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        return self.channels[chan_index].get_inset()

    def set_input_parameters(self, chan, *args):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        args = map(int, args)
        self.channels[chan_index].set_inset(*args)

    def get_tlimit(self, chan):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        temp = str(self.channels[chan_index].temp_limit)
        return temp

    def set_tlimit(self, chan, limit):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        self.channels[chan_index].temp_limit = float(limit)

    def get_rdgpwr(self, chan):
        if chan == 'A':
            chan_index = 0
        else:
            chan_index = int(chan)
        if not 0 <= chan_index <= self.num_channels:
            self.log.warning(f"chan num must be A or between 1 and {self.num_channels}")
            return

        return self.channels[chan_index].get_excitation_power()

    def get_outmode(self, heater_output):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be between 0 and 2")
            return

        return self.heaters[int(heater_output)].get_output_mode()

    def set_outmode(self, heater_output, *args):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be between 0 and 2")
            return

        args = map(str, args)
        self.heaters[int(heater_output)].set_output_mode(*args)

    def get_htr(self):
        """Random sample heater value."""
        return f"+{np.random.rand():.4f}E+00"

    def get_htrset(self, heater_output):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be 0 or 1")
            return

        return self.heaters[int(heater_output)].get_heater_setup()

    def set_htrset(self, heater_output, *args):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be 0 or 1")
            return

        args = map(int, args)
        self.heaters[int(heater_output)].set_heater_setup(*args)

    def get_mout(self, heater_output):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be between 0 and 2")
            return

        return str(self.heaters[int(heater_output)].output_value)

    def set_mout(self, heater_output, value):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be between 0 and 2")
            return

        self.heaters[int(heater_output)].output_value = float(value)

    def get_ramp(self, heater_output):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be between 0 and 2")
            return

        ramp_string = '{},{}'.format(str(self.heaters[int(heater_output)].ramp),
                                     str(self.heaters[int(heater_output)].rate))
        return ramp_string

    def set_ramp(self, heater_output, enabled, value):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be between 0 and 2")
            return

        if int(enabled) in [0, 1]:
            self.heaters[int(heater_output)].ramp = int(enabled)
        else:
            self.log.warning("0 = ramping off, 1 = ramping on")
            return

        if 0.001 <= float(value) <= 100:
            self.heaters[int(heater_output)].rate = float(value)
        else:
            self.log.warning("setpoint ramp rate must be between 0.001 and 100 k/min")
            return

    def get_ramp_status(self, heater_output):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be between 0 and 2")
            return

        return str(self.heaters[int(heater_output)].status)

    def get_heater_range(self, heater_output):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be between 0 and 2")
            return

        return str(self.heaters[int(heater_output)].rng)

    def set_heater_range(self, heater_output, heater_range):
        if not 0 <= int(heater_output) <= 2:
            self.log.warning("heater output must be between 0 and 2")
            return

        self.heaters[int(heater_output)].rng = int(heater_range)

    def get_setpoint(self, heater_output):
        if not 0 <= int(heater_output) < 2:
            self.log.warning("heater output must be 0 or 1")
            return

        return str(self.heaters[int(heater_output)].setpoint)

    def set_setpoint(self, heater_output, setp):
        if not 0 <= int(heater_output) < 2:
            self.log.warning("heater output must be 0 or 1")
            return

        self.heaters[int(heater_output)].setpoint = setp

    def get_still(self):
        return str(self.heaters[2].output_value)

    def set_still(self, output):
        self.heaters[2].output_value = float(output)

    def get_pid(self):
        return ','.join([str(self.heaters[0].P), str(self.heaters[0].I), str(self.heaters[0].D)])

    def set_pid(self, heater_output, p, i, d):
        if not 0 <= int(heater_output) < 2:
            self.log.warning("heater output must be 0 or 1")
            return

        if 0.0 <= float(p) <= 1000:
            self.heaters[int(heater_output)].p = float(p)
        else:
            self.log.warning("P value must be between 0.0 and 1000")
            return

        if 0 <= float(i) <= 10000:
            self.heaters[int(heater_output)].i = float(i)
        else:
            self.log.warning("I value must be between 0 and 10000")
            return

        if 0 <= float(d) <= 2500:
            self.heaters[int(heater_output)].d = float(d)
        else:
            self.log.warning("D value must be between 0 and 2500")
            return

    def get_curve_header(self, curve):
        curve_index = int(curve)
        if not 1 <= curve_index <= 59:
            self.log.warning("curve num must be between 1 and 59")
            return

        return self.curves[curve_index].get_header()

    def set_curve_header(self, curve, *args):
        curve_index = int(curve)
        if not 21 <= curve_index <= 59:
            self.log.warning("curve num must be between 21 and 59")
            return

        args = map(str, args)
        self.curves[curve_index].set_header(*args)

    def get_curve_data(self, curve, index):
        curve_index = int(curve)
        if not 1 <= curve_index <= 59:
            self.log.warning("curve num must be between 1 and 59")
            return

        return '{},{},{}'.format(str(self.curves[curve_index].data[int(index)][0]),
                                 str(self.curves[curve_index].data[int(index)][1]),
                                 str(self.curves[curve_index].data[int(index)][2]))

    def set_curve_data(self, curve, index, units, kelvin, curvature=0):
        curve_index = int(curve)
        if not 21 <= curve_index <= 59:
            self.log.warning("curve num must be between 21 and 59")
            return

        self.curves[curve_index].data[int(index)][0] = float(units)
        self.curves[curve_index].data[int(index)][1] = float(kelvin)
        self.curves[curve_index].data[int(index)][2] = float(curvature)

    def delete_curve(self, curve):
        curve_index = int(curve)
        if not 21 <= curve_index <= 59:
            self.log.warning("curve num must be between 21 and 59")
            return

        for i in range(1, 201):
            self.curves[curve_index].data[i][0] = 0
            self.curves[curve_index].data[i][1] = 0
            self.curves[curve_index].data[i][2] = 0


class ChannelSim:
    def __init__(self, channel_num, name):
        self.log = logging.getLogger()

        self.channel_num = channel_num
        self.name = name
        self.temp_limit = 0

        self.enabled = 1
        self.dwell = 10
        self.pause = 3
        self.curve_number = 0
        self.tempco = 1

        if channel_num == 'A':
            self.mode = 1
        else:
            self.mode = 0
        self.excitation = 1
        self.autorange = 0
        self.rng = 1
        self.cs_shunt = 0
        self.units = 1
        self.value = 100

    def get_intype(self):
        return ','.join([
            str(self.mode),
            str(self.excitation),
            str(self.autorange),
            str(self.rng),
            str(self.cs_shunt),
            str(self.units)
        ])

    def set_intype(self, mode, excitation, autorange, rng, cs_shunt, units):
        if mode in [0, 1]:
            self.log.debug(f"Setting mode to {mode}")
            self.mode = mode

        if excitation in range(1, 13) and self.mode == 0:
            self.excitation = excitation

        if excitation in range(1, 23) and self.mode == 1:
            self.excitation = excitation

        if autorange in [0, 1, 2]:
            self.autorange = autorange

        if rng in range(1, 23):
            self.rng = rng

        if cs_shunt in [0, 1]:
            self.cs_shunt = cs_shunt

        if units in [1, 2]:
            self.units = units

    def set_value(self, value):
        self.log.debug(f"Setting value to {value}")
        self.value = float(value)

    def get_reading(self, unit='S'):
        if self.enabled == 0:
            rv = 0
        else:
            rv = np.random.normal(self.value)

        return str(rv)

    def get_inset(self):
        return ','.join([
            str(self.enabled),
            str(self.dwell),
            str(self.pause),
            str(self.curve_number),
            str(self.tempco)
        ])

    def set_inset(self, enabled, dwell, pause, curve_number, tempco):
        if enabled in [0, 1]:
            self.log.debug(f"Setting mode to {enabled}")
            self.enabled = enabled

        if dwell in range(1, 201) and self.channel_num != 'A':
            self.dwell = dwell

        if pause in range(3, 201):
            self.pause = pause

        if curve_number in range(59):
            self.curve_number = curve_number

        if tempco in [1, 2]:
            self.tempco = tempco

    def get_excitation_power(self):
        if self.mode == 0:
            pwr = (voltage_excitation_key[int(self.excitation)]**2) / (float(self.get_reading()))
        if self.mode == 1:
            pwr = (current_excitation_key[int(self.excitation)]**2) * (float(self.get_reading()))

        return str(pwr)


class Heater:
    def __init__(self, output):
        self.output = output
        self.mode = 0
        self.input = 1
        self.powerup = 0
        self.polarity = 0
        self.filter = 0
        self.delay = 5

        self.rng = 0

        self.resistance = 1
        self.max_current = 0
        self.max_user_current = 0
        self.display = 1

        self.output_value = 0

        self.ramp = 0
        self.rate = 0
        self.status = 0

        self.setpoint = 0

        self.p = 0
        self.i = 0
        self.d = 0

    def get_output_mode(self):
        return ','.join([
            str(self.mode),
            str(self.input),
            str(self.powerup),
            str(self.polarity),
            str(self.filter),
            str(self.delay)
        ])

    def set_output_mode(self, output, mode, input, powerup, polarity, filter, delay):
        if int(output) in [0, 1, 2]:
            self.log.debug(f"Setting output to {output}")
            self.output = int(output)

        if (int(output) == 0 and int(mode) in [0, 2, 3, 5]) or (int(output) == 1 and int(mode) in [0, 2, 3, 5, 6]) or (int(output) == 2 and int(mode) in [0, 1, 2, 4]):
            self.mode = int(mode)

        if input == 'A':
            self.input = input
        elif int(input) in range(1, 17):
            self.input = int(input)

        if int(powerup) in [0, 1]:
            self.powerup = int(powerup)

        if int(polarity) in [0, 1] and int(output) != 1:
            self.polarity = int(polarity)

        if int(filter) in [0, 1]:
            self.filter = int(filter)

        if int(delay) in range(1, 256):
            self.delay = int(delay)

    def get_heater_setup(self):
        return ','.join([
            str(self.resistance),
            str(self.max_current),
            str(self.max_user_current),
            str(self.display)
        ])

    def set_heater_setup(self, output, resistance, max_current, max_user_current, display):
        if output in [0, 1]:
            self.output = output

        if (output == 0 and resistance in range(1, 2001)) or (output == 1 and resistance in [1, 2]):
            self.resistance = resistance

        if max_current in [0, 1, 2]:
            self.max_current = max_current

        # if max_user_current in []
        # not sure what condition to use
        self.max_user_current = max_user_current

        if display in [1, 2]:
            self.display = display


class Curve:
    def __init__(self, num):
        self.curve_num = num
        self.name = "User Curve"
        self.serial_number = None
        self.format = 4
        self.limit = 40.0
        self.coefficient = 1

        self.get_header()

        self.units = np.random.random([201])
        self.temp = np.random.random([201])
        self.curvature = 0
        self.data = {i: [self.units[i], self.temp[i], self.curvature] for i in range(1, 201)}

    def get_header(self):
        return ','.join([
            str(self.name),
            str(self.serial_number),
            str(self.format),
            str(self.limit),
            str(self.coefficient)
        ])

    def set_header(self, name, serial_number, format, limit, coefficient):
        self.name = name

        if len(str(serial_number)) <= 10:
            self.serial_number = serial_number

        if int(format) in [3, 4, 7]:
            self.format = format

        if float(limit) in range(1000):
            self.limit = float(limit)

        if int(coefficient) in [1, 2]:
            self.coefficient = int(coefficient)


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--port', type=int, default=50000,
                        help="Port which simulator will wait for a connection. "
                             "If taken, it will test several consecutive ports "
                             "until it finds one that is free.")
    parser.add_argument('--num-channels', type=int, default=16,
                        help="Number of channels which the simulator will have.")
    parser.add_argument('--sn', type=str, default='LSASIM',
                        help="Serial number for the device")
    parser.add_argument('--log-file', type=str, default=None,
                        help="File where logs are written")
    parser.add_argument('-o', '--log-stdout', action="store_true",
                        help="Log to stdout")
    return parser


if __name__ == '__main__':

    parser = make_parser()
    args = parser.parse_args()

    level = os.environ.get('LOGLEVEL', 'info')
    log_level = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR
    }[level]

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

    ls = Lakeshore372_Simulator(args.port,
                                num_channels=args.num_channels,
                                sn=args.sn)
    start_time = time.time()  # begins timer as soon as simulator is created
    ls.run()
