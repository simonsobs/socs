import time
import socket
import select


class PrologixInterface:
    def __init__(self, ip_address, gpibAddr, **kwargs):
        self.ip_address = ip_address
        self.gpibAddr = gpibAddr
        self.sock = None
        self.conn_socket()
        self.configure()
        super().__init__(**kwargs)

    def conn_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.ip_address, 1234))
        self.sock.settimeout(5)

    def configure(self):
        self.write('++mode 1')
        self.write('++auto 1')
        self.write('++addr ' + str(self.gpibAddr))

    def connection_check(self, op):
        assert op in ['read', 'write'], "'op' must be 'read' or 'write'"
        select_lists = ([self.com,], [], []) if op == 'read' else ([], [self.com,], [])
        try:
            ready_to_read, ready_to_write, in_error = \
                select.select(*select_lists, 5)
        except select.error:
            self.sock.shutdown(2)
            self.sock.close()
            print("Prologix interface connection error")
            self.disconnect_handler()
            self.connection_check(op)  # need to test on real hardware
            return
        if op == 'read':
            assert len(ready_to_read) > 0, "No sockets ready for reading"
        elif op == 'write':
            assert len(ready_to_write) > 0, "No sockets ready for writing"


    def write(self, msg):
        self.connection_check('write')
        message = msg + '\n'
        try:
            self.sock.sendall(message.encode())
        except socket.error as e:
            print(f"Socket write failed (disconnect?): {e}")
            self.disconnect_handler()
            # still write immediately after reconnect,
            # may not be desirable in certain use cases
            self.write(msg)
            return
        time.sleep(0.1)  # Don't send messages too quickly

    def read(self):
        self.connection_check('read')
        data = self.sock.recv(128)
        if not data:
            print("Received no data from socket (disconnect?)")
            self.disconnect_handler()
            # reading from socket immediately after reconnect
            # should timeout or give irrelevant data,
            # so raise exception and let caller handle it
            raise ConnectionResetError(
                "Recovered connection during read attempt -- this read cannot be satisfied"
            )
        return data.decode().strip()

    def disconnect_handler(self):
        for i in range(5):
            try:
                self.conn_socket()
                self.configure()
                print(f"Successfully reconnected on attempt #{i}")
                return
            except socket.error as e:
                print(f"Reconnect attempt #{i} failed with: {e}")
                time.sleep(1)
        assert False, "Could not reconnect"

    def version(self):
        self.write('++ver')
        return self.read()

    def identify(self):
        self.write('*idn?')
        return self.read()
