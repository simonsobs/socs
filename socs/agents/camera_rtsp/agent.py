# Copyright (C) 2023-2024 Simons Observatory Collaboration
# See top-level LICENSE.txt file for more information.
"""Agent to capture images from cameras which support the RTSP protocol.
"""

import os
import glob
import shutil
import re
import time
from datetime import datetime, timezone

import numpy as np
import cv2
import txaio

from collections import deque

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

txaio.use_twisted()


def image_read_callback(path):
    """Read callback for images.

    Args:
        path (str):  Path to the image file.

    Returns:
        (array):  Image data.

    """
    return cv2.imread(path)


def image_write_callback(data, path, quality=20):
    """Write callback for images.

    Args:
        data (array):  Image data.
        path (str):  Path to the image file.
        quality (int):  JPEG quality (0-100).

    Returns:
        None

    """
    cv2.imwrite(path, data, [int(cv2.IMWRITE_JPEG_QUALITY), quality])


def video_read_callback(path):
    """Read callback for video.

    Args:
        path (str):  Path to the video file.

    Returns:
        (array):  video data.

    """
    data = list()
    cap = cv2.VideoCapture(path)
    success = True
    while success:
        success, frame = cap.read()
        if success:
            data.append(frame)
    cap.release()
    return data


def video_write_callback(data, path, fps=20.0):
    """Write callback for video.

    Args:
        data (list):  List of frames.
        path (str):  Path to the video file.

    Returns:
        None

    """
    first = data[0]
    height = first.shape[0]
    width = first.shape[1]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(path, fourcc, fps, (width, height))
    for frame in data:
        out.write(frame)
    out.release()


class CircularMediaBuffer:
    """Class to manage a circular media file buffer on disk.

    Rather than try to guess the average file size and target disk usage,
    this class just manages a fixed number of files within a directory.

    The filenames and file data are stored as tuples in a deque.  Only the
    data for recent files is kept in memory.

    If the read callback function is None, no recent data is kept in memory.
    Any additional kwargs to the constructor are passed to the write
    callback function.

    Args:
        directory (str): The path to the directory of image files.  This
            should be a directory that is completely managed by this class
            which contains no other files.
        root_name (str): The root of each file name (e.g. "img", "vid").
        suffix (str): The file suffix (e.g. "jpg", "mp4").
        max_files (int): The maximum number of files to keep.
        write_callback (function): The function to use for writing files.
        read_callback (function): The function to use for loading recent
            files.
        recent (int): The number of recent images to keep in memory.

    """

    def __init__(
        self,
        directory,
        root_name,
        suffix,
        max_files,
        write_callback,
        read_callback=None,
        recent=3,
        **kwargs,
    ):
        self.dir = os.path.abspath(directory)
        if not os.path.isdir(self.dir):
            os.makedirs(self.dir)
        self.max_files = max_files
        self.recent = recent
        self.root = root_name
        self.suffix = suffix
        self.writer = write_callback
        self.reader = read_callback
        self.writer_opts = kwargs

        # Load current files into our store
        existing_files = filter(
            os.path.isfile,
            glob.glob(os.path.join(self.dir, f"{self.root}_*.{self.suffix}")),
        )

        # We could sort by modification time, but if files were copied that could
        # be unreliable.  Instead we sort by date/time encoded in the filename.
        self._deque = deque()
        for file in sorted(existing_files):
            self._deque.append((file, None))

        # Load recent
        if self.reader is not None:
            to_load = min(len(self._deque), self.recent)
            for idx in range(to_load):
                pos = -(idx + 1)
                file = self._deque[pos][0]
                self._deque[pos] = (file, self.reader(file))

    def store(self, data):
        now = datetime.now(tz=timezone.utc)
        path = self._media_path(now)
        self.writer(data, path, **self.writer_opts)
        self.prune()
        if self.recent > 0:
            self._deque.append((path, data))
        else:
            self._deque.append((path, None))

        # Clear stale recent entry
        if len(self._deque) > self.recent and self.recent > 0:
            pos = -(self.recent + 1)
            file = self._deque[pos][0]
            past = self._deque[pos][1]
            del past
            self._deque[pos] = (file, None)

        # Update latest symlink
        link = os.path.join(self.dir, f"latest.{self.suffix}")
        if os.path.exists(link):
            os.remove(link)
        os.symlink(path, link)

    def fetch_recent(self):
        result = list()
        to_fetch = min(len(self._deque), self.recent)
        for idx in range(to_fetch):
            pos = -(to_fetch + idx)
            result.append(self._deque[pos])
        return result

    def fetch_index(self, index):
        return self._deque[index]

    def prune(self):
        while len(self._deque) >= self.max_files:
            file, buffer = self._deque.popleft()
            del buffer
            self._remove(file)

    def _remove(self, path):
        if not os.path.isfile:
            raise RuntimeError(f"{path} does not exist, cannot remove")
        os.remove(path)

    def _media_path(self, dt):
        dstr = self._dt_to_iso(dt)
        return os.path.join(self.dir, f"{self.root}_{dstr}.{self.suffix}")

    def _media_time(self, path):
        file = os.path.basename(path)
        pat = re.compile(f"{self.root}_(.*)\.{self.suffix}")
        mat = pat.match(file)
        iso = mat.group(1)
        return self._iso_to_dt(iso)

    def _dt_to_iso(self, dt):
        return dt.isoformat(sep="T", timespec="seconds")

    def _iso_to_dt(self, iso):
        return datetime.datetime.fromisoformat(iso)


