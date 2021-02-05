changed ip to port in __init__ call

changed self.module.channels[params['channel']] to self.module.chan_num2Channel(params['channel'])
>will always work for arbitrary ordering of channels, self.module.channels[] may fail if not in order

changed self.module.get_active_channel().units to self.module.sample_heater.units

changed self.module.get_active_channel().set_units('kelvin') to self.module.sample_heater.set_units('kelvin')

changed parser arg --ip-address to --port

throughout, changed references from LS372 to LS370, ip address to port etc.

removed OTD block at beginning of agent
