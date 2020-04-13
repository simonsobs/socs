socket functionality replaced with serial, 370 does not support ethernet communication

channel A functionality removed, no channel A in 370 

get_temp now uses Channel methods get_kelvin_reading and get_resistance_reading, units functionality removed

###

get/set_sensor_input_name commented out, INNAME? not in 370 firmware API
>channel.name set to f'Channel {channel_num}' 

get/set_input_setup implemented with RDGRNG, INTYPE not in 370 firmware API. Note no units parameter, and order of range/autorange is flipped w.r.t. 372. RDGRNG can return 'out of range' values -- values not possible according to firmware API, e.g. range = 50, see page 6-33. Methods get/set_units commented out
>resetting RDGRNG values seemed to place LS370 in valid state, no longer returning 'out of range' values
>some RDGRNG values did vary from commanded values after command sent, however, even though cs on (excitation off), autorange off, scanning off. This can lead to mismatch between instance variables of python objects representing machine state and actual machine state.
>Channel.enable/disable_excitation observed to enable excitation on all channels, not just one, even though ls.msg('CHGALL?') returns 0 (range and excitation keys change one channel individually). I believe this may be a feature of device functionality: there is only one current source. This can lead to mismatch between instance variables of python objects representing machine state and actual machine state. Possible that other per channel commands also affect other channels.
>>after reading the manual, it doesn't seem to be functionality, but rather is a bug
>Channel.enable/disable_autorange observed to enable autorange on all channels, not just one. I believe this may be a feature of device functionality: there is only one range-finding mechanism, which is scanned across channels. This can lead to mismatches between instance variables of python objects representing machine state and actual machine state. Possible that other per channel commands also affect other channels.
>>after reading the manual, it doesn't seem to be functionality, but rather is a bug

get/set_units commented out, INTYPE not in 370 firmware API. units not returned with RDGRNG

get/set_temperature_limit commented out, TLIMIT not in 370 firmware API

get_sensor_reading commented out, SRDG not in firmware API

it looks like every call to RDGRNG results in a stored range value off by a constant amount (over range value in command string) depending on channel in a random way, and excitation value in a deterministic way (delta r + excitation value = constant), wtf. eg, channel 11 Range is always 9 digits above nominal if excitation value = 3, but if excitation value is 1, channel 11 Range is always 11 digits above nominal. The DC level offset is per channel, many are -2, -1, 0, 1, 2, or 9...
>changing baudrate from 9600 to 300 did not fix.
>sending negative params in RDGRNG did not produce simple response (eg, doesn't just add 9, sets to some other default value).
>could add offset parameters to Channel object to try to track this for _set_input_setup. also add get_XYZ function call to end of every set_XYZ function call to update instance variables of Channel object toactual machine state.
>with above, some resitance range values will be unobtainable without autorange finding them. Autogrange did find channel 2 at 1kohm from a range setting of 6.32Mohm, so it's reasonably good.

###

curve format key/lock does not support value 7, cubic spline. removed from key/lock

removed quotes around {_name}, {_sn} arguments in _set_header

removed curvature functionality from get/set_data_point - for cubic spline (372 only)

_check_curve checks for data up to breakpoint_idx = len(values) instead of 200, and zeropoint data afterward up to 200 (handles curves that are nominally empty after <200 breakpoints)

_check_curve handles assertion error for mismatched temperature at breakpoint (in addition to units)

###

CMODE (370) changes control loop mode

CPOL (370) changes heater polarity

CSET (370) to set up control loop, including units - see, e.g., SETP
>above three commands together essentially replace HTRSET, OUTMODE in 372. 372 commands usually apply toany output; 370 commands apply only to actual control output (not analog)

HTRRNG (370) ~ RANGE (372)

A lot of 372 functionality treats all 3 outputs equally, whereas 370 functionality favors control output. In implementing 372 API as closely as possible, 370 methods require different msg calls depending on output type > will need to build new Analog class. Also, many parameters do not carry over, eg, Heater.powerup, and have been commented out.

self.powerup commented out
self.max_current commented out, replaced with rng_limit
self.max_user_current commented out
get/set_output_mode replaces powerup with units, and rearranges order of params according to 370 firmware
>output_modes dict modified to match firmware API
get/set_heater_setup replaces max_current and max_user current with rng_limit, and rearranges order of params according to 370 firmware 

added get/set_units
