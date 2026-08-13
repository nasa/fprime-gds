import zmq
import threading
from queue import Queue

from fprime_gds.common.zmq_transport import ZmqWrapper


def test_zmq_client_waits_for_subscription_before_sending():
    server = ZmqWrapper()
    server.make_server()
    context = zmq.Context()
    probe = context.socket(zmq.PAIR)
    port = probe.bind_to_random_port("tcp://127.0.0.1")
    probe.close()
    incoming_port = port + 1
    transport_url = (
        f"tcp://127.0.0.1:{port}",
        f"tcp://127.0.0.1:{incoming_port}",
    )
    server.configure(transport_url, b"FSW", b"GUI")
    server.connect_outgoing()
    received = Queue()
    stop = threading.Event()
    connected = threading.Event()

    def receive():
        server.connect_incoming()
        connected.set()
        while not stop.is_set():
            message = server.recv(100)
            if message:
                received.put(message)

    receiver = threading.Thread(target=receive)
    receiver.start()
    connected.wait(1.0)

    try:
        for index in range(8):
            client = ZmqWrapper()
            client.configure(transport_url, b"GUI", b"FSW")
            client.connect_outgoing()
            try:
                assert client.wait_for_ready(1.0)
                client.send(str(index).encode())
            finally:
                client.disconnect_outgoing()
                client.terminate()

            assert received.get(timeout=1.0) == str(index).encode()
    finally:
        stop.set()
        receiver.join()
        server.disconnect_incoming()
        server.disconnect_outgoing()
        server.terminate()
        context.term()
