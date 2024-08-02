import os

import pytest
from ocs.testing import check_crossbar_connection


def create_crossbar_fixture():
    # Fixture to wait for crossbar server to be available.
    # Speeds up tests a bit to have this session scoped
    # If tests start interfering with one another this should be changed to
    # "function" scoped and session_scoped_container_getter should be changed
    # to function_scoped_container_getter
    # @pytest.fixture(scope="function")
    # def wait_for_crossbar(function_scoped_container_getter):
    @pytest.fixture(scope="session")
    def wait_for_crossbar(docker_services):
        """Wait for the crossbar server from docker compose to become
        responsive.

        """
        check_crossbar_connection()

    return wait_for_crossbar


# Overrides the default location that pytest-docker looks for the compose file.
# https://pypi.org/project/pytest-docker/
@pytest.fixture(scope="session")
def docker_compose_file(pytestconfig):
    return os.path.join(str(pytestconfig.rootdir), "docker-compose.yml")
