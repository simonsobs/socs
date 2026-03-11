try:
    import cv2  # noqa: F401
    import imutils  # noqa: F401

    from socs.agents.rtsp_camera.agent import RTSPCameraAgent  # noqa: F401
except ImportError:
    print("Opencv / imutils not available- skipping RTSPCameraAgent tests")
