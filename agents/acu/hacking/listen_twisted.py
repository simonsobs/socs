# Twisted UDP demo -- you need to start the UDP stream separately.

from twisted.internet import reactor, protocol, endpoints
from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep as dsleep

import struct
import time


# Temporary hack for importing aculib during dev.
import os, sys
here = os.path.split(__file__)[0]
sys.path.append(os.path.join(here, '../'))
import aculib


@inlineCallbacks
def test_listen():
    print('Creating a listener and adding to reactor...')
    FMT = '<iddd'
    FMT_LEN = struct.calcsize(FMT)

    # Declare the class inside the function, so it has access to the
    # values of variables at the present time (FMT, FMT_LEN).

    class MonitorUDP(protocol.DatagramProtocol):
        def datagramReceived(self, data, src_addr):
            # We don't really care, but this is the host+port...
            host, port = src_addr

            # Unpack, and print the last element.
            offset = 0
            while len(data) - offset >= FMT_LEN:
                d = struct.unpack(FMT, data[offset:offset+FMT_LEN])
                offset += FMT_LEN
            print(d)

            # This bit just implements a rate announcement, storing
            # some state in self._counter.
            if getattr(self, '_counter', None) is None:
                def announce():
                    n, t0 = self._counter
                    t1 = time.time()
                    rate = (n - 1) / (t1 - t0)
                    print('Receiving packets at %.1f Hz' % rate)
                    if n > 1:
                        self._counter = 1, t1
                        reactor.callLater(1, announce)
                    else:
                        self._counter = None
                reactor.callLater(1, announce)
                self._counter = 1, time.time()
            else:
                n, t0 = self._counter
                self._counter = n+1, t0

    # Just to show we can, connect and kill the monitor in a loop.
    UDP_IP = "172.16.5.10"  # local host
    UDP_PORT = 10000
    # This one-liner is enough to connect the handler:
    #
    #    reactor.listenUDP(UDP_PORT, MonitorUDP())
    #
    # But since we might want to be able to tear-down and re-setup the
    # handler, demonstrate that in a loop:
    while True:
        print('Attaching for 5 seconds...')
        handler = reactor.listenUDP(UDP_PORT, MonitorUDP())
        yield dsleep(5)
        print('Detaching for 2 seconds...')
        handler.stopListening()
        yield dsleep(2)

    # You only need this yield if you have no other yields to make
    # this a generator.
    #yield None
#How do we know this is working? It doesn't print any data--should it?

reactor.callLater(1, test_listen)
reactor.run()
