import socket
import errno
import select

class GripperClient(object):
    def __init__(self, ip, send_port, recv_port):
        self.ip = ip
        self.send_port = send_port
        self.recv_port = recv_port
        self.data = b''

        self._s_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._s_send.setblocking(False)

        self._s_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._s_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._s_recv.setblocking(False)

        self._s_recv.bind(('', self.recv_port))

    def send_data(self, data):
        self._s_send.sendto(bytes(data, 'utf-8'), (self.ip, self.send_port))

    def listen(self, timeout = 0.01):
        try:
            ready = select.select([self._s_recv], [], [], timeout)
            if ready[0]:
                self.data = self._s_recv.recv(1024)
        except socket.error as err:
            if err.errno != errno.EAGAIN:
                raise
            else:
                pass

        if len(self.data) > 0:
            return_data =  self.data
            self.data = b''
            return return_data
        else:
            return b''

    def __exit__(self):
        self._s_send.close()
        self._s_recv.close()

