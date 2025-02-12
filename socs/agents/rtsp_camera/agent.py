# Copyright (C) 2023-2024 Simons Observatory Collaboration
# See top-level LICENSE.txt file for more information.
"""Agent to capture images from cameras which support the RTSP protocol.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import cv2
import ocs
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

txaio.use_twisted()

from socs.common.camera import (CircularMediaBuffer, FakeCamera,
                                MotionDetector, image_read_callback,
                                image_write_callback, video_write_callback)


class RTSPCameraAgent:
    """Agent to support image capture from RTSP cameras.

    This Agent captures images and writes them to a feed, as well as saving frames
    to disk.  The camera can also be triggered to record....

    Args:
        agent (OCSAgent): OCSAgent object from :func:`ocs.ocs_agent.init_site_agent`.
        directory (str): The path to image storage for this camera.
        address (str): The hostname or IP address of the camera.
        user (str): The user name for camera access.
        password (str): The password for camera access.
        seconds (int): The seconds between snapshots.
        port (int): The RTSP port to use (default is standard 554).
        urlpath (str): The remaining URL for the camera, which might include
            options like channel and subtype.  This will depend on the manufacturer.
        jpeg_quality (int): The JPEG quality for snapshot images (0-100).
        max_snapshot_files (int): The maximum number of snapshots to keep.
        record_fps (float): The frames per second for recorded video.
        record_duration (int): The number of seconds for each recorded video.
        max_record_files (int): The maximum number of recordings to keep.
        motion_start (str): ISO time (HH:MM:SS+-zz:zz) to start motion detection.
        motion_stop (str): ISO time (HH:MM:SS+-zz:zz) to stop motion detection.
        disable_motion (bool): If True, disable motion detection.
        fake (bool): If True, ignore camera settings and generate fake video
            for testing.

    Attributes:
        agent (OCSAgent): OCSAgent object from :func:`ocs.ocs_agent.init_site_agent`.
        log (txaio.tx.Logger): Logger object used to log events within the
            Agent.
        lock (TimeoutLock): TimeoutLock object used to prevent simultaneous
            commands being sent to hardware.

    """

    def __init__(
        self,
        agent,
        directory,
        address,
        user,
        password,
        seconds=10,
        port=554,
        urlpath=None,
        jpeg_quality=20,
        max_snapshot_files=10000,
        record_fps=20.0,
        record_duration=60,
        max_record_files=100,
        motion_start=None,
        motion_stop=None,
        disable_motion=False,
        fake=False,
    ):
        self.agent = agent
        self.topdir = directory
        self.log = agent.log
        self.lock = TimeoutLock(default_timeout=5)

        self.address = address
        self.port = port
        self.user = user
        self.password = password
        self.seconds = seconds
        self.urlpath = urlpath
        self.fake = fake
        self.motion_start = motion_start
        self.motion_stop = motion_stop
        self.motion_detect = not disable_motion

        if self.urlpath is None:
            # Try the string for the Dahua cameras at the site
            self.urlpath = "/cam/realmonitor?channel=1&subtype=0"

        self.connection = f"rtsp://{self.user}:{self.password}"
        self.connection += f"@{self.address}:{self.port}{self.urlpath}"

        # We will store recordings and snapshots to separate subdirs
        if not os.path.isdir(self.topdir):
            os.makedirs(self.topdir)
        self.img_dir = os.path.join(self.topdir, "snapshots")
        self.vid_dir = os.path.join(self.topdir, "recordings")
        self.record_duration = record_duration
        self.record_fps = record_fps

        # Create the image buffer on disk
        self.img_buffer = CircularMediaBuffer(
            self.img_dir,
            "img",
            "jpg",
            max_snapshot_files,
            image_write_callback,
            read_callback=image_read_callback,
            recent=3,
            quality=jpeg_quality,
        )

        # Create the recording buffer on disk
        self.vid_buffer = CircularMediaBuffer(
            self.vid_dir,
            "vid",
            "mp4",
            max_record_files,
            video_write_callback,
            read_callback=None,
            recent=0,
            fps=record_fps,
        )

        # Register OCS feed
        self.feed_name = f"RTSP_{self.address}"

        agg_params = {"frame_length": self.seconds}  # [sec]
        self.agent.register_feed(
            self.feed_name,
            record=True,
            agg_params=agg_params,
            buffer_time=1.0,
        )

    def _in_motion_time_range(self):
        """Determine if we are in the valid time range for motion detection."""
        if self.motion_start is None or self.motion_stop is None:
            # We are not using the start / stop time range, so all times are valid
            return True

        # The current time in UTC
        curtime = datetime.now(tz=timezone.utc)

        # Convert the start / stop times to datetimes based on today
        curdaystr = f"{curtime.year}-{curtime.month:02d}-{curtime.day:02d}"

        # The datetimes for start/stop today
        def _dt_convert(timestr):
            tstr = f"{curdaystr}T{timestr}"
            try:
                tm = datetime.strptime(tstr, "%Y-%m-%dT%H:%M:%S%z")
            except ValueError:
                tm = datetime.strptime(tstr, "%Y-%m-%dT%H:%M:%S")
                msg = f"Motion time '{timestr}' is not "
                msg += "timezone-aware.  Assuming UTC."
                self.log.warning(msg)
                tm = tm.replace(tzinfo=timezone.utc)
            return tm
        start = _dt_convert(self.motion_start)
        stop = _dt_convert(self.motion_stop)

        if stop <= start:
            # We are starting today and stopping tomorrow
            stop += timedelta(days=1)

        if curtime > start and curtime < stop:
            return True
        else:
            return False

    def _init_stream(self):
        """Connect to camera and initialize video stream."""
        if self.fake:
            cap = FakeCamera()
        else:
            cap = cv2.VideoCapture(self.connection)
        if not cap.isOpened():
            self.log.error(f"Cannot open RTSP stream at {self.connection}")
            return None

        return cap

    @ocs_agent.param("test_mode", default=False, type=bool)
    def acq(self, session, params=None):
        """acq(test_mode=False)

        **Process** - Capture frames from an RTSP camera.

        Args:
            test_mode (bool):  Run the Process loop only once. Meant only
                for testing.  Default is False.

        Notes:
            Individual frames are written to a circular disk buffer.  Metadata
            about the captured images is stored in the session data.  The format
            of this is::

                >>> response.session['data']
                {
                    'address': 'camera-c1.example.org',
                    'timestamp': 1701983575.123456,
                    'path': '/ocs/cameras_rtsp/c1/img_2023-12-29T02:44:47+00:00.jpg',
                }

        """
        pm = Pacemaker(1 / self.seconds, quantize=False)
        pmgrab = Pacemaker(self.record_fps, quantize=True)

        frames_per_snapshot = int(self.seconds * self.record_fps)

        self.is_streaming = True

        # Open camera stream
        cap = self._init_stream()
        connected = True
        if not cap:
            connected = False

        # Tracking state of whether we are currently recording motion detection
        detecting = False
        detect_start = None
        record_frames = int(self.record_fps * self.record_duration)
        motion_detector = MotionDetector()

        snap_count = 0
        while self.is_streaming:
            if not connected:
                self.log.info("Trying to reconnect.")
                cap = self._init_stream()
                if not cap:
                    pm.sleep()
                    continue

            # Use UTC
            timestamp = time.time()
            data = dict()

            for iframe in range(frames_per_snapshot):
                pmgrab.sleep()
                # Grab an image
                _ = cap.grab()
            success, image = cap.retrieve()
            if not success:
                msg = "Failed to retrieve snapshot image from stream"
                self.log.error(msg)
                connected = False
                continue
            connected = True

            # Motion detection.  We ignore the first few snapshots and also
            # any changes that happen while we are already recording.
            if snap_count < 4:
                skip = True
            else:
                skip = False
            if detecting:
                if (snap_count - detect_start) * frames_per_snapshot > record_frames:
                    # We must have finished recording
                    detecting = False
                    skip = False
                else:
                    # We are still recording
                    skip = True
            if self.motion_detect and self._in_motion_time_range():
                image, movement = motion_detector.process(image, skip=skip)
                if movement:
                    # Start recording
                    detecting = True
                    detect_start = snap_count
                    rec_stat, rec_msg, _ = self.agent.start(
                        "record", params={"test_mode": False}
                    )
                    if rec_stat != ocs.OK:
                        self.log.error(f"Problem with motion capture: {rec_msg}")

            # Save to circular buffer
            self.img_buffer.store(image)

            # Get the saved path
            path = self.img_buffer.fetch_index(-1)[0]

            # Fill data
            data = {
                "address": self.address,
                "timestamp": timestamp,
                "path": path,
                "connected": connected
            }

            # Update session.data and publish
            session.data = data
            self.log.debug(f"{data}")

            message = {
                "block_name": "cameras",
                "timestamp": timestamp,
                "data": {
                    "address": self.address,
                    "path": path,
                    "connected": connected
                },
            }
            session.app.publish_to_feed(self.feed_name, message)

            if params["test_mode"]:
                break
            snap_count += 1
            pm.sleep()

        # Flush buffer and stop the data stream
        self.agent.feeds[self.feed_name].flush_buffer()

        # Release stream
        cap.release()
        return True, "Acquisition finished"

    def _stop_acq(self, session, params=None):
        """_stop_acq()
        **Task** - Stop task associated with acq process.
        """
        if self.is_streaming:
            self.is_streaming = False
            return True, "Stopping Acquisition"
        else:
            return False, "Acq is not currently running"

    def record(self, session, params=None):
        """Record video stream.

        **Task** - Record video for fixed timespan.

        Parameters:
            None

        """
        session.set_status("running")

        with self.lock.acquire_timeout(0, job="record") as acquired:
            if not acquired:
                self.log.warn(
                    "Could not start recording because "
                    "{} is already running".format(self.lock.job)
                )
                return False, "Only one simultaneous recording per camera allowed"

            pm = Pacemaker(self.record_fps, quantize=True)

            # Open camera stream
            self.log.info("Recording:  opening camera stream")
            cap = self._init_stream()
            if not cap:
                return False, "Cannot connect to camera."

            # Total number of frames
            total_frames = int(self.record_fps * self.record_duration)

            msg = f"Recording:  starting {total_frames} frames "
            msg += f"({self.record_duration}s at {self.record_fps}fps)"
            self.log.info(msg)

            frames = list()
            for iframe in range(total_frames):
                if session.status != "running":
                    return False, "Aborted recording"
                pm.sleep()
                # Grab an image
                success, image = cap.read()
                if not success:
                    msg = f"Recording:  broken stream at frame {iframe}, ending"
                    self.log.error(msg)
                    break
                frames.append(image)

            # Save to circular buffer
            self.vid_buffer.store(frames)

            # Get the saved path
            path = self.vid_buffer.fetch_index(-1)[0]
            self.log.info(f"Recording:  finished {path}")

            # Cleanup
            cap.release()

        return True, "Recording finished."

    def _abort_record(self, session, params):
        if session.status == "running":
            session.set_status("stopping")


def add_agent_args(parser=None):
    """Create or append agent arguments.

    Args:
        parser (ArgumentParser): Optional input parser to use.  If None,
            a new parser will be created.

    Returns:
        (ArgumentParser): The created or modified parser.

    """
    if parser is None:
        from argparse import ArgumentParser as A

        parser = A()
    pgroup = parser.add_argument_group("Agent Options")

    pgroup.add_argument(
        "--mode",
        type=str,
        default="acq",
        choices=["acq", "test"],
        help="Starting action for the Agent.",
    )

    pgroup.add_argument(
        "--directory",
        type=str,
        required=True,
        help="Directory for media buffers (snapshots and recordings)",
    )

    pgroup.add_argument(
        "--address",
        type=str,
        required=True,
        help="Hostname or IP address of camera",
    )

    pgroup.add_argument(
        "--user",
        type=str,
        required=True,
        help="User name for camera access",
    )

    pgroup.add_argument(
        "--password",
        type=str,
        required=True,
        help="Password for camera access",
    )

    pgroup.add_argument(
        "--motion_start",
        type=str,
        default=None,
        required=False,
        help="ISO 8601 time (HH:MM:SS+-zz:zz) to begin motion detection",
    )

    pgroup.add_argument(
        "--motion_stop",
        type=str,
        default=None,
        required=False,
        help="ISO 8601 time (HH:MM:SS+-zz:zz) to end motion detection",
    )

    pgroup.add_argument(
        "--snapshot_seconds",
        type=int,
        required=False,
        default=10,
        help="Number of seconds between snapshots for motion detection",
    )

    pgroup.add_argument(
        "--port",
        type=int,
        required=False,
        default=554,
        help="The RTSP port number",
    )

    pgroup.add_argument(
        "--urlpath",
        type=str,
        default=None,
        required=False,
        help="The path portion of the URL.  Default will use values for Dahua cameras.",
    )

    pgroup.add_argument(
        "--jpeg_quality",
        type=int,
        required=False,
        default=20,
        help="The JPEG quality (0-100)",
    )

    pgroup.add_argument(
        "--max_snapshot_files",
        type=int,
        required=False,
        default=17280,  # 2 days at 10s per snapshot
        help="Maximum number of images to keep in the circular buffer",
    )

    pgroup.add_argument(
        "--record_fps",
        type=float,
        required=False,
        default=20.0,
        help="The frames per second for video recording",
    )

    pgroup.add_argument(
        "--record_duration",
        type=float,
        required=False,
        default=60,
        help="The length in seconds to record video.",
    )

    pgroup.add_argument(
        "--max_record_files",
        type=int,
        required=False,
        default=120,  # Most recent 2 hours of motion capture
        help="Maximum number of images to keep in the circular buffer",
    )

    pgroup.add_argument(
        "--fake",
        action="store_true",
        required=False,
        default=False,
        help="Use an internal fake camera for acquisition",
    )

    pgroup.add_argument(
        "--disable_motion",
        action="store_true",
        required=False,
        default=False,
        help="Disable motion detection",
    )

    return parser


def main(args=None):
    txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(
        agent_class="RTSPCameraAgent", parser=parser, args=args
    )

    if args.mode == "acq":
        init_params = {"test_mode": False}
    elif args.mode == "test":
        init_params = {"test_mode": True}

    agent, runner = ocs_agent.init_site_agent(args)

    cam = RTSPCameraAgent(
        agent,
        args.directory,
        args.address,
        args.user,
        args.password,
        seconds=args.snapshot_seconds,
        port=args.port,
        urlpath=args.urlpath,
        jpeg_quality=args.jpeg_quality,
        max_snapshot_files=args.max_snapshot_files,
        record_fps=args.record_fps,
        record_duration=args.record_duration,
        max_record_files=args.max_record_files,
        fake=args.fake,
        motion_start=args.motion_start,
        motion_stop=args.motion_stop,
        disable_motion=args.disable_motion,
    )
    agent.register_process("acq", cam.acq, cam._stop_acq, startup=init_params)
    agent.register_task(
        "record", cam.record, aborter=cam._abort_record
    )
    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
