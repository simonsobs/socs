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

    def connection_check(self):
        try:
            ready_to_read, ready_to_write, in_error = \
                select.select([self.sock,], [self.sock,], [], 5)
        except select.error:
            self.sock.shutdown(2)    # 0 = done receiving, 1 = done sending, 2 = both
            self.sock.close()
            # connection error event here, maybe reconnect
            print('prologix interface connection error')
        return ready_to_read, ready_to_write

    def connection_check_read(self):
        ready_to_read, _ = self.connection_check()
        assert len(ready_to_read) > 0

    def connection_check_write(self):
        _, ready_to_write = self.connection_check()
        assert len(ready_to_write) > 0

    def write(self, msg):
        self.connection_check_write()
        message = msg + '\n'
        self.sock.sendall(message.encode())
        time.sleep(0.1)  # Don't send messages too quickly

    def read(self):
        self.connection_check_read()
        return self.sock.recv(128).decode().strip()

    def version(self):
        self.write('++ver')
        return self.read()

    def identify(self):
        self.write('*idn?')
        return self.read()
