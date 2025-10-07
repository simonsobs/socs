from socs.tcp import TCPInterface

class GalilStageController(TCPInterface):
    def __init__(self, ip, port=23, timeout=10, configfile=None):
    """Interface class for Galil stage controller."""
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.configfile = configfile

        # setup TCP interface
        super().__init__(ip, port, timeout)


    def query(self, expr):
        """Send an MG (message) query to the Galil and return the ASCII reply."""
        # MG means “message” — returns the evaluated expression
        response = self.send(f"MG {expr}\r")
        if isinstance(response, bytes):
            response = response.decode("ascii", errors="ignore")
        return response.strip(": \r\n")


    def get_data(self):
        """Query positions, velocities, and torques for each axis."""
        axes = ["A", "B", "C", "D"]
        data = {}

        for axis in axes:
            try:
                pos = float(self.query(f"_TP{axis}"))
                vel = float(self.query(f"_TV{axis}"))
                tor = float(self.query(f"_TT{axis}"))
            except ValueError:
                pos = vel = tor = float("nan")

            data[axis] = {
                "position": pos,
                "velocity": vel,
                "torque": tor
            }

        return data

