class Motor:
    """
    The Motor object holds parameters for a given actuator

    Args:
    name (str): motor name (default "Unnamed Motor")
    """
    def __init__(self, name = 'Unnamed Motor'):
        self.name = name

        self.is_home = False  # is homed
        self.is_in_pos = False  # is in position
        self.is_pushing = False  # is pushing
        self.is_brake = False  # brake engaged
        self.pos = 0.  # position
        self.max_pos_err = 0.  # maximum possible position error

        self.max_pos = 20.  # mm
        self.min_pos = -2.  # mm
        self.home_pos = 0.  # mm
