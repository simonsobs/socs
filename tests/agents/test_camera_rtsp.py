try:
    import cv2 # noqa: F401
    import imutils # noqa: F401
    from socs.agents.camera_rtsp.agent import CameraRTSPAgent  # noqa: F401
except ImportError:
    print("Opencv / imutils not available- skipping CameraRTSPAgent tests")
