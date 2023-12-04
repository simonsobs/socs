import socket
import struct
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock


class starcam_Helper:

    """
    CLASS to control and retrieve data from the starcamera

    Args:
        ip_address: IP address of the starcamera computer
        user_port: port of the starcamera

    Atributes:
        unpack_data receives the astrometry data from starcamera system and unpacks it
        close closes the socket
    """

    def __init__(self, ip_address, user_port, timeout=10):
        self.ip = ip_address
        self.port = user_port
        self.server_addr = (self.ip, self.port)
        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect(self.server_addr)
        self.comm.settimeout(timeout)

    def pack_cmds(self):
        """pack commands and parameters to be sent to star camera"""
        logodds = 1e8
        latitude = 51.6262
        longitude = 6.4650
        height = 21.0
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
        self.cmds_for_camera = struct.pack('ddddddfiiiiiiiiiifffffffff', logodds, latitude, longitude, height, exposure, timelimit, set_focus_to_amount, auto_focus_bool, start_focus, end_focus, step_size, photos_per_focus, infinity_focus_bool, set_aperture_steps, max_aperture_bool, make_HP_bool, use_HP_bool, spike_limit_value, dynamic_hot_pixels_bool, r_smooth_value, high_pass_filter_bool, r_high_pass_filter_value, centroid_search_border_value, filter_return_image_bool, n_sigma_value, star_spacing_value)

    def send_cmds(self):
        self.comm.sendto(self.cmds_for_camera, (self.ip, self.port))
        print("Commands sent to camera")

    def get_astrom_data(self):
        """Receive data from camera and unpack it"""
        (starcamdata_raw, _) = self.comm.recvfrom(224)
        starcamdata_unpacked = struct.unpack_from("dddddddddddddiiiiiiiiddiiiiiiiiiiiiiifiii", starcamdata_raw)
        c_time = starcamdata_unpacked[0]
        gmt = starcamdata_unpacked[1]
        blob_num = starcamdata_unpacked[2]
        obs_ra = starcamdata_unpacked[3]
        astrom_ra = starcamdata_unpacked[4]
        obs_dec = starcamdata_unpacked[5]
        astrom_dec = starcamdata_unpacked[6]
        fr = starcamdata_unpacked[7]
        ps = starcamdata_unpacked[8]
        alt = starcamdata_unpacked[9]
        az = starcamdata_unpacked[10]
        ir = starcamdata_unpacked[11]
        astrom_solve_time = starcamdata_unpacked[12]
        camera_time = starcamdata_unpacked[13]
        return c_time, gmt, blob_num, obs_ra, astrom_ra, obs_dec, astrom_dec, fr, ps, alt, az, ir, astrom_solve_time, camera_time

    def close(self):
        """Close the socket of the connection"""
        self.comm.close()


class starcam_Agent:

    def __init__(self, agent, ip_address, user_port):
        self.agent = agent
        self.active = True
        self.log = agent.log
        self.job = None
        self.take_data = False
        self.lock = TimeoutLock()
        agg_params = {'frame_length': 60}
        self.agent.register_feed("starcamera", record=True, agg_params=agg_params, buffer_time=1)
        try:
            self.starcam_Helper = starcam_Helper(ip_address, user_port)
        except socket.timeout:
            self.log.error("Starcamaera connection has times out")
            return False, "Timeout"

    def send_commands(self, session, params=None):
        """
        send_commands()
        **Task**
        Parameretes:
            standard_cmds (boolean): whether or not to send standard commands to star camera
        """
        with self.lock.acquire_timeout(job='send_commands') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "f"{self._lock.job} is already running")
                return False, "Could not acquire lock"
            self.log.info("Sending commands")
            self.starcam_Helper.pack_cmds()
            self.starcam_Helper.send_cmds()
        return True, "Sent commands to starcamera"

    @ocs_agent.param('_')
    def acq(self, session, params=None):
        """start_acq(test_mode=False)
        **Process** - Acquire data from starcam and write to feed.

        Parameters:
            test_mode (bool, optional): Run the acq process loop only once. This is meant only for testing. Default is false.
        """
        if params is None:
            params = {}
        with self.lock.acquire_timeout(timeout=100, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock"
            session.set_status('running')
            self.log.info("Starting acquisition")
            self.take_data = True
            while self.take_data:
                data = {
                    'timestamp': time.time(),
                    'block_name': 'astrometry',
                    'data': {}
                }
                c_time_reading, gmt_reading, blob_num_reading, obs_ra_reading, astrom_ra_reading, obs_dec_reading, astrom_dec_reading, fr_reading, ps_reading, alt_reading, az_reading, ir_reading, astrom_solve_time_reading, camera_time_reading = self.starcam_Helper.get_astrom_data()
                data['data']['c_time'] = c_time_reading
                data['data']['gmt'] = gmt_reading
                data['data']['blob_num'] = blob_num_reading
                data['data']['obs_ra'] = obs_ra_reading
                data['data']['astrom_ra'] = astrom_ra_reading
                data['data']['obs_dec'] = obs_dec_reading
                data['data']['astrom_dec'] = astrom_dec_reading
                data['data']['fr'] = fr_reading
                data['data']['ps'] = ps_reading
                data['data']['alt'] = alt_reading
                data['data']['az'] = az_reading
                data['data']['ir'] = ir_reading
                data['data']['astrom_solve_time'] = astrom_solve_time_reading
                data['data']['camera_time'] = camera_time_reading
                session.data.update(data['data'])
                self.agent.publish_to_feed('starcamera', data)
        return True, 'Acquisition exited cleanly'

    def _stop_acq(self, session, params):
        ok = False
        if self.take_data:
            session.set_status('stopping')
            self.take_data = False
            ok = True
            # self.starcam_Helper.close()
        return (ok, {True: 'Requested process to stop', False: 'Failed to request process stop.'}[ok])


def add_agent_args(parser_in=None):
    if parser_in is None:
        from argparse import ArgumentParser as A
        parser_in = A()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--ip-address", default="192.168.1.181", type=str, help="IP address of starcam computer")
    pgroup.add_argument("--user-port", default="8000", type=int, help="Port of starcam computer")
    return parser_in


def main(args=None):
    parser = add_agent_args()
    args = site_config.parse_args(agent_class="starcam_Agent", parser=parser)
    startup = True
    agent, runner = ocs_agent.init_site_agent(args)
    starcam_agent = starcam_Agent(agent, ip_address=args.ip_address, user_port=args.user_port)
    agent.register_task('send_commands', starcam_agent.send_commands, startup=True)
    agent.register_process('acq', starcam_agent.acq, starcam_agent._stop_acq)
    runner.run(agent, auto_reconnect=False)


if __name__ == '__main__':
    main()
