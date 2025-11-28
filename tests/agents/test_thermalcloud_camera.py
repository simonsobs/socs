try:
    from socs.agents.thermalcloud_camera.agent import ThermalCloudCameraAgent  # noqa: F401
except ImportError:
    print("skipping ThermalCloudCameraAgent tests")
