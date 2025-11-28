# Copyright (C) 2023-2024 Simons Observatory Collaboration
# See top-level LICENSE.txt file for more information.
"""Agent to capture images from thermal cloud cameras using MJPG.
This is minor modification of RTSPCameraAgent
"""
import os
import time

import cv2
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

txaio.use_twisted()

from socs.common.camera import (CircularMediaBuffer, FakeCamera,
                                image_read_callback,
                                image_write_callback)


class ThermalCloudCameraAgent:
    """Agent to support image capture from thermal cloud cameras.

    This Agent captures images and writes them to a feed, as well as saving frames
    to disk.  The camera can also be triggered to record....

    Args:
        agent (OCSAgent): OCSAgent object from :func:`ocs.ocs_agent.init_site_agent`.
        directory (str): The path to image storage for this camera.
        address (str): The hostname or IP address of the camera.
        seconds (int): The seconds between snapshots. (default 30)
        port (int): The port to use (default 8080).
        urlpath (str): The remaining URL for the camera, which might include
            options like channel and subtype.  This will depend on the manufacturer. (default ircam_last)
        fps (float): The frames per second of the stream.
        jpeg_quality (int): The JPEG quality for snapshot images (0-100).
        max_snapshot_files (int): The maximum number of snapshots to keep.
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
        seconds=30,
        port=8080,
        urlpath='ircam_last',
        fps=2.0,
        jpeg_quality=90,
        max_snapshot_files=10000,
        fake=False,
    ):
        self.agent = agent
        self.topdir = directory
        self.log = agent.log
        self.lock = TimeoutLock(default_timeout=5)

        self.address = address
        self.port = port
        self.seconds = seconds
        self.urlpath = urlpath
        self.fake = fake

        self.connection = f"http://{self.address}:{self.port}/{self.urlpath}"

        # We will store recordings and snapshots to separate subdirs
        if not os.path.isdir(self.topdir):
            os.makedirs(self.topdir)
        self.img_dir = os.path.join(self.topdir, "snapshots")
        self.fps = fps

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

        # Register OCS feed
        self.feed_name = f"ThmCldCam_{self.address}"

        agg_params = {"frame_length": self.seconds}  # [sec]
        self.agent.register_feed(
            self.feed_name,
            record=True,
            agg_params=agg_params,
            buffer_time=1.0,
        )

    def _init_stream(self):
        """Connect to camera and initialize video stream."""
        if self.fake:
            cap = FakeCamera()
        else:
            cap = cv2.VideoCapture(self.connection)
        if not cap.isOpened():
            self.log.error(f"Cannot open stream at {self.connection}")
            return None

        return cap

    @ocs_agent.param("test_mode", default=False, type=bool)
    def acq(self, session, params=None):
        """acq(test_mode=False)

        **Process** - Capture frames from an thermal cloud camera.

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
        pmgrab = Pacemaker(self.fps, quantize=True)

        frames_per_snapshot = int(self.seconds * self.fps)

        self.is_streaming = True

        # Open camera stream
        cap = self._init_stream()
        connected = True
        if not cap:
            connected = False

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
        "--snapshot_seconds",
        type=int,
        required=False,
        default=30,
        help="Number of seconds between snapshots",
    )

    pgroup.add_argument(
        "--port",
        type=int,
        required=False,
        default=8080,
        help="The stream port number",
    )

    pgroup.add_argument(
        "--urlpath",
        type=str,
        default='ircam_last',
        required=False,
        help="The path portion of the URL.",
    )

    pgroup.add_argument(
        "--fps",
        type=float,
        required=False,
        default=2.0,
        help="The frames per second",
    )

    pgroup.add_argument(
        "--jpeg_quality",
        type=int,
        required=False,
        default=90,
        help="The JPEG quality (0-100)",
    )

    pgroup.add_argument(
        "--max_snapshot_files",
        type=int,
        required=False,
        default=5760,  # 2 days at 30s per snapshot
        help="Maximum number of images to keep in the circular buffer",
    )

    pgroup.add_argument(
        "--fake",
        action="store_true",
        required=False,
        default=False,
        help="Use an internal fake camera for acquisition",
    )

    return parser


def main(args=None):
    txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(
        agent_class="ThermalCloudCameraAgent", parser=parser, args=args
    )

    if args.mode == "acq":
        init_params = {"test_mode": False}
    elif args.mode == "test":
        init_params = {"test_mode": True}

    agent, runner = ocs_agent.init_site_agent(args)

    cam = ThermalCloudCameraAgent(
        agent,
        args.directory,
        args.address,
        seconds=args.snapshot_seconds,
        port=args.port,
        urlpath=args.urlpath,
        fps=args.fps,
        jpeg_quality=args.jpeg_quality,
        max_snapshot_files=args.max_snapshot_files,
        fake=args.fake,
    )
    agent.register_process("acq", cam.acq, cam._stop_acq, startup=init_params)
    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
