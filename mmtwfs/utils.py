# Licensed under GPL3
# coding=utf-8

"""
Misc. utility routines
"""

import dns.resolver as resolver


def srvlookup(server):
    """
    Perform a SRV lookup of 'server' and return its hostname and port.
    """
    try:
        response = resolver.query(server, 'SRV')
        host = response[0].target.to_text()
        port = response[0].port
    except Exception as e:
        # we'll be lenient and just return None if there's an issue
        host = None
        port = None

    return host, port