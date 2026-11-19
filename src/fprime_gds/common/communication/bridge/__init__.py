"""fprime_gds.common.communication.bridge: F Prime endpoint to UDP packet bridge

Implements `fprime-comm-bridge`, which connects an F Prime endpoint (reached through a
communication adapter plugin: TCP, UART, IP, ...) to a ground system exchanging packets as
UDP datagrams (YAMCS, OpenC3 COSMOS, ...). One framing plugin stage sits between the two.
"""

# Bridge defaults: a TCP server on the F Prime GDS port fed through the TM frame aggregator
DEFAULT_COMMUNICATION = "tcp-fast-server"
DEFAULT_FRAMING = "tm-frame-aggregator"
