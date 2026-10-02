from services.peer_network import PeerNetworkNode
from services.peer_transport_factory import PeerTransportFactory
from test_peer_membership import member


def test_production_tls_factory_uses_individual_pinned_leaf_certificates(tmp_path):
    a, b = member(tmp_path, 'A'), member(tmp_path, 'B')
    a.initialize_primary('Synthetic company')
    b.accept_invitation(a.invitation(), company='Synthetic company', primary_id='A')
    peers = {'A': a, 'B': b}
    factories = {name: PeerTransportFactory(peer, runtime_root=tmp_path / 'runtime',
        hostname='fixture-' + name.lower(), lan_ips=['127.0.0.1']) for name, peer in peers.items()}
    nodes = {name: PeerNetworkNode(access=peer, client_for=factories[name].client, ready=lambda slot: False)
             for name, peer in peers.items()}
    contexts = {name: factories[name].context(server=True) for name in nodes}
    try:
        for name, node in nodes.items():
            address = node.start(('127.0.0.1', 0), context=contexts[name])
            packet = factories[name].own_contact(host='127.0.0.1', port=address[1])
            for peer in peers.values():
                peer.accept_contact(packet)
        for name, factory in factories.items():
            factory.refresh_server_trust(contexts[name])
        # No fixture CA, permissive certificate resolver or OS trust change.
        result = factories['A'].client('B').manifest()
        assert result['through'] == 0
        assert nodes['A'].session('B').run().status == 'complete'
    finally:
        for node in nodes.values():
            node.stop(wait=True)
