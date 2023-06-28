Tests
=====

We use `pytest <https://docs.pytest.org/>`_ as the test runner for SOCS. To run
all of the tests, from with in the ``socs/tests/`` directory, run pytest::

    $ python3 -m pytest --cov

This will run every test, both unit and integration tests. Integration tests
depend on mocked up versions of the hardware the agents in question interface
with. Testing against actual hardware has previously been done in the
``hardware/`` directory. These hardware tests will not automatically be run.

Test Selection
--------------

You typically will not want to run all tests all the time. There are many ways
to limit which tests run. Here are some examples.

Run only one test file::

    $ python3 -m pytest --cov socs agents/test_ls372_agent.py

Run tests based on test name(s)::

    $ python3 -m pytest --cov -k 'test_ls372_init_lakeshore_task'

Note that this will match to the beginning of the test names, so the above will
match 'test_ls372_init_lakeshore_task' as well as
'test_ls372_init_lakeshore_task_already_initialzed'.

Custom Markers
``````````````
There are some custom markers for tests in SOCS, 'integtest' for integration
tests, and 'spt3g' for tests dependent on
`spt3g_software <https://github.com/CMB-S4/spt3g_software>`_. These markers can
be used to select or deselect tests.

To run only the unit tests run::

    $ python3 -m pytest --cov -m 'not integtest'

To run only the integration tests::

    $ python3 -m pytest --cov -m 'integtest'

.. note::
    The integration tests depend on '--cov' being used, so all examples here
    throw that flag. You could omit it when running unit tests, but it's often
    useful to view coverage results anyway.

You can view the available markers with::

    $ python3 -m pytest --markers
    @pytest.mark.integtest: marks tests as integration test (deselect with '-m "not integtest"')
    @pytest.mark.spt3g: marks tests that depend on spt3g (deselect with '-m "not spt3g"')

Code Coverage
-------------
Code coverage measures how much of the code the tests cover. This is typically
reported as a percentage of lines executed during testing. Coverage is measured
with `Coverage.py <https://coverage.readthedocs.io/>`_.

To obtain code coverage::

    $ python3 -m pytest --cov --cov-report=html

You can then view the coverage report in the ``htmlcov/`` directory. Coverage
for SOCS is also automatically reported to
`coveralls.io <https://coveralls.io/github/simonsobs/socs>`_.

Testing Against Hardware
------------------------

.. warning::
    Testing against hardware is not well supported at this time. Tests early on
    in development were initially built against actual hardware, but have since
    been neglected.

If you are designing and running tests against actual hardware you should store
and run them directly from the hardware directory, which is configured to be
ignored by the automatic test discovery in pytest.

When running against hardware, call only the test you'd like to run. For
instance, to test just the Lakeshore 372::

  $ cd hardware/
  $ python3 -m pytest test_ls372.py
