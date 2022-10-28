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
        select_lists = ([self.sock, ], [], []) if op == 'read' else ([], [self.sock, ], [])
        try:
            ready_to_read, ready_to_write, in_error = \
                select.select(*select_lists, 5)
        except select.error as e:
            # self.sock.shutdown(2)
            # self.sock.close()
            # print("Lakeshore372 connection error")
            # self.disconnect_handler()
            # self.connection_check(op)  # need to test on real hardware
            # return
            raise Exception("Triggered select.error block unexpectedly") from e
        if op == 'read' and not ready_to_read:
            self.disconnect_handler("No sockets ready for reading")
        elif op == 'write' and not ready_to_write:
            self.disconnect_handler("No sockets ready for writing")

    def write(self, msg):
        self.connection_check('write')
        message = msg + '\n'
        try:
            self.sock.sendall(message.encode())
        except socket.error as e:
            self.disconnect_handler(f"Socket write failed (disconnect?): {e}")
        time.sleep(0.1)  # Don't send messages too quickly

    def read(self):
        self.connection_check('read')
        data = self.sock.recv(128)
        if not data:
            self.disconnect_handler("Received no data from socket (disconnect?)")
        return data.decode().strip()

    def disconnect_handler(self, reset_reason):
        max_attempts = 500
        for i in range(max_attempts):
            try:
                self.conn_socket()
                self.configure()
                break
            except socket.error as e:
                print(f"Reconnect attempt #{i} failed with: {e}")
                if i == max_attempts - 1:
                    assert False, "Could not reconnect"
                time.sleep(1)
        print(f"Successfully reconnected on attempt #{i}")
        raise ConnectionResetError(reset_reason)  # should be caught by agent

    def version(self):
        self.write('++ver')
        return self.read()

    def identify(self):
        self.write('*idn?')
        return self.read()
