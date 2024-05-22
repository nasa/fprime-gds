""" fprime_gds.common.zmq_transport:

A set of implementations based on ZeroMQ for data passing amongst components in the fprime_gds. ZeroMQ was chose to
replace the ThreadedTcpServer for several reasons as described below.

1. ZeroMQ is performant and can move 1GB/s/thread
2. ZeroMQ does not require a separate process and may be used w/o tcp sockets
3. ZeroMQ will not reorder packets at high data rates

@author lestarch
"""

import logging
import struct
from typing import Tuple

import zmq

from fprime_gds.common.communication.ground import GroundHandler
from fprime_gds.common.transport import (
    RoutingTag,
    ThreadedTransportClient,
    TransportationException,
)

LOGGER = logging.getLogger("transport")


class ZmqWrapper(object):
    """Handler for ZMQ functions for use in other objects"""

    def __init__(self):
        """Initialize the ZMQ setup"""
        super().__init__()
        self.context = zmq.Context()
        self.zmq_socket_incoming = None
        self.zmq_socket_outgoing = None
        self.pub_topic = None
        self.sub_topic = None
        self.transport_url = None
        self.server = False

    def configure(self, transport_url: Tuple[str], sub_topic: bytes, pub_topic: bytes):
        """Configure the ZeroMQ wrapper

        Configures the ZeroMQ wrapper, but notably does not connect it. This has been separated out because ZeroMQ
        sockets are expected to be created on their governing thread. As such, we just setup the information but defer
        the creation of the sockets until the threads exist.

        Args:
            transport_url: url of the ZeroMQ network to connect to
            sub_topic: subscription topic used to filter incoming messages
            pub_topic: publication topic supplied for remote subscription filters
        """
        assert (
            len(transport_url) == 2
        ), f"Must supply a pair of URLs for ZeroMQ not '{transport_url}'"
        self.pub_topic = pub_topic
        self.sub_topic = sub_topic
        self.transport_url = transport_url

    def make_server(self):
        """Makes this wrapper a server

        ZeroMQ needs at least one server for binding the network to real resources. However, it ZeroMQ doesn't really
        change functionality it provides to the caller. It just changes the call to connect/bind the connection to the
        network.
        """
        assert (
            self.pub_topic is None and self.sub_topic is None
        ), "Cannot make server after connect call"
        self.server = True

    def connect_outgoing(self):
        """Sets up a ZeroMQ connection for outgoing data

        ZeroMQ allows multiple connections to a single endpoint. However, there must be at least one bind client in the
        system. This will connect the ZeroMQ topology and if self.server is set, will bind the outgoing port rather than
        connect it such that this wrapper will act as a host. This only affects outgoing connections as sockets must be
        created on their owning threads.

        The connection is made using self.transport_url, and as such, this must be configured before running. This is
        intended to be called on the sending thread.
        """
        assert (
            self.transport_url is not None and len(self.transport_url) == 2
        ), "Must configure before connecting"
        assert (
            self.zmq_socket_outgoing is None
        ), "Cannot connect outgoing multiple times"
        assert self.pub_topic is not None, "Must configure sockets before connecting"
        self.zmq_socket_outgoing = self.context.socket(zmq.PUB)
        self.zmq_socket_outgoing.setsockopt(zmq.SNDHWM, 0)
        # When set to bind sockets, connect via a bind call
        if self.server:
            server_transport = self.transport_url[1].replace("localhost", "127.0.0.1")
            LOGGER.info("Outgoing binding to: %s", (server_transport))
            self.zmq_socket_outgoing.bind(server_transport)
        else:
            LOGGER.info("Outgoing connecting to: %s", (self.transport_url[0]))
            self.zmq_socket_outgoing.connect(self.transport_url[0])

    def connect_incoming(self):
        """Sets up a ZeroMQ connection for incoming data

        ZeroMQ allows multiple connections to a single endpoint. This only affects incoming connections as sockets must
        be created on their owning threads. This will connect the ZeroMQ topology and if self.server is set, will bind
        the incoming port rather than connect it such that this wrapper will act as a host.

        The connection is made using self.transport_url, and as such, this must be configured before running. This is
        intended to be called on the receiving thread.
        """
        assert (
            self.transport_url is not None and len(self.transport_url) == 2
        ), "Must configure before connecting"
        assert (
            self.zmq_socket_incoming is None
        ), "Cannot connect incoming multiple times"
        assert self.sub_topic is not None, "Must configure sockets before connecting"
        self.zmq_socket_incoming = self.context.socket(zmq.SUB)
        self.zmq_socket_incoming.setsockopt(zmq.RCVHWM, 0)
        self.zmq_socket_incoming.setsockopt(zmq.SUBSCRIBE, self.sub_topic)
        if self.server:
            server_transport = self.transport_url[0].replace("localhost", "127.0.0.1")
            LOGGER.info("Incoming binding to: %s", (server_transport))
            self.zmq_socket_incoming.bind(server_transport)
        else:
            LOGGER.info("Incoming connecting to: %s", (self.transport_url[1]))
            self.zmq_socket_incoming.connect(self.transport_url[1])

    def disconnect_outgoing(self):
        """Disconnect the ZeroMQ sockets"""
        if self.zmq_socket_outgoing is not None:
            self.zmq_socket_outgoing.close()

    def disconnect_incoming(self):
        """Disconnect the ZeroMQ sockets"""
        if self.zmq_socket_incoming is not None:
            self.zmq_socket_incoming.close()

    def terminate(self):
        """Terminate the ZeroMQ context"""
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
        self,
        transport_url: Tuple[str],
        sub_routing: RoutingTag,
        pub_routing: RoutingTag,
    ):
        """Connects to the ZeroMQ network"""
        self.zmq.configure(transport_url, sub_routing.value, pub_routing.value)
        self.zmq.connect_outgoing()  # Outgoing socket, for clients, exists on the current thread
        super().connect(transport_url, sub_routing, pub_routing)

    def disconnect(self):
        """Disconnects from ZeroMQ network"""
        self.zmq.disconnect_outgoing()  # Outgoing is on the current thread
        super().disconnect()

    def send(self, data):
        """Send data via ZeroMQ"""
        if data[:4] == b"ZZZZ":
            data = data[4:]
        self.zmq.send(
            data
        )  # Must strip out ZZZZ as that is a ThreadedTcpServer only property

    def recv(self, timeout=None):
        """Receives data from ZeroMQ"""
        return self.zmq.recv(timeout)

    def recv_thread(self):
        """Overrides the recv_thread method

        Overrides the recv_thread method of the superclass such that the ZeroMQ socket may be created/destroyed
        before/after the main recv loop.
        """
        self.zmq.connect_incoming()
        super().recv_thread()  # Contains a while <event> loop, will only return at end of program
        self.zmq.disconnect_incoming()
        self.zmq.terminate()  # Everything should be shutdown and safe to terminate the context


