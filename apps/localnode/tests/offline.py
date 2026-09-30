"""Fail on attempted public networking while leaving loopback/LAN usable."""
from contextlib import contextmanager
import ipaddress
import socket
from unittest.mock import patch


@contextmanager
def offline_network():
    attempts=[]
    original_dns,original_connect=socket.getaddrinfo,socket.socket.connect
    def allowed(host):
        if host in ('localhost','pos.bigparty.lan'): return True
        try:
            ip=ipaddress.ip_address(host)
            return ip.is_loopback or (ip.version==4 and any(ip in ipaddress.ip_network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')))
        except ValueError: return False
    def dns(host,*args,**kwargs):
        if not allowed(host):
            attempts.append(host);raise AssertionError('Unexpected external DNS')
        return original_dns(host,*args,**kwargs)
    def connect(sock,address):
        if isinstance(address,tuple) and not allowed(address[0]):
            attempts.append(address[0]);raise AssertionError('Unexpected external connection')
        return original_connect(sock,address)
    with patch('socket.getaddrinfo',dns),patch('socket.socket.connect',connect):yield attempts
