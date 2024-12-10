# Copyright (C) 2023-2024 Simons Observatory Collaboration
# See top-level LICENSE.txt file for more information.
"""Tools for working with image / video cameras.
"""
import glob
import os
import re
import shutil
from collections import deque
from datetime import datetime, timezone

import numpy as np

try:
    import cv2
    import imutils
    have_cv2 = True
except ImportError:
    have_cv2 = False


def image_read_callback(path):
    """Read callback for OpenCV images.

    This is for use with the CircularMediaBuffer class.

    Args:
        path (str):  Path to the image file.

    Returns:
        (array):  Image data.

    """
    return cv2.imread(path)


def image_write_callback(data, path, quality=20):
    """Write callback for OpenCV images.

    This is for use with the CircularMediaBuffer class.

    Args:
        data (array):  Image data.
        path (str):  Path to the image file.
        quality (int):  JPEG quality (0-100).

    Returns:
        None

    """
    cv2.imwrite(path, data, [int(cv2.IMWRITE_JPEG_QUALITY), quality])


def video_read_callback(path):
    """Read callback for OpenCV video.

    This is for use with the CircularMediaBuffer class.

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
    """Write callback for OpenCV video.

    This is for use with the CircularMediaBuffer class.

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
        # be unreliable.  Instead we sort by ISO date/time encoded in the filename.
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
            file, buffer = self._deque[pos]
            del buffer
            self._deque[pos] = (file, None)

        # Update latest copy
        latest = os.path.join(self.dir, f"latest.{self.suffix}")
        shutil.copy2(path, latest)

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
        pat = re.compile(f"{self.root}_(.*)\\.{self.suffix}")
        mat = pat.match(file)
        iso = mat.group(1)
        return self._iso_to_dt(iso)

    def _dt_to_iso(self, dt):
        return dt.isoformat(sep="T", timespec="seconds")

    def _iso_to_dt(self, iso):
        return datetime.datetime.fromisoformat(iso)


class MotionDetector:
    """Class to process images in sequence and look for changes.

    This uses the (stateful) helper tools from OpenCV to detect when an
    image contains changes from previous ones.

    Args:
        blur (int):  The odd number of pixels for blurring width
        threshold (int):  The grayscale threshold (0-255) for considering
            image changes in the blurred images.
        dilation (int):  The dilation iterations on the thresholded image.
        min_frac (float):  The minimum fraction of pixels that must change
            to count as a detection.
        max_frac (float):  The maximum fraction of pixels that can change
            to still count as a detection (rather than a processing error).

    """

    def __init__(
        self,
        blur=51,
        threshold=100,
        dilation=2,
        min_frac=0.005,
        max_frac=0.9,
    ):
        if blur % 2 == 0:
            raise ValueError("blur must be an odd integer")
        self.blur = blur
        if threshold < 0 or threshold > 255:
            raise ValueError("threshold should be between 0-255")
        self.thresh = int(threshold)
        if dilation > 10:
            raise ValueError("dilation should be a small, positive integer")
        self.dilation = dilation
        self.min_frac = min_frac
        self.max_frac = max_frac
        self._backsub = cv2.createBackgroundSubtractorMOG2()

    def reset(self):
        """Reset the background subtraction."""
        self._backsub = cv2.createBackgroundSubtractorMOG2()

    def process(self, data, skip=False):
        """Process image data and look for changes.

        Args:
            data (array):  The image data.
            skip (bool):  If True, accumulate image to background model, but
                do not look for motion.

        Returns:
            (tuple):  The (image, detection).

        """
        gray = cv2.cvtColor(data, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (self.blur, self.blur), 0)

        mask = self._backsub.apply(blurred)
        if skip:
            return (data, False)

        thresholded = cv2.threshold(mask, self.thresh, 255, cv2.THRESH_BINARY)[1]
        dilated = cv2.dilate(thresholded, None, iterations=self.dilation)
        cnts = cv2.findContours(
            dilated.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cnts = imutils.grab_contours(cnts)

        # loop over the contours
        img_area = thresholded.shape[0] * thresholded.shape[1]
        min_area = self.min_frac * img_area
        max_area = self.max_frac * img_area
        detection = False
        for c in cnts:
            # if the contour is too small or too large, ignore it
            area = cv2.contourArea(c)
            if area < min_area:
                continue
            if area > max_area:
                continue
            # compute the bounding box for the contour, draw it on the frame,
            # and update the text
            detection = True
            (x, y, w, h) = cv2.boundingRect(c)
            cv2.rectangle(data, (x, y), (x + w, y + h), (0, 255, 0), 2)
        return (data, detection)


class FakeCamera:
    """Class used generate image data on demand for testing.

    The API for this class is intended to match the one provided
    by cv2.VideoCapture objects.

    Args:
        width (int):  Width of each frame in pixels.
        height (int):  Height of each frame in pixels.
        fps (float):  The frames per second of the stream.

    """

    def __init__(self, width=1280, height=720, fps=20.0):
        self.width = width
        self.height = height
        self.fps = fps

        # The number of frames to hold fixed before switching
        self.fixed_frames = int(60 * self.fps)

        # The size of a square to randomly place in the field of view
        self.square_dim = 100
        self.sq_half = self.square_dim // 2
        self._random_sq_pos()

        self.current = None
        self.frame_count = 0

    def isOpened(self):
        return True

    def _random_sq_pos(self):
        sq_y = int(self.height * np.random.random_sample(size=1)[0])
        sq_x = int(self.width * np.random.random_sample(size=1)[0])
        if sq_y > self.height - self.sq_half:
            sq_y = self.height - self.sq_half
        if sq_y < self.sq_half:
            sq_y = self.sq_half
        if sq_x > self.width - self.sq_half:
            sq_x = self.width - self.sq_half
        if sq_x < self.sq_half:
            sq_x = self.sq_half
        self.sq_x = sq_x
        self.sq_y = sq_y

    def grab(self):
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:, :, 0] = 127
        img[:, :, 1] = 127
        img[:, :, 2] = 127
        if self.frame_count % self.fixed_frames == 0:
            self._random_sq_pos()
        img[
            self.sq_y - self.sq_half: self.sq_y + self.sq_half,
            self.sq_x - self.sq_half: self.sq_x + self.sq_half,
            0,
        ] = 255
        self.current = img
        self.frame_count += 1
        return True

    def retrieve(self):
        img = np.array(self.current)
        self.current = None
        return True, img

    def read(self):
        _ = self.grab()
        return self.retrieve()

    def release(self):
        pass
