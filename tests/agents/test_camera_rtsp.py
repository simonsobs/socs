try:
    import cv2
    import imutils

    from socs.agents.camera_rtsp.agent import CameraRTSPAgent  # noqa: F401
except ImportError:
    print("Opencv / imutils not available- skipping CameraRTSPAgent tests")
