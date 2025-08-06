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
    {'group': 'ignore',
     'regex': r'Time|Year',
     'name_pattern': '{sname}',
     },

    {'group': 'T_indexed',
     'regex': r'Temperature (?P<loc>.*) (?P<idx>\d+)',
     'name_pattern': 'Temp_{sloc}_{idx}',
     'feed_group': _DATA,
     },

    {'group': 'T_average',
     'regex': r'Temperature Average (?P<loc>.*)',
     'name_pattern': 'Temp_{sloc}_avg',
     'feed_group': _DATA,
     },

    {'group': 'T_setpoint',
     'regex': r'Setpoint Temperature (?P<loc>.*)',
     'name_pattern': 'Temp_{sloc}_setpoint',
     'feed_group': _CTRL,
     },

    {'group': 'fan_on',
     'regex': r'Fan (?P<loc>.*) on',
     'name_pattern': 'Fan_{sloc}_on',
     'feed_group': _CTRL,
     },

    {'group': 'fan_fault',
     'regex': r'Fan (?P<loc>.*) Failure',
     'name_pattern': 'Fan_{sloc}_fault',
     'feed_group': _FAULTS,
     },

    {'group': 'fan_setpoint',
     'regex': r'Setpoint Speed Fan (?P<loc>.*)',
     'name_pattern': 'Fan_{sloc}_setpoint',
     'feed_group': _CTRL,
     },

    {'group': 'booster_on',
     'regex': r'Booster (?P<loc>.*) on',
     'name_pattern': 'Booster_{sloc}_on',
     'feed_group': _CTRL,
     },

    {'group': 'booster_fault',
     'regex': r'Booster (?P<loc>.*) Failure',
     'name_pattern': 'Booster_{sloc}_fault',
     'feed_group': _FAULTS,
     },

    {'group': 'heater_on',
     'regex': r'Heater on',
     'name_pattern': 'Heater_on',
     'feed_group': _CTRL,
     },

    {'group': 'unclassified',
     'regex': r'.+',
     'name_pattern': '{sname}',
     },
]


@dataclass
class HvacItem:
    """Describes the type, name, shortened name, and feed details for
    a single entry in DataSets.HVAC."""
    ftype: str
    name: str
    acu_name: str
    feed_group: str
    data: str


class HvacManager:
    groups = None
    field_map = None

    def parse_fields(self, data):
        """Given the output from DataSets.HVAC, analyzes the fields
        therein and populates self.groups and self.field_map.  This
        should be called on first valid data retrieval -- it will fail
        if self.groups has been popualted already.

        """
        assert self.groups is None

        fields = {r['group']: [] for r in HVAC_SCHEMA}
        field_map = {}
        for f in data.keys():
            for sch in HVAC_SCHEMA:
                if m := re.match(sch['regex'], f):
                    data = m.groupdict()
                    if 'loc' in data:
                        data['sloc'] = data['loc'].replace(' ', '')
                    data['sname'] = f.replace(' ', '')
                    name = sch['name_pattern'].format(**data)
                    hv = HvacItem(ftype=sch['group'],
                                  name=name,
                                  acu_name=f,
                                  feed_group=sch.get('feed_group'),
                                  data=data)
                    fields[sch['group']].append(hv)
                    field_map[f] = hv
                    break
        self.groups = fields
        self.field_map = field_map

    def get_block_info(self):
        """Provides block info for monitor() process.  To be called
        after parse_fields.  Returns a map from acu_key to (group,
        block_name, block_key).

        """
        output = {}
        for group, fields in self.groups.items():
            for f in fields:
                if f.feed_group:
                    output[f.acu_name] = (f.feed_group, 'ACU_' + f.feed_group, f.name)
        return output
