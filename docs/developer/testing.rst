Testing
=======

Testing SOCS Agent code is critical to ensuring code functions properly,
especially when making changes after initial creation of the Agent. Testing
within SOCS comes in two forms, unit tests and integration tests.

Unit tests test functionality of the Agent code directly, without running the
Agent itself (or any supporting parts, such as the crossbar server, or a piece
of hardware to connect to.)

Integration tests run a small OCS network, starting up the crossbar server, and
likely require some code emulating the piece of hardware the OCS Agent is built
to communicate with. Integration tests are more involved than unit tests,
requiring more setup and thus taking longer to execute than unit tests. Both
are important for fully testing the functionality of your Agent.

Running Tests
-------------

.. include:: ../../tests/README.rst
    :start-line: 2
