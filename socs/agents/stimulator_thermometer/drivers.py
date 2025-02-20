#!/usr/bin/env python3
"""Module to handle thermometers connected to KR260 via SPI bus.
"""

from pathlib import Path


class StimThermoError(Exception):
    """Exception raised by stimulator thermometer."""


class Iio:
    """Generic IIO driver.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the iio device directory.
    """

    def __init__(self, path):
        self._path = Path(path)

    def read(self, name):
        """Read the file in the iio directory.

        Parameters
        ----------
        name : str
            File name in IIO directory.

        Returns
        -------
        data : str
            Contents of the file.
        """
        with open(self._path.joinpath(name), 'r') as fd:
            return fd.readline().strip()

    @property
    def name(self):
        """Read name of the iio device.

        Returns
        -------
        name : str
            Name of the device.
        """
        return self.read('name')


class Max31856(Iio):
    """Class to read MAX31856 via IIO interface.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the iio device directory.
    """
    @property
    def thermocouple_type(self):
        """Get thermocouple type.

        Returns
        -------
        type : str
            Thermocouple type in string.
        """
        return self.read('in_temp_thermocouple_type')

    def get_temp_raw(self):
        """Get raw temperature.

        Returns
        -------
        temp_raw : int
            Raw temperature.
        """
        return int(self.read('in_temp_raw'))

    def get_temp(self):
        """Get temperature in degrees Celsius.

        Returns
        -------
        temp : float
            Temperature in degrees Celsius.
        """
        return self.get_temp_raw() / 2**7

    def get_temp_ambient_raw(self):
        """Get raw ambient temperature.

        Returns
        -------
        temp_ambient_raw : int
            Raw ambient temperature.
        """
        return int(self.read('in_temp_ambient_raw'))

    def get_temp_ambient(self):
        """Get ambient temperature in degrees Celsius.

        Returns
        -------
        temp_ambient : float
            Ambient temperature in degrees Celsius.
        """
        return self.get_temp_ambient_raw() / 2**6


class Max31865(Iio):
    """Class to read MAX31865 via IIO interface.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the iio device directory.
    """
    R_REF = 4300
    R_0 = 1000
    ALPHA = 0.0039

    def get_temp_raw(self):
        """Get raw temperature.

        Returns
        -------
        temp_raw : int
            Raw temperature.
        """
        return int(self.read('in_temp_raw'))

    def get_temp(self):
        """Get temperature in degrees Celsius.

        Returns
        -------
        temp : float
            Temperature in degrees Celsius.
        """
        r_rtd = self.R_REF * self.get_temp_raw() / 32768

        return (r_rtd / self.R_0 - 1) / self.ALPHA


def from_spi_node_path(path):
    """Return device class from path to the SPI directory.

    Paramter
    --------
    path : str or pathlib.Path
        Path to the SPI node directory like
        /sys/bus/spi/devices/spi3.0/

    Returns
    -------
    dev : Max31865 or Max31856
        Device class.
    """
    path_iio = list(Path(path).glob('iio*'))
    if len(path_iio) != 1:
        raise StimThermoError(f'IIO definition not found: {path_iio}')

    dev_iio = Iio(path_iio[0])

    name_dev = dev_iio.name

    if name_dev == 'max31856':
        return Max31856(path_iio[0])
    elif name_dev == 'max31865':
        return Max31865(path_iio[0])
    else:
        raise StimThermoError('Thermometer type not supported.')


def main():
    """ Main function """
    paths = ['/sys/bus/spi/devices/spi3.0/',
             '/sys/bus/spi/devices/spi3.1/',
             '/sys/bus/spi/devices/spi3.3/',
             '/sys/bus/spi/devices/spi3.4/']
    thermometers = [from_spi_node_path(path) for path in paths]

    for dev in thermometers:
        print(dev.get_temp())
        if isinstance(dev, Max31856):
            print(dev.get_temp_ambient())


if __name__ == '__main__':
    main()
