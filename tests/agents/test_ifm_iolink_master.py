"""Tests for IFM IO-Link Master agent sensor extraction functions."""

import pytest

from socs.agents.ifm_iolink_master.drivers import (
    SENSOR_EXTRACTORS,
    extract_generic,
    extract_kq1001,
    extract_sbn246,
)


class TestExtractSBN246:
    """Test SBN246 flowmeter extraction.

    The SBN246 process data is 32 bits:
      bits[0:16]  = flow in gallons/min * 10
      bits[16:30] = temperature in Fahrenheit
    """

    def test_known_value(self):
        # flow = 0x01A4 = 420 -> 42.0 gpm -> 159.0 L/min
        # temp (bits 16:30) = need to construct carefully
        # Let's use a value from the existing agent:
        # binary: 0000000110100100 00000101000000 00
        #         flow=420 (42.0gpm)  temp=320 (320F)
        # hex of that 32-bit: 01A4 1400 -> but let's compute properly
        # flow_bits = 420 = 0b0000000110100100
        # temp_bits = 320 = 0b00000101000000 (14 bits)
        # remaining 2 bits = 00
        # full binary: 0000000110100100 00000101000000 00
        # = 0000 0001 1010 0100 0000 0101 0000 0000
        # = 0x01A40500
        result = extract_sbn246('01A40500')
        # 42.0 gpm * 3.785411784 = 159.0 L/min
        assert result['flow'] == 159.0
        # 320 F -> (320-32)*5/9 = 160.0 C
        assert result['temperature'] == 160.0

    def test_zero(self):
        result = extract_sbn246('00000000')
        assert result['flow'] == 0.0
        # temp_f = 0 -> (0-32)*5/9 = -17.8 C
        assert result['temperature'] == -17.8

    def test_typical_cooling_loop(self):
        # Typical cooling: ~11 gpm flow, ~68F (20C) water temp
        # flow = 110 (11.0 gpm) = 0b0000000001101110
        # temp = 68F = 0b00000001000100 (14 bits)
        # remaining = 00
        # binary: 0000000001101110 00000001000100 00
        # = 0000 0000 0110 1110 0000 0001 0001 0000
        # = 0x006E0110
        result = extract_sbn246('006E0110')
        # 11.0 gpm * 3.785411784 = 41.6 L/min
        assert result['flow'] == 41.6
        # 68F -> (68-32)*5/9 = 20.0 C
        assert result['temperature'] == 20.0

    def test_returns_dict_with_expected_keys(self):
        result = extract_sbn246('00000000')
        assert 'flow' in result
        assert 'temperature' in result
        assert len(result) == 2


class TestExtractKQ1001:
    """Test KQ1001 level sensor extraction.

    The KQ1001 process data is 32 bits:
      bits[0:16]   = PDV1 (level value)
      bits[24:28]  = device status
    """

    def test_full_level(self):
        # level = 1000 (100.0%), status = 0
        # level_bits = 1000 = 0b0000001111101000
        # bits 16:24 = 00000000 (scale)
        # status_bits = 0b0000
        # bits 28:32 = 0000
        # binary: 0000001111101000 00000000 0000 0000
        # = 0x03E80000
        result = extract_kq1001('03E80000')
        assert result['level'] == 1000.0
        assert result['status'] == 0

    def test_zero_level(self):
        result = extract_kq1001('00000000')
        assert result['level'] == 0.0
        assert result['status'] == 0

    def test_status_nonzero(self):
        # level = 500, status = 3
        # level_bits = 500 = 0b0000000111110100
        # bits 16:24 = 00000000
        # status = 3 = 0b0011
        # bits 28:32 = 0000
        # binary: 0000000111110100 00000000 0011 0000
        # = 0x01F40030
        result = extract_kq1001('01F40030')
        assert result['level'] == 500.0
        assert result['status'] == 3

    def test_returns_dict_with_expected_keys(self):
        result = extract_kq1001('00000000')
        assert 'level' in result
        assert 'status' in result
        assert len(result) == 2


class TestExtractGeneric:
    """Test generic passthrough extraction."""

    def test_passthrough(self):
        result = extract_generic('DEADBEEF')
        assert result == {'raw_value': 'DEADBEEF'}

    def test_empty_string(self):
        result = extract_generic('')
        assert result == {'raw_value': ''}


class TestSensorRegistry:
    """Test the SENSOR_EXTRACTORS registry."""

    def test_sbn246_registered(self):
        assert 'SBN246' in SENSOR_EXTRACTORS
        assert SENSOR_EXTRACTORS['SBN246'] is extract_sbn246

    def test_kq1001_registered(self):
        assert 'KQ1001' in SENSOR_EXTRACTORS
        assert SENSOR_EXTRACTORS['KQ1001'] is extract_kq1001

    def test_generic_registered(self):
        assert 'generic' in SENSOR_EXTRACTORS
        assert SENSOR_EXTRACTORS['generic'] is extract_generic

    def test_unknown_sensor_falls_back(self):
        extractor = SENSOR_EXTRACTORS.get('UNKNOWN_SENSOR', extract_generic)
        assert extractor is extract_generic


class TestParsePortArg:
    """Test the --port argument parser."""

    def test_valid_port(self):
        from socs.agents.ifm_iolink_master.agent import parse_port_arg
        result = parse_port_arg('1:SBN246')
        assert result == {'port': 1, 'sensor_type': 'SBN246'}

    def test_valid_port_high_number(self):
        from socs.agents.ifm_iolink_master.agent import parse_port_arg
        result = parse_port_arg('8:KQ1001')
        assert result == {'port': 8, 'sensor_type': 'KQ1001'}

    def test_invalid_no_colon(self):
        from socs.agents.ifm_iolink_master.agent import parse_port_arg
        import argparse
        with pytest.raises(argparse.ArgumentTypeError):
            parse_port_arg('1SBN246')

    def test_invalid_port_number(self):
        from socs.agents.ifm_iolink_master.agent import parse_port_arg
        import argparse
        with pytest.raises(argparse.ArgumentTypeError):
            parse_port_arg('X:SBN246')
