import pytest
from ocs.matched_client import MatchedClient


def pytest_addoption(parser):
    parser.addoption(
        '--instance-id', default='thermo1', help="Instance id for LS240."
    )


@pytest.fixture
def client(request):
    inst = request.config.getoption('--instance-id')
    c = MatchedClient(inst, args=[])
    print("Initializing Lakeshore.....")
    c.init_lakeshore.start()
    x = c.init_lakeshore.wait()
    return c