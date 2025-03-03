"""
fprime_gds.common.transport:

Sets up the classes used to transport data within the GDS system between the few executables that compose the GDS. This
file defines several base classes used to specify what a client looks like and it defines a basic implementation:
ThreadedTCPSocketClient used to send data through the threaded tcp server.

@author lestarch
"""
import select
import socket
import threading
from abc import ABC, abstractmethod
from enum import Enum

from fprime_gds.common.handlers import DataHandler, HandlerRegistrar


class RoutingTag(Enum):
    """Tag for routing data about the system"""

    GUI = b"GUI"
    FSW = b"FSW"


class TransportationException(Exception):
    pass


class TransportClient(DataHandler, HandlerRegistrar, ABC):
    """Transport client used as an interface for handling transportation within the GDS

    The GDS is composed of multiple parts: communications talking to the embedded software, the GUI displaying
    information to a user, etc. Between these various executables and functions there needs to be data transportation.
    This class acts as an interface for various implementations that shuttle that data about the GDS.

    This has two important parents: DataHandler and HandlerRegistrar. The DataHandler allows this to be registered to
    anything that produces data making sending data out of this client east. The HandlerRegistrar allows this to pass
    incoming data to various handlers easy.
    """

    @abstractmethod
    def connect(
        self,
        connection_uri,
        incoming_routing=RoutingTag.GUI,
        outgoing_routing=RoutingTag.FSW,
    ):
        """Connect to this client given the connection URI

        For clients that can handle a URI directly this should be consumed as-is. For clients expecting a host/port this
        should be split on ':' to break apart the URI. The connection needs to specify routing (e.g. FSW, GUI) for both
        incoming data and outgoing data. Since this is a client it defaults to the incoming GUI tag, and outgoing FSW
        tag.  It is up to the client to use this information.

        Args:
            connection_uri: connection URI for setting up this client
            incoming_routing: routing tag for the incoming (received) data
            outgoing_routing: routing tag for the outgoing (sent) data
        """

    @abstractmethod
    def disconnect(self):
        """Disconnects from this client ensuring all resources deallocated"""

    @abstractmethod
    def send(self, data):
        """Send the supplied data out of this client

        Sends the supplied data out of this client. This data is not specifically formatted. It is expected that the
        data is a set of bytes to send. This is send method is typically triggered by the data_callback method and will
        send any data received by that call. Send is not governed by a timeout and will block until the send succeeds.

        Args:
            data {bytes}: data to send out this client
        """

    @abstractmethod
    def recv(self, timeout=None):
        """Receive data from the interface and return it

        Receives the data from the client and returns it out of the interface. The client implementation is not expected
        to return complete messages. It may or may not do so and the calling function should expect misc bytes returned.
        Recv is governed by a timeout such that it does not hand forever.

        Args:
            timeout {int}: timeout in milliseconds before returning b""
        Returns:
             byte data read from interface. b"" on timeout.
        """

    def data_callback(self, data, sender=None):
        """Calls send to send received data"""
        assert isinstance(
            data, (bytes, bytearray)
        ), "Client cannot handle non-binary data callbacks"
        self.send(data)


