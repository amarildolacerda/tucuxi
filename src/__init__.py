"""Pacote principal do projeto Secur."""

import socket

# Force IPv4 globally: Raspberry Pi has broken IPv6 routing
# causing ConnectionResetError on api.telegram.org
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_getaddrinfo

from .main import main

__all__ = ["main"]
