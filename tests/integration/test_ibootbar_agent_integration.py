import pytest
import threading
import time
from unittest.mock import patch
from snmpsim.commands import responder


@pytest.fixture
def start_responder():
    def f():
        with patch(
            "sys.argv",
            [
                "test_ibootbar_agent_integration.py",
                "--data-dir=/home/jguo/snmpsim-work/data",
                "--agent-udpv4-endpoint=127.0.0.1:1024",
            ],
        ):
            responder.main()

    t = threading.Thread(target=f)
    t.start()


start_responder()
time.sleep(2)
print("main thread here")