class ThreadedTransportClient(TransportClient, ABC):
    """Transportation client that uses a thread to receive and dispatch calls through registrants

    This client will setup a thread and use this thread to call recv to receive data and then forward that data to all
    registrants. The thread is created at connection time and will stop after disconnect is called. Subclasses should
    call connect here after the connection is setup and should call disconnect (typically) before the connection is
    destroyed although it is understood that the threads will join before disconnect is complete.
    """

    def __init__(self, timeout=100):
        """Sets up the stop event and thread object

        Args:
            timeout: read timeout supplied to the recv call within the thread. Sets shutdown time.
        """
        super().__init__()
        self.__data_recv_thread = threading.Thread(target=self.recv_thread, name="TTSReceiverThread")
        self.__stop_event = threading.Event()
        self.timeout = timeout
        self.started = False

    def connect(self, *_, **__):
        """Starts up the recv thread when connected

        Upon connection this client starts up the receive thread. Subclasses should call super().connect(...) after the
        connection has been created as it will immediately start reading data. All arguments are ignored.
        """
        super().connect(*_, **__)
        if not self.__stop_event.is_set():
            self.started = True
            self.__data_recv_thread.start()

    def disconnect(self):
        """Stops and joins to thee recv thread when disconnected

        Upon disconnection this client will stop the thread and then join to it. The maximum time to join should be
        ~self.timeout. Subclasses should call super().disconnect(...) before the connection is closed as the thread will
        read data until it is stopped.
        """
        super().disconnect()
        self.__stop_event.set()
        if self.started:
            self.__data_recv_thread.join()

    def stop(self):
        """ Stop the receive thread without waiting """
        self.__stop_event.set()

    def poll(self):
        """ Poll the receive and process the result

        Poll the receive and process the results. This will be called by the receive thread, but is separated out for
        flexibility in case users wish to reduce the number of empty threads in the system.
        """
        data = self.recv(self.timeout)
        if len(data) > 0:
            self.send_to_all(data)

    def recv_thread(self):
        """Loops reading data and dispatching it to registrants

        Reads data while supplying timeout on a thread. After each read the thread is checked to shutdown and as such
        the timeout is roughly the maximum time the thread may take to shutdown after the shutdown event is issued. The
        data is only forwarded to registrants if the data is not empty as that indicates a timeout.
        """
        while not self.__stop_event.is_set():
            self.poll()


class ThreadedTCPSocketClient(ThreadedTransportClient):
    """
    Threaded TCP client that connects to the socket server that serves packets from the flight software. The threaded
    tcp server acts as the original middleware layer for transporting data. This client is designed specifically to
    source incoming data from that server and send outgoing data to that server.
    """

    def __init__(self, sock=None):
        """
        Threaded client socket constructor

        Keyword Arguments:
            sock {Socket} -- A socket for the client to use. Created own if None (default: {None})
        """
        super().__init__()
        self.dest = None
        self.chunk_size = 1024
        if sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        else:
            self.sock = sock

    def connect(
        self,
        connection_uri,
        incoming_routing=RoutingTag.GUI,
        outgoing_routing=RoutingTag.FSW,
    ):
        """Connect to host at given port and start the threaded recv method

        Connects to a running ThreadedTcpServer at the given connection_uri expected in the format tcp://host:port or
        simply host: port. This will also register with the ThreadedTcpServer using the incoming

        Arguments:
            connection_uri {string} -- connection uri of the form (tcp://)?host:port
            incoming_routing {RoutingTag}: routing tag for incoming data, used to register client to server
            outgoing_routing {RoutingTag}: routing tog applied to outgoing data when sent
        """
        try:
            self.dest = outgoing_routing.value
            connection_uri = connection_uri.split("//", 1)[-1]  # Remove leading tcp
            host, port = connection_uri.split(":", 1)
            port = int(port)

            self.sock.connect((host, port))
            self.sock.send(b"Register %s\n" % incoming_routing.value)
            super().connect(connection_uri, incoming_routing, outgoing_routing)
        except ValueError as vle:
            msg = f"Failed to parse connection uri: {connection_uri}. {vle}"
            raise TransportationException(
                msg
            )
        except Exception as exc:
            msg = f"Failed to connect to transportation layer at: {connection_uri}. {exc}"
            raise TransportationException(
                msg
            )

    def disconnect(self):
        """Disconnect the socket client"""
        super().disconnect()
        self.sock.close()

    def send(self, data):
        """Send data to the server

        Sends data out to the destination via the threaded tcp server. All necessary headers are added in this function
        such that the sever can process this send.

        Arguments:
            data {binary} -- the data to send (What you want the destination to receive)
        """
        assert self.dest is not None, "Cannot send data before connect call"
        self.sock.send(b"A5A5 %s %s" % (self.dest, data))

    def recv(self, timeout=0.1):
        """Receives data from the threaded tcp server

        Receives raw data from the threaded tcp server. This data is expected to have no headers and will be passed as
        received or in chunks back to the caller.

        Args:
            timeout {int}: timeout to wait for the socket to have data before returning b"". Default: 100ms.
        """
        assert self.dest is not None, "Cannot recv data before connect call"
        ready = select.select([self.sock], [], [], timeout)
        return self.sock.recv(self.chunk_size) if ready[0] else b""