class CameraRTSPAgent:
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
        quality (int): The JPEG quality for output images (0-100).
        max_buffer_files (int): The maximum number of files to keep in the image
            buffer directory.

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
                    'address': 'camera-c1.simonsobs.org',
                    'timestamp': 1701983575.123456,
                    'path': '/ocs/cameras_rtsp/c1/img_2023-12-29T02:44:47+00:00.jpg',
                }

        """
        pm = Pacemaker(1 / self.seconds, quantize=False)
        pmgrab = Pacemaker(self.record_fps, quantize=True)

        frames_per_snapshot = int(self.seconds * self.record_fps)

        session.set_status("running")
        self.is_streaming = True

        # Open camera stream
        cap = cv2.VideoCapture(self.connection)
        if not cap.isOpened():
            self.log.error(f"Cannot open RTSP stream at {self.connection}")
            return False, "Could not open RTSP stream"

        # Tracking state of whether we are already recording motion detection
        detecting = False
        detect_start = None
        record_frames = int(self.record_fps * self.record_duration)
        # backsub = cv2.createBackgroundSubtractorMOG2()
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        backsub = cv2.bgsegm.createBackgroundSubtractorGMG()

        snap_count = 0
        while self.is_streaming:
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
                return False, "Broken stream"

            # Motion detection.  Get the recent images and use them to define
            # the background.  Extract pixels with movement and if a large
            # enough region is detected, trigger the recording task.

            mask = backsub.apply(image)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel) 
            image_write_callback(mask, os.path.join(self.img_dir, f"mask_{snap_count}.jpg"))

            if snap_count > 4:
                # We have enough frames to trust the result
                pass

            # Save to circular buffer
            self.img_buffer.store(image)

            # Get the saved path
            path = self.img_buffer.fetch_index(-1)[0]

            # Fill data
            data = {
                "address": self.address,
                "timestamp": timestamp,
                "path": path,
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
            session.set_status("stopping")
            self.is_streaming = False
            return True, "Stopping Acquisition"
        else:
            return False, "Acq is not currently running"

    @ocs_agent.param("test_mode", default=False, type=bool)
    def record(self, session, params=None):
        """Record video stream.

        **Task** - Record video at specified framerate for fixed timespan.

        Parameters:
            auto_acquire (bool): Automatically start acq process after
                initialization. Defaults to False.

        """
        if params["test_mode"]:
            # Only record for a few seconds
            duration = 5
        else:
            duration = self.record_duration

        with self.lock.acquire_timeout(0, job="record") as acquired:
            if not acquired:
                self.log.warn(
                    "Could not start recording because "
                    "{} is already running".format(self.lock.job)
                )
                return False, "Could not acquire lock."

            session.set_status("starting")

            pm = Pacemaker(self.record_fps, quantize=True)

            # Open camera stream
            cap = cv2.VideoCapture(self.connection)
            if not cap.isOpened():
                self.log.error(f"Cannot open RTSP stream at {self.connection}")
                return False, "Could not open RTSP stream"
            
            # Total number of frames
            total_frames = int(self.record_fps * duration)
        
            self.log.info(f"Recording {total_frames} frames ({duration}s at {self.record_fps}fps)")

            self.log.info(f"Begin recording")

            frames = list()
            for iframe in range(total_frames):
                pm.sleep()
                # Grab an image
                success, image = cap.read()
                if not success:
                    msg = f"Broken stream at frame {iframe}, ending recording"
                    self.log.error(msg)
                    break
                frames.append(image)

            # Save to circular buffer
            self.vid_buffer.store(frames)

            # Get the saved path
            path = self.vid_buffer.fetch_index(-1)[0]

            self.log.info(f"Finished recording {path}")

        return True, "Recording finished."


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
        help="Directory for circular image buffer",
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
        "--seconds",
        type=int,
        required=False,
        default=10,
        help="Number of seconds between frame grabs",
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
        default=17280, # 2 days at 10s per snapshot
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
        default=100,
        help="Maximum number of images to keep in the circular buffer",
    )

    return parser


def main(args=None):
    txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(
        agent_class="CameraRTSPAgent", parser=parser, args=args
    )

    if args.mode == "acq":
        acq_params = {"test_mode": False}
        rec_params = {"test_mode": False}
    elif args.mode == "test":
        acq_params = {"test_mode": True}
        rec_params = {"test_mode": True}

    agent, runner = ocs_agent.init_site_agent(args)

    cam = CameraRTSPAgent(
        agent,
        args.directory,
        args.address,
        args.user,
        args.password,
        seconds=args.seconds,
        port=args.port,
        urlpath=args.urlpath,
        jpeg_quality=args.jpeg_quality,
        max_snapshot_files=args.max_snapshot_files,
        record_fps=args.record_fps,
        record_duration=args.record_duration,
        max_record_files=args.max_record_files,
    )
    agent.register_process("acq", cam.acq, cam._stop_acq, startup=acq_params)
    agent.register_task("record", cam.record, startup=rec_params)
    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
