
import os

import psutil
import pytest


@pytest.fixture(autouse=True, scope='module')
def check_subprocesses():
    # Get a list of child PIDs before the test starts
    parent = psutil.Process(os.getpid())
    before_children = {child.pid for child in parent.children(recursive=True)}

    yield

    after_children = {child.pid for child in parent.children(recursive=True)}
    leftover_processes = after_children - before_children

    if leftover_processes:
        leftover_details = [
            f"PID {p.pid}: {p.cmdline()}" for p in parent.children(recursive=True) if p.pid in leftover_processes
        ]
        pytest.fail(f"Lingering subprocesses detected:\n" + "\n".join(leftover_details))