class ZmqGround(GroundHandler):
    """Ground handler implementation for using ZeroMQ as the transport

    This ground handler is built upon the ZmqWrapper subclass an uses zero mq to send data from the communications layer
    to the display and processing layer(s). This effectively acts as the "FSW" side of that interface as it
    frames/deframes packets heading to that layer.

    Since there is likely only one communications client to the FSW users should instantiate with server=True
    to ensure that it binds to resources for the network. This is not forced in case of multiple FSW connections.
    """

    def __init__(self, transport_url, server=True):
        """Initialize this interface with the transport_url needed to connect

        Args:
            transport_url: transport url passed into the zeromq connection
        """
        super().__init__()
        self.zmq = ZmqWrapper()
        self.transport_url = transport_url
        self.timeout = 10
        if server:
            self.zmq.make_server()

    def open(self):
        """Open this ground interface. Delegates to the connect method

        Opens any needed resources and prepares the system for receiving and sending. This means opening the ZeroMQ
        network and setting up routing to incoming as FSW and outgoing to GUI.

        Returns:
            True on successful connection, False on error
        """
        try:
            self.zmq.configure(
                self.transport_url, RoutingTag.FSW.value, RoutingTag.GUI.value
            )
        except TransportationException:
            return False
        return True

    def close(self):
        """Closes the open adapter"""
        # Don't know what else to do, the governing threads are dead, so attempt to close?
        self.zmq.disconnect_incoming()
        self.zmq.disconnect_outgoing()
        self.zmq.terminate()

    def receive_all(self):
        """Receive all available packets

        Receive all packet available from the ground layer. This will return full ground packets up to the uplinker.
        These packets should be fully-deframed and ready for reframing in the comm-layer specified format. With ZeroMQ
        handling whole messages, there is never any outstanding data.

        Returns:
            list deframed packets, outstanding data (always b"")
        """
        if self.zmq.zmq_socket_incoming is None:
            self.zmq.connect_incoming()
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
        if self.zmq.zmq_socket_outgoing is None:
            self.zmq.connect_outgoing()
        for packet in frames:
            # TODO: we need to fix where this is being pulled off, should be done in the framing protocol for uplink
            size_bytes = struct.pack(
                ">I", len(packet)
            )  # Add in size bytes as it was stripped in the downlink protocol
            self.zmq.send(size_bytes + packet)
