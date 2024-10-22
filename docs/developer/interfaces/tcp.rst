.. _tcp:

===================================
Transmission Control Protocol (TCP)
===================================

SOCS provides a standard interface for connecting to devices using TCP. This
page details how to use this interface. The primary benefit to using this
interface is the included error handling.

A few important things to know about the behavior of the interface class:

* The interface tries to connect to the device when instantiated.
* It will log but not raise an error if it cannot connect, instead
  ``self.comm`` will be ``None``.
* The connection will be reset when ``send()`` is called if this happens.
  An exception will be raised if it still cannot connect.
* The interface is built to mimic ``socket.send()`` and ``socket.recv()``, but
  uses ``socket.sendall()`` in its implementation, so all bytes in the included
  message are sent to the socket.

See the example below for how to implement use of the ``TCPInterface`` class in
your device drivers and how to add error handling to the agent.

Example
-------
An example of using ``TCPInterface`` to create a class that interfaces with a
device::

    from socs.tcp import TCPInterface

    class Device(TCPInterface):
        def __init__(self, ip_address, port=501, timeout=10, *args, **kwargs):
            # Setup the TCP Interface
            super().__init__(ip_address, port, timeout)

        def get_data(self):
            self.send(query_string)
            data = self.recv()
            # Optionally perform any decoding required
            return data

Within the agent code where ``Device.get_data`` is used you should now handle
the possible ``ConnectionError``, as shown below.

.. note::
    This example is stripped down to focus on the error handling. Important
    parts of the agent process are missing here, like obtaining the lock and
    publishing data to a feed.

.. code-block::

    class DeviceAgent:
        self.device = Device('192.168.1.2')

    def main(self, session, params):
        """Main data acquisition process."""

        while session.status in ['starting', 'running']:
            try:
                data = self.device.get_data()
                if session.degraded:
                    self.log.info("Connection re-established.")
                    session.degraded = False
            except ConnectionError:
                self.log.error("Failed to get data from device. Check network connection.")
                session.degraded = True
                time.sleep(1)  # wait between reconnection attempts
                continue

        return True, "Main process exited successfully."

See existing TCP agents, such as the Cryomech CPA Agent (which the above
example is based on) for more examples.

API
---

If you are developing an agent that connects to a device using TCP, the
``TCPInterface`` class is available for use and detailed here:

.. autoclass:: socs.tcp.TCPInterface
    :members:
