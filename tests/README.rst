=======
Testing
=======

Unit tests for OCS. These historically were separated into tests for hardware
and mock tests (meaning simulated hardware). Automated tests currently run on
all tests other than those in this old directories. Hardware tests are very
useful, but not always able to be run, pending the availability of the
hardware. All other tests should be runable independently.

Running the Test Suite
----------------------
To run the tests, from the top level of the repo run::

    $ python3 -m pytest -p no:wampy --cov-report html --cov socs ./tests/

You can then view the coverage report in the typical ``htmlcov/`` directory.


If you are running tests on hardware you likely want to run them directly from
the hardware directory, which is configured to be ignored by the automatic test
discovery in pytest.

When running on hardware, call only the test you'd like to run. For instance,
to test just the Lakeshore 372::

  $ cd hardware/
  $ python3 -m pytest test_ls372.py
