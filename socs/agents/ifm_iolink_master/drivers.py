"""Sensor extraction functions for IFM IO-Link devices.

Each extractor takes a hex string (the raw process data from the IO-Link
device) and returns a dict of {field_name: value} with physical units.

To add a new sensor type, write an extract function and add it to
SENSOR_EXTRACTORS.
"""


def extract_sbn246(hex_value):
    """Decode SBN246 flowmeter process data.

    Returns flow in liters/min and temperature in Celsius.
    """
    binary = bin(int(hex_value, 16))[2:].zfill(32)
    flow_gpm = int(binary[0:16], 2) / 10
    temp_f = int(binary[16:30], 2)
    flow_lpm = round(flow_gpm * 3.785411784, 1)
    temp_c = round((temp_f - 32) * (5 / 9), 1)
    return {'flow': flow_lpm, 'temperature': temp_c}


def extract_kq1001(hex_value):
    """Decode KQ1001 level sensor process data.

    Returns level in percent and device status integer.
    """
    binary = bin(int(hex_value, 16))[2:].zfill(32)
    level = int(binary[0:16], 2) * 1.0
    status = int(binary[24:28], 2)
    return {'level': level, 'status': status}


def extract_generic(hex_value):
    """Passthrough for unknown sensor types."""
    return {'raw_value': hex_value}


SENSOR_EXTRACTORS = {
    'SBN246': extract_sbn246,
    'KQ1001': extract_kq1001,
    'generic': extract_generic,
}
