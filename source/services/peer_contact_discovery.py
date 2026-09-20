"""Recover known peer addresses at startup/reconnect without granting access.

The ordinary UDP hint leads to a public signed contact on the local report Web
server. Its unverified discovery TLS response cannot authorize any data RPC:
the previously enrolled identity, group HMAC, signature and generation must all
verify first. Subsequent data traffic uses the pinned mutual-TLS transport.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing
import json
import http.client
import sqlite3
from time import monotonic
from urllib.parse import urlsplit

from services.peer_membership import PeerMembership, _hex, _unbase


def public_contact(path):
    # Read the current public packet only: no vault access, key generation,
    # enrollment or group capability is performed by the Web process.
    with closing(sqlite3.connect(path)) as conn:
        group = conn.execute('SELECT document FROM lan_peer_group WHERE singleton=1').fetchone()
        identity = conn.execute("SELECT value FROM settings WHERE key='installation_id'").fetchone()
        if not group or not identity:
            return None
        group = json.loads(group[0])
        if group.get('local_installation_id') != identity[0]:
            return None
        row = conn.execute('SELECT document FROM lan_peer_members WHERE member_id=? AND revoked=0', identity).fetchone()
    if not row:
        return None
    packet = json.loads(row[0])
    if set(packet) != {'document', 'signature', 'proof'}:
        raise ValueError('Invalid public contact')
    document = packet['document']
    PeerMembership._validate_contact(document)
    _unbase(packet['signature'], 64)
    _hex(packet['proof'])
    if (document['member_id'], document['group_id']) != (identity[0], group['group_id']):
        raise ValueError('Public contact differs from local enrollment')
    return packet


def fetch_contact(host, port):
    import socket
    from threading import Timer
    import ipaddress
    from services.secondary_setup import SecondaryPeerClient
    from services.web_port import validate_web_port
    address = ipaddress.IPv4Address(host)
    if address.is_multicast or address.is_unspecified:
        raise ValueError('Invalid contact address')
    conn = http.client.HTTPSConnection(str(address), validate_web_port(port),
        context=SecondaryPeerClient._context(), timeout=.8)
    transport = None
    def expire():
        # A peer sending one byte before each socket timeout must not prevent
        # ownership handoff or Agent shutdown forever, including HTTP headers.
        if transport is not None:
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    timer = Timer(2, expire)
    timer.daemon = True
    try:
        conn.connect()
        transport = conn.sock
        timer.start()
        conn.request('GET', '/api/v1/peer/contact', headers={'Connection': 'close'})
        response = conn.getresponse()
        if response.status != 200:
            return None
        raw = response.read(32769)
        if len(raw) > 32768:
            raise ValueError('Oversized peer contact')
        return json.loads(raw)
    finally:
        timer.cancel()
        conn.close()


def refresh_known_contacts(access, interfaces, *, cancelled=lambda: False, discover=None, fetch=fetch_contact):
    from services.lan_discovery import discover as discover_lan
    known = {p['document']['member_id'] for p in access.contacts()} - {access.member_id}
    if not known or not interfaces or cancelled():
        return 0
    try:
        targets = (discover or discover_lan)(interfaces)
    except OSError:
        return 0  # Blocked UDP leaves the already pinned direct addresses usable.
    changed = 0
    deadline = monotonic() + 8
    # Only eight short discovery probes at a time; no full subnet HTTP scan.
    pending, remaining = {}, iter(targets)
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix='komi-peer-address') as pool:
        def fill():
            while len(pending) < 8 and not cancelled() and monotonic() < deadline:
                item = next(remaining, None)
                if item is None:
                    break
                host, port = item
                pending[pool.submit(fetch, host, port)] = host
        fill()
        while pending and not cancelled() and monotonic() < deadline:
            done, _ = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
            for future in done:
                host = pending.pop(future)
                try:
                    packet = future.result()
                    if not packet or cancelled():
                        continue
                    document = packet['document']
                    if document['member_id'] not in known or urlsplit(document['url']).hostname != host:
                        continue
                    access.accept_contact(packet)
                    changed += 1
                except (OSError, ValueError, KeyError, TypeError, PermissionError, sqlite3.Error, http.client.HTTPException):
                    continue  # A hint cannot change trust when its proof fails.
            fill()
        for future in pending:
            future.cancel()
    return changed
