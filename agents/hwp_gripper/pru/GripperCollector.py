import multiprocessing
import socket
import select
import errno

class GripperCollector(object):
    def __init__(self, pru_port):
        self._read_chunk_size = 2**20
        self.pru_port = pru_port

        self._s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._s.setblocking(False)
        self._s.bind(("", pru_port))

        self._data = b''
        self._timeout_sec = 1

        self.queue = multiprocessing.Queue()

    def relay_gripper_data(self):
        try:
            ready = select.select([self._s], [], [], self._timeout_sec)
            if ready[0]:
                self._data += self._s.recv(self._read_chunk_size)
        except socket.error as err:
            if err.errno != errno.EAGAIN:
                raise
            else:
                pass

        if len(self._data) > 0:
            self.queue.put(obj = self._data, block = True, timeout = None)
            self._data = b''
