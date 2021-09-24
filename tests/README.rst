Tests
=====

We use pytest for the test running in SOCS. To run all of the tests, from with
in this ``tests/`` directory, run pytest::

    $ python3 -m pytest

This will run every test, both unit and integration tests. Integration tests
depend on mocked up versions of the hardware the agents in question interface
with. Testing against actual hardware has previously been done in the
``hardware/`` directory. These tests will not automatically be run.

Unit Tests
----------

To run only the unit tests run::

    $ python3 -m pytest -m 'not integtest'

This will exclude the integration tests.

Code Coverage
-------------
To obtain code coverage::

    $ python3 -m pytest --cov --cov-report=html

You can then view the coverage report in the ``htmlcov/`` directory.

Testing Against Hardware
------------------------

If you are running tests on hardware you likely want to run them directly from
the hardware directory, which is configured to be ignored by the automatic test
discovery in pytest.

When running on hardware, call only the test you'd like to run. For instance,
to test just the Lakeshore 372::

  $ cd hardware/
  $ python3 -m pytest test_ls372.py
