

class DigitalIO:
    """
    The digital IO class to read & control the digital IOs
    via the Galil actuator controller.

    Args:
        name(string)            : Name of this instance
        io_list(list)           : IO configurations
        g(gclib.py())           : Actuator controller library
        get_onoff_reverse(bool) : Return 1/0 in _get_onoff()
                                  if IO input is 0/1
        set_onoff_reverse(bool) : Send SB(1)/CB(0) to the controller
                                  in _set_onoff()
                                  if "onoff" argument is False/True
        verbose(int)    : Verbosity level
    """

    def __init__(self, name, io_list, g,
                 get_onoff_reverse=False, set_onoff_reverse=False, verbose=0):
        self.name = name
        self.g = g
        self.get_reverse = get_onoff_reverse
        self.set_reverse = set_onoff_reverse
        self.verbose = verbose

        self.io_list = io_list
        self.io_names = [io['name'] for io in io_list]
        self.io_labels = [io['label'] for io in io_list]
        self.io_indices = {io['name']: index
                           for index, io in enumerate(io_list)}
        self.io_dict = {io['name']: io['io'] for io in io_list}
        # Retrieve IO number: io OUT[3] --> 3
        self.io_numdict = \
            {name: (int)(io.split('[')[1].split(']')[0])
                for name, io in self.io_dict.items()}

    def _get_onoff(self, io_name):
        onoff = self.g.GCommand('MG @{}'.format(self.io_dict[io_name]))
        try:
            onoff = bool(float(onoff.strip()))
        except ValueError as e:
            msg = \
                'DigitalIO[{}]:_get_onoff(): ERROR!: '\
                'Failed to get correct on/off message '\
                'from the controller.\n'.format(self.name)\
                + 'DigitalIO[{}]:_get_onoff(): '\
                  ' message = "{}" | Exception = "{}"'\
                  .format(self.name, onoff, e)
            raise ValueError(msg)
        if self.get_reverse:
            onoff = not onoff
        # print('DigitalIO[{}]:_get_onoff(): onoff for {}: {}'
        #      .format(self.name, io_name, onoff))
        return int(onoff)

    def get_onoff(self, io_name=None):
        """Get True/False (ON/OFF) for the digital IOs.

        Args:
            io_name (str or list): A string of a IO name or list of IO names.

        Returns:
            list or str: A list of True/Falses or a single True/False depending
            on the value of `io_name`. If `io_name` is None, return a list of
            the ON/OFFs for all the IOs. If `io_name` is a list, return a list
            of the ON/OFFs for asked IOs.  If `io_name` is a string (one IO),
            return one ON/OFF. Here True means ON and False means OFF.
        """
        if io_name is None:
            onoff = [self._get_onoff(name) for name in self.io_names]
        elif isinstance(io_name, list):
            if not all([(name in self.io_names) for name in io_name]):
                msg = \
                    'DigitalIO[{}]:get_onoff(): ERROR!: '\
                    .format(self.name) \
                    + 'There is no matched IO name.\n'\
                      'DigitalIO[{}]:get_onoff():       '\
                      .format(self.name)\
                    + 'Assigned IO names = {}\n'\
                      .format(self.io_names)\
                    + 'DigitalIO[{}]:get_onoff():       '\
                      'Asked IO names = {}'.format(self.name, io_name)
                raise ValueError(msg)
            onoff = [self._get_onoff(name) for name in io_name]
        else:
            if not (io_name in self.io_names):
                msg = \
                    'DigitalIO[{}]:get_onoff(): ERROR!: '\
                    'There is no IO name of {}.\n'\
                    .format(self.name, io_name) \
                    + 'DigitalIO[{}]:get_onoff():         '\
                      'Assigned IO names = {}'.format(self.name, self.io_names)
                raise ValueError(msg)
            onoff = self._get_onoff(io_name)
        return onoff

    def get_label(self, io_name):
        if io_name is None:
            label = self.io_labels
        elif isinstance(io_name, list):
            if not all([(name in self.io_names) for name in io_name]):
                msg = \
                    'DigitalIO[{}]:get_label(): ERROR!: '\
                    'There is no matched IO name.\n'\
                    .format(self.name)\
                    + 'DigitalIO[{}]:get_label():     '\
                      'Assigned IO names = {}\n'\
                      .format(self.name, self.io_names)\
                    + 'DigitalIO[{}]:get_label():     '\
                      'Asked IO names    = {}'.format(self.name, io_name)
                raise ValueError(msg)
            label = [self.io_indices[name] for name in io_name]
        else:
            if not (io_name in self.io_names):
                msg = \
                    'DigitalIO[{}]:get_label(): ERROR!: '\
                    'There is no IO name of {}.\n'\
                    .format(self.name, io_name) \
                    + 'DigitalIO[{}]:get_label():     '\
                      'Assigned IO names = {}'.format(self.name, self.io_names)
                raise ValueError(msg)
            label = self.io_label(io_name)
        return label

    def _set_onoff(self, onoff, io_name):
        io_num = self.io_numdict[io_name]
        onoff = bool(int(onoff))
        if self.set_reverse:
            onoff = not onoff
        if onoff:
            cmd = 'SB {}'.format(io_num)
        else:
            cmd = 'CB {}'.format(io_num)
        self.g.GCommand(cmd)

    def set_onoff(self, onoff=0, io_name=None):
        """Set True/False (ON/OFF) for the digital IOs.

        Args:
            onoff (int): 0 (OFF) or 1 (ON)
            io_name (str or list): a string of a IO name or list of IO names.
                If None, set all possible IOs ON/OFF. If a list, set all
                specified IOs ON/OFF. If a string (one IO), set the given IO
                ON/OFF.
        """
        set_io_names = []
        if io_name is None:
            set_io_names = self.io_names
        elif isinstance(io_name, list):
            if not all([(name in self.io_names) for name in io_name]):
                msg = \
                    'DigitalIO[{}]:set_onoff(): ERROR!: '\
                    'There is no matched IO name.\n'\
                    .format(self.name)\
                    + 'DigitalIO[{}]:set_onoff():    '\
                      'Assigned IO names = {}\n'\
                      .format(self.name, self.io_names)\
                    + 'DigitalIO[{}]:set_onoff():     '\
                      'Asked IO names    = {}'\
                      .format(self.name, io_name)
                raise ValueError(msg)
            set_io_names = io_name
        else:
            if not (io_name in self.io_names):
                msg = \
                    'DigitalIO[{}]:set_onoff(): ERROR!: '\
                    'There is no IO name of {}.\n'\
                    .format(self.name, io_name)\
                    + 'DigitalIO[{}]:set_onoff():     '\
                      'Assigned IO names = {}'.format(self.name, self.io_names)
                raise ValueError(msg)
            set_io_names = [io_name]
        print('DigitalIO[{}]:set_onoff(): Set {} for the IOs: '
              '{}'.format(self.name, 'ON' if onoff else 'OFF', set_io_names))
        for name in set_io_names:
            self._set_onoff(onoff, name)

    def set_allon(self):
        print('DigitalIO[{}]:set_allon(): '
              'Set ON for all of the digital IOs'.format(self.name))
        self.set_onoff(1, None)

    def set_alloff(self):
        print('DigitalIO[{}]:set_allon(): '
              'Set OFF for all of the digital IOs'.format(self.name))
        self.set_onoff(0, None)
