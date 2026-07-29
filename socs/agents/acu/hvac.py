# HVAC fields for the LAT
#
# While most fields are listed explicitly in soaculib, the HVAC fields
# are parsed from the dataset on first read, because we also want to
# use regex to classify them for ocs-web / commanding.

import re
from dataclasses import dataclass

# Feed groups:

# hvac_data: readings (from thermometers), intended to only be
# recorded at low rate.
_DATA = 'hvac_data'

# hvac_ctrl: set points and on/off setting indicators.
_CTRL = 'hvac_ctrl'

# hvac_faults: faults and other flags.
_FAULTS = 'hvac_faults'


HVAC_SCHEMA = [
    {'type': 'ignore',
     'regex': r'Time|Year',
     'name_pattern': '{sname}',
     'cmd_target': '_',
     },

    {'type': 'T_indexed',
     'regex': r'Temperature (?P<loc>.*) (?P<idx>\d+)',
     'name_pattern': 'Temp_{sloc}_{idx}',
     'feed_group': _DATA,
     'cmd_target': '_',
     },

    {'type': 'T_average',
     'regex': r'Temperature Average (?P<loc>.*)',
     'name_pattern': 'Temp_{sloc}_avg',
     'feed_group': _DATA,
     'cmd_target': '_',
     },

    {'type': 'T_setpoint',
     'regex': r'Setpoint Temperature (?P<loc>.*)',
     'name_pattern': 'Temp_{sloc}_setpoint',
     'feed_group': _CTRL,
     'cmd_target': 'Temperature {loc}',
     },

    {'type': 'fan_on',
     'regex': r'Fan (?P<loc>.*) on',
     'name_pattern': 'Fan_{sloc}_on',
     'feed_group': _CTRL,
     'cmd_target': 'Fan {loc}',
     },

    {'type': 'fan_fault',
     'regex': r'Fan (?P<loc>.*) Failure',
     'name_pattern': 'Fan_{sloc}_fault',
     'feed_group': _FAULTS,
     'cmd_target': '_',
     },

    {'type': 'fan_setpoint',
     'regex': r'Setpoint Speed Fan (?P<loc>.*)',
     'name_pattern': 'Fan_{sloc}_setpoint',
     'feed_group': _CTRL,
     'cmd_target': 'Fan {loc}',
     },

    {'type': 'booster_on',
     'regex': r'Booster (?P<loc>.*) on',
     'name_pattern': 'Booster_{sloc}_on',
     'feed_group': _CTRL,
     'cmd_target': 'Booster {loc}',
     },

    {'type': 'booster_fault',
     'regex': r'Booster (?P<loc>.*) Failure',
     'name_pattern': 'Booster_{sloc}_fault',
     'feed_group': _FAULTS,
     'cmd_target': '_',
     },

    {'type': 'heater_on',
     'regex': r'Heater on',
     'name_pattern': 'Heater_on',
     'feed_group': _CTRL,
     'cmd_target': 'Heater',
     },

    {'type': 'unclassified',
     'regex': r'.+',
     'name_pattern': '{sname}',
     'cmd_target': '_',
     },
]


@dataclass
class HvacItem:
    """Describes the type, name, shortened name, and feed details for
    a single entry in DataSets.HVAC.

    """
    type: str
    name: str
    acu_name: str
    feed_group: str
    data: str
    cmd_base: str


class HvacManager:
    """Interface class for collecting info about HVAC status fields
    from ACU.

    For now this assists with analyzing the HVAC dataset to classify
    the fields and assign them to the appropriate feed group.  Those
    are achieved by instantiating an instance (with no args) and then
    calling ``parse_fields`` followed by ``get_block_info``.

    In the future it may also help with generating control commands.

    """

    #: dict from field type to list of HvacItem.
    grouped_fields = None

    #: dict from ACU field name to the HvacItem.
    field_map = None

    def __init__(self, dataset_ident='Datasets.HVAC'):
        self._dataset_ident = dataset_ident

    def parse_fields(self, data):
        """Given the output from DataSets.HVAC, analyzes the fields
        therein and populates self.grouped_fields and self.field_map.
        This should be called on first valid data retrieval -- it will
        fail if self.grouped_fields has been populated already.

        """
        assert self.grouped_fields is None

        fields = {r['type']: [] for r in HVAC_SCHEMA}
        field_map = {}
        for f in data.keys():
            for sch in HVAC_SCHEMA:
                if m := re.match(sch['regex'], f):
                    data = m.groupdict()
                    if 'loc' in data:
                        data['sloc'] = data['loc'].replace(' ', '')
                    data['sname'] = f.replace(' ', '')
                    name = sch['name_pattern'].format(**data)
                    cmd_base = sch['cmd_target'].format(**data)
                    hv = HvacItem(type=sch['type'],
                                  name=name,
                                  acu_name=f,
                                  feed_group=sch.get('feed_group'),
                                  cmd_base=cmd_base,
                                  data=data)
                    fields[sch['type']].append(hv)
                    field_map[f] = hv
                    break
        self.grouped_fields = fields
        self.field_map = field_map

    def get_block_info(self):
        """Provides block info for monitor() process.  To be called
        after parse_fields.  Returns a map from acu_key to
        (feed_group, block_name, block_key).

        """
        output = {}
        for fields in self.grouped_fields.values():
            for f in fields:
                if f.feed_group:
                    output[f.acu_name] = (f.feed_group, 'ACU_' + f.feed_group, f.name)
        return output

    def get_command(self, name, value):
        """Turn a target and value into ACU command parameters.

        Args:
          name: The target name (e.g. 'Booster Yoke Traverse A Electronic Space')
          value: The value to send. This must be either "on", "off" or
            be castable to a float.  The on/off values may be applied
            to fans, boosters, or heaters.  The float value will be
            applied as a fan speed setpoint or a temperature setpoint.

        Returns:
          dict: If the (name, value) pair was successfully parsed, the
            returned dictionary contains kwargs that may be passed
            directly to AcuControl.Command. On failure, the dict
            contains only key 'error' with value a helpful message.

        """

        cmd = {'identifier': self._dataset_ident,
               'command': None,
               'parameter': None}

        if value in ['on', 'off']:
            try:
                self.field_map[name + ' on']
            except KeyError:
                return {'error': f'Target "{name}" not eligible for switch on/off.'}
            return cmd | {'command': f'Switch {value} {name}'}

        try:
            value = float(value)
        except ValueError:
            return {'error': f'Expected value to be float or on/off: {value}'}

        for set_prop in ['Speed', 'Temperature']:
            try:
                self.field_map[f'Setpoint {set_prop} {name}']
            except KeyError:
                continue
            return cmd | {'command': f'Set {set_prop} {name}',
                          'parameter': value}

        return {'error': f'Target "{name}" not eligible for setpoint update.'}
