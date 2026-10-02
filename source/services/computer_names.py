"""Display-only names from accepted contacts; never use names for authorization."""
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
from urllib.parse import urlsplit

from cryptography import x509


def local_computer_name():
    return socket.gethostname()


def computer_directory(conn):
    """The signed v1 contact already carries the generated certificate's hostname.

    Reading its SAN keeps interoperability with installed v1 peers. Do not use
    reverse DNS, localhost, ambiguous SANs, or the certificate CN (often localhost).
    Retain removed contacts for historical attribution, not access decisions.
    """
    records = []
    for member, origin, packet in conn.execute('SELECT member_id,origin,document FROM lan_peer_members'):
        name = address = ''
        try:
            document = json.loads(packet)['document']
            address = urlsplit(document['url']).hostname or ''
            cert = x509.load_pem_x509_certificate(document['certificate'].encode())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            names = {n for n in san.get_values_for_type(x509.DNSName)
                     if n.lower() != 'localhost' and '*' not in n and len(n) <= 253
                     and all(c.isalnum() or c in '.-_' for c in n)}
            if len(names) == 1:
                name = next(iter(names))
        except (KeyError, TypeError, ValueError, x509.ExtensionNotFound):
            pass
        records.append((member, origin, name, address))
    counts = Counter(name.casefold() for _, _, name, _ in records if name)
    members, origins = {}, {}
    for member, origin, name, address in records:
        label = name or address or member
        if name and counts[name.casefold()] > 1:
            label += f' ({address or member})'
        members[member] = label
        origins[origin] = label
    return {'members': members, 'origins': origins}


def snapshot_readers(path, snapshots):
    """Attribute the exact displayed observation, never the relay or newest job."""
    result = {}
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as conn:
            conn.execute('BEGIN')
            names = computer_directory(conn)['origins']
            local = conn.execute("SELECT value FROM web_observation_state WHERE key='origin'").fetchone()
            if local:
                names[local[0]] = local_computer_name()
            for slot, snapshot in snapshots.items():
                if snapshot is None or not snapshot.event_id:
                    continue
                row = conn.execute('SELECT origin_id,observed_at FROM web_observations '
                    'WHERE event_id=? AND device_slot=? AND device_serial=?',
                    (snapshot.event_id, slot, snapshot.serial)).fetchone()
                if row:
                    result[slot] = {'name': names.get(row[0], row[0]), 'at': row[1], 'origin': row[0]}
    except (sqlite3.Error, OSError):
        pass  # Missing provenance stays unknown; no implicit attribution to this PC.
    return result
