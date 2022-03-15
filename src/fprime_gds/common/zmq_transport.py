""" fprime_gds.common.zmq_transport:

A set of implementations based on ZeroMQ for data passing amongst components in the fprime_gds. ZeroMQ was chose to
replace the ThreadedTcpServer for several reasons as described below.

1. ZeroMQ is performant and can move 1GB/s/thread
2. ZeroMQ does not require a separate process and may be used w/o tcp sockets
3. ZeroMQ will not reorder packets at high data rates

@author lestarch
"""
import struct
import zmq

from fprime_gds.common.communication.ground import GroundHandler
from fprime_gds.common.transport import (
    RoutingTag,
    ThreadedTransportClient,
    TransportationException,
)


class ZmqWrapper(object):
    """Handler for ZMQ functions for use in other objects"""

    def __init__(self):
        """Initialize the ZMQ setup"""
        super().__init__()
        self.context = zmq.Context()
        self.transport_url = None
        self.zmq_socket_incoming = self.context.socket(zmq.SUB)
        self.zmq_socket_outgoing = self.context.socket(zmq.PUB)
        self.pub_topic = None
        self.sub_topic = None
        self.bound = False

    def configure(self, sub_topic: bytes, pub_topic: bytes):
        """Configure this setup"""
        self.zmq_socket_incoming.setsockopt(zmq.SUBSCRIBE, sub_topic)
        self.zmq_socket_incoming.setsockopt(zmq.RCVHWM, 0)
        self.zmq_socket_incoming.setsockopt(zmq.SNDHWM, 0)
        self.pub_topic = pub_topic
        self.sub_topic = sub_topic

    def make_server(self):
        """Makes this wrapper a server

        ZeroMQ needs at least one server for binding the network to real resources. However, it ZeroMQ doesn't really
        change functionality it provides to the caller. It just changes the call to connect/bind the connection to the
        network.
        """
        assert (
            self.pub_topic is None and self.sub_topic is None
        ), "Cannot make server after connect call"
        self.bound = True

    def connect(self, transport_url: str, sub_routing: bytes, pub_routing: bytes):
        """Sets up a ZeroMQ connection

        ZeroMQ allows multiple connections to a single endpoint. However, there must be at least one bind client in the
        system. This will connect the ZeroMQ topology and if server is set, will bind the outgoing port rather than
        connect it such that this wrapper will act as a host.

        Args:
            transport_url: transportation URL for use with communication
            sub_routing: routing tag dictating the subscription topic
            pub_routing: routing tag dictating the publishing topic
        """
        assert (
            self.pub_topic is None and self.sub_topic is None
        ), "Cannot connect multiple times"
        self.configure(sub_routing, pub_routing)
        self.transport_url = transport_url
        if self.bound:
            self.zmq_socket_outgoing.bind(
                self.transport_url.replace("localhost", "*") + "1"
            )
            self.zmq_socket_incoming.bind(
                self.transport_url.replace("localhost", "*") + "0"
            )
        else:
            self.zmq_socket_outgoing.connect(self.transport_url + "0")
            self.zmq_socket_incoming.connect(self.transport_url + "1")

    def disconnect(self):
        """Disconnect the ZeroMQ sockets"""
        self.zmq_socket_outgoing.close()
        self.zmq_socket_incoming.close()
        self.context.term()

    def recv(self, timeout=None):
        """Receive single packet from ZMQ"""
        try:
            self.zmq_socket_incoming.setsockopt(
                zmq.RCVTIMEO, timeout if timeout is not None else -1
            )
            message = self.zmq_socket_incoming.recv()[len(self.sub_topic) :]
        except zmq.Again:
            return b""
        return message

    def send(self, data):
        """Send single message through ZMQ"""
        message_out = self.pub_topic + data
        return self.zmq_socket_outgoing.send(message_out)


class ZmqClient(ThreadedTransportClient):
    """ZeroMQ client to the transport layer

    This client will connect into a ZeroMQ network to act as a data client. Unless the make_server() is called, this
    client will only connect to existing resource and not bind those resources. It uses ThreadedTransportClient to read
    data from the network as part of a thread.

    Note: implementation delegates to a zmq wrapper
    """

    def __init__(self):
        """Create ZMQ wrapper"""
        super().__init__()
        self.zmq = ZmqWrapper()

    def connect(
        self, transport_url: str, sub_routing: RoutingTag, pub_routing: RoutingTag
    ):
        """Connects to the ZeroMQ network"""
        self.zmq.connect(transport_url, sub_routing.value, pub_routing.value)
        super().connect(transport_url, sub_routing, pub_routing)

    def disconnect(self):
        """Disconnects from ZeroMQ network"""
        super().disconnect()
        self.zmq.disconnect()

    def send(self, data):
        """Send data via ZeroMQ"""
        if data[0:4] == b'ZZZZ':
            data = data[4:]
        self.zmq.send(data)  # Must strip out ZZZZ as that is a ThreadedTcpServer only property

    def recv(self, timeout=None):
        """Receives data from ZeroMQ"""
        return self.zmq.recv(timeout)


class ZmqGround(GroundHandler):
    """Ground handler implementation for using ZeroMQ as the transport

    This ground handler is built upon the ZmqWrapper subclass an uses zero mq to send data from the communications layer
    to the display and processing layer(s). This effectively acts as the "FSW" side of that interface as it
    frames/deframes packets heading to that layer.

    Since there is likely only one communications client to the FSW users should call make_server() after construction
    to ensure that it binds to resources for the network. This is not forced in case of multipl FSW connections.
    """

    def __init__(self, transport_url):
        """Initialize this interface with the transport_url needed to connect

        Args:
            transport_url: transport url passed into the zeromq connection
        """
        super().__init__()
        self.zmq = ZmqWrapper()
        self.transport_url = transport_url
        self.timeout = 10

    def open(self):
        """Open this ground interface. Delegates to the connect method

        Opens any needed resources and prepares the system for receiving and sending. This means opening the ZeroMQ
        network and setting up routing to incoming as FSW and outgoing to GUI.

        Returns:
            True on successful connection, False on error
        """
        try:
            self.zmq.connect(
                self.transport_url, RoutingTag.FSW.value, RoutingTag.GUI.value
            )
        except TransportationException:
            return False
        return True

    def close(self):
        """Closes the open adapter"""
        self.zmq.disconnect()

    def make_server(self):
        """Makes it into a server"""
        self.zmq.make_server()

    def receive_all(self):
        """Receive all available packets

        Receive all packet available from the ground layer. This will return full ground packets up to the uplinker.
        These packets should be fully-deframed and ready for reframing in the comm-layer specified format. With ZeroMQ
        handling whole messages, there is never any outstanding data.

        Returns:
            list deframed packets, outstanding data (always b"")
        """
        messages = []
        data = None
        while data != b"":
            data = self.zmq.recv(timeout=self.timeout)
            if data != b"":
                # TODO: we need to fix where this is being pulled off, should be done in the framing protocol for uplink
                data = data[
                    4:
                ]  # Strip off the size as this will be re-added by the framing protocol
                messages.append(data)
        return messages

    def send_all(self, frames):
        """Send all the data frames to GUI

        Sends all available frames across the system to the waiting GDS layer. No extra wrapping is performed as ZeroMQ
        handles its own on-wire framing setup.

        Args:
            frames: list of bytes messages to send out
        """
        for packet in frames:
            # TODO: we need to fix where this is being pulled off, should be done in the framing protocol for uplink
            size_bytes = struct.pack(
                ">I", len(packet)
            )  # Add in size bytes as it was stripped in the downlink protocol
            self.zmq.send(size_bytes + packet)
