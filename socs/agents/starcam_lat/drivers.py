import struct

from socs.tcp import TCPInterface


class StarcamHelper(TCPInterface):
    """Functions to control and retrieve data from the starcam.

    Parameters
    ----------
    ip_addres: str
        IP address of the starcam computer.
    port: int
        Port of the starcam computer.
    timeout: float
        Socket connection timeout in seconds. Defaults to 10 seconds.

    """

    def __init__(self, ip_address, port, timeout=10):
        # Set up the TCP Interface
        super().__init__(ip_address, port, timeout)

    def send_cmds(self):
        """Send commands and parameters to the starcam."""
        cmds = self._pack_cmds()
        self.comm.send(cmds)

    @staticmethod
    def _pack_cmds():
        """Packs commands and parameters to be sent to the starcam.

        Returns:
            bytes: Packed bytes object to send to the starcam.

        """
        logodds = 1e8
        latitude = -22.9586
        longitude = -67.7875
        height = 5200.0
        exposure = 700
        timelimit = 1
        set_focus_to_amount = 0
        auto_focus_bool = 1
        start_focus = 0
        end_focus = 0
        step_size = 5
        photos_per_focus = 3
        infinity_focus_bool = 0
        set_aperture_steps = 0
        max_aperture_bool = 0
        make_HP_bool = 0
        use_HP_bool = 0
        spike_limit_value = 3
        dynamic_hot_pixels_bool = 1
        r_smooth_value = 2
        high_pass_filter_bool = 0
        r_high_pass_filter_value = 10
        centroid_search_border_value = 1
        filter_return_image_bool = 0
        n_sigma_value = 2
        star_spacing_value = 15
        values = [logodds,
                  latitude,
                  longitude,
                  height,
                  exposure,
                  timelimit,
                  set_focus_to_amount,
                  auto_focus_bool,
                  start_focus,
                  end_focus,
                  step_size,
                  photos_per_focus,
                  infinity_focus_bool,
                  set_aperture_steps,
                  max_aperture_bool,
                  make_HP_bool,
                  use_HP_bool,
                  spike_limit_value,
                  dynamic_hot_pixels_bool,
                  r_smooth_value,
                  high_pass_filter_bool,
                  r_high_pass_filter_value,
                  centroid_search_border_value,
                  filter_return_image_bool,
                  n_sigma_value,
                  star_spacing_value]

        # Pack values into the command for the camera
        return struct.pack('ddddddfiiiiiiiiiifffffffff', *values)

    def get_astrom_data(self):
        """Receives and unpacks data from the starcam.

        Returns:
            dict: Dictionary of unpacked data.
        """
        scdata_raw = self.comm.recv(256)
        return self._unpack_response(scdata_raw)

    @staticmethod
    def _unpack_response(response):
        data = struct.unpack_from("dddddddddddddiiiiiiiiddiiiiiiiiiiiiiifiii",
                                  response)
        keys = ['c_time',
                'gmt',
                'blob_num',
                'obs_ra',
                'astrom_ra',
                'obs_dec',
                'fr',
                'ps',
                'alt',
                'az',
                'ir',
                'astrom_solve_time',
                'camera_time']

        # Create a dictionary of the unpacked data
        astrom_data = [data[i] for i in range(len(keys))]
        astrom_data_dict = {keys[i]: astrom_data[i] for i in range(len(keys))}
        return astrom_data_dict
