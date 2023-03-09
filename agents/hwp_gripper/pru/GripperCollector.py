import ctypes
import errno
import multiprocessing
import select
import signal
import socket
import time


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

        self._should_stop = multiprocessing.Value(ctypes.c_bool, False)
        self._stopped = multiprocessing.Value(ctypes.c_bool, False)

        self.queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=self.relay_gripper_data,
            args=(self._should_stop, self._stopped))
        self._process.start()

        signal.signal(signal.SIGINT, self.sigint_handler_parent)

    def sigint_handler_parent(self, signal, frame):
        self.stop()

    def sigint_handler_child(self, signal, frame):
        pass

    def relay_gripper_data(self, should_stop, stopped):
        signal.signal(signal.SIGINT, self.sigint_handler_child)

        while True:
            if should_stop.value:
                break

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
                self.queue.put(obj=self._data, block=True, timeout=None)
                self._data = b''

        with stopped.get_lock():
            stopped.value = True

    def stop(self):
        with self._should_stop.get_lock():
            self._should_stop.value = True

        while not self._stopped.value:
            time.sleep(0.001)
        self._process.terminate()
        self._process.join()
