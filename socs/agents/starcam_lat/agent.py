import argparse
import socket
import struct
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock


class StarcamHelper:

    """
    CLASS to control and retrieve data from the starcamera

    Args:
        ip_address: IP address of the starcamera computer
        port: port of the starcamera
    """

    def __init__(self, ip_address, port, timeout=10):
        self.ip = ip_address
        self.port = port
        self.server_addr = (self.ip, self.port)
        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect(self.server_addr)
        self.comm.settimeout(timeout)

    def pack_and_send_cmds(self):
        """
        pack_and_send_cmds()

        **Process**
<<<<<<< HEAD
        packs commands and parameters to be sent to starcamera and sends
        
=======
        packs commands and parameters to be sent to star camera and sends

>>>>>>> 82252e753327de73c687591486c64dca8f4a8638
        **Return**
        returns list of values sent
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
        self.cmds_for_camera = struct.pack('ddddddfiiiiiiiiiifffffffff', 
                                           *values)
        # send commands to the camera
        self.comm.sendto(self.cmds_for_camera, (self.ip, self.port))
        print(“Commands sent to camera”)
        # Return the list of values
        return values

    def get_astrom_data(self):
        """
        get_astrom_data()

        **Process**
        receives and unpacks data from camera

        **Return**
        returns dictionary of unpacked data
        """
        (scdata_raw, _) = self.comm.recvfrom(224)
        data = struct.unpack_from("dddddddddddddiiiiiiiiddiiiiiiiiiiiiiifiii",
                                  scdata_raw)
        sc_keys = ['c_time',
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
        astr_data = [data[i] for i in range(len(sc_keys))]
        astr_data_dict = {keys[i]: astr_data[i] for i in range(len(sc_keys))}
        return astr_data_dict

    def close(self):
        """
        close()

        **Process**
        closes the socket of the connection
        """
        self.comm.close()


class StarcamAgent:

    def __init__(self, agent, ip_address, port):
        self.agent = agent
        self.active = True
        self.log = agent.log
        self.job = None
        self.take_data = False
        self.lock = TimeoutLock()
        agg_params = {'frame_length': 60}
        self.agent.register_feed("starcamera", record=True, 
                                 agg_params=agg_params, buffer_time=1)
        try:
            self.StarcamHelper = StarcamHelper(ip_address, port)
        except socket.timeout:
            self.log.error("Starcamera connection has times out")
            return False, "Timeout"

    @ocs_agent.param('_')
    def send_commands(self, session, params=None):
        """
        send_commands()

        **Process**
        packs and sends camera+astrometry-related commands to starcam

        **Return**
        returns a touple with True/False and a string describing whether
        or not a lock could be acquired and commands were sent to the sc
        """
        with self.lock.acquire_timeout(job='send_commands') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"
            self.log.info("Sending commands")
            self.StarcamHelper.pack_and_send_cmds()
        return True, "Sent commands to starcamera"

    @ocs_agent.param('_')
    def acq(self, session, params=None):
        """
        acq()

        **Process**
        acquires data from starcam and publishes to feed

        **Return**
<<<<<<< HEAD
        once the acq() loop exits (wherein data is retrieved from 
        the camera and pulished), a touple with True/False and a string 
        describing whether or not the loop was exited after the end of 
        an acquisition.
=======
        once the acq() loop exits (wherein data is retrieved from the camera and pulished),
        a touple with True/False and a string describing whether or not the loop was exited
        after the end of an acquisition.
>>>>>>> 82252e753327de73c687591486c64dca8f4a8638
        """
        if params is None:
            params = {}
        with self.lock.acquire_timeout(timeout=100, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start init because {} is already 
                              running".format(self.lock.job))
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
                # get astrometry data
                astrom_data = self.StarcamHelper.get_astrom_data()
<<<<<<< HEAD
                # update the data dictionary+session and publish
                data['data'].update(astrom_data_dict) 
=======
                # update the data dictionary, update the session, and publish
                data['data'].update(astrom_data_dict)
>>>>>>> 82252e753327de73c687591486c64dca8f4a8638
                session.data.update(data['data'])
                self.agent.publish_to_feed('starcamera', data)

        return True, 'Acquisition exited cleanly'

    def _stop_acq(self, session, params):
        ok = False
        if self.take_data:
            session.set_status('stopping')
            self.take_data = False
            ok = True
            # self.StarcamHelper.close()
        return (ok, {True: 'Requested process to stop', 
                     False: 'Failed to request process stop.'}[ok])


def add_agent_args(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument("--ip-address", type=str, 
                        help="IP address of starcam computer")
    pgroup.add_argument("--port", default="8000", type=int, 
                        help="Port of starcam computer")
    return parser


def main(args=None):
    # for logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class="StarcamAgent", parser=parser)
    agent, runner = ocs_agent.init_site_agent(args)
    starcam_agent = StarcamAgent(agent, ip_address=args.ip_address, 
                                 port=args.port)
    agent.register_task('send_commands', starcam_agent.send_commands, 
                        startup=True)
    agent.register_process('acq', starcam_agent.acq, starcam_agent._stop_acq)
    runner.run(agent, auto_reconnect=False)


if __name__ == '__main__':
    main()
