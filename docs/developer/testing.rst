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

Writing Tests
-------------
When writing integration tests for an Agent we need to mock the communication
with the hardware the Agent interfaces with. We can do that with the
DeviceEmulator. socs provides a function for creating pytest fixtures that
yield a Device Emulator. Here's an example of how to use it:

.. code-block:: python

    # define the fixture, including any responses needed for Agent startup
    emulator = create_device_emulator({'*IDN?': 'LSCI,MODEL425,4250022,1.0'}, relay_type='serial')

    @pytest.mark.integtest
    def test_ls425_operational_status(wait_for_crossbar, emulator, run_agent, client):
        # define the responses needed for this test
        responses = {'OPST?': '001'}
        emulator.define_responses(responses)

        # run task that sends the 'OPST?' command
        resp = client.operational_status()
        assert resp.status == ocs.OK
        assert resp.session['op_code'] == OpCode.SUCCEEDED.value

In the example, we initialize the emulator with any commands and responses
needed for Agent startup, and specify that the Agent communicates via serial.
Then, within the test, we define commands and their responses needed during
testing. In this case that is the ``OPST?`` command and the expected response of
``001``. Once these are saved with
:func:`socs.testing.device_emulator.DeviceEmulator.define_responses` we can run
our Agent Tasks/Processes for testing.

API
---
.. automodule:: socs.testing.device_emulator
    :members:
