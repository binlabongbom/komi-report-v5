from types import SimpleNamespace as NS
from services.reader_status import member_rows, newest_time


def test_member_roles_change_without_probing_and_connection_is_not_data(monkeypatch):
    from services import reader_status
    monkeypatch.setattr(reader_status, 'local_computer_name', lambda: 'VM103')
    monkeypatch.setattr(reader_status, 'latest_local_data', lambda p: '2026-09-23T09:00:00+07:00')
    owners = {0: 'LOCAL', 1: 'REMOTE'}
    states = [{'member': 'REMOTE', 'error': '', 'status': 'idle', 'last_success': '2026-09-23T09:10:00+07:00'}]
    def forbidden(*a, **kw):
        raise AssertionError('Display must not start a probe or elect a reader')
    election = NS(owner=lambda scope: owners[scope], select=forbidden, probe=forbidden)
    polling = NS(repository=NS(list=lambda **kw: [NS(slot=0,name='Office'), NS(slot=1,name='Sales')]),
        peer_network=NS(member_id='LOCAL',access=NS(members=lambda slot: ['LOCAL','REMOTE'])),
        peer_history=NS(snapshot=lambda: states),
        peer_network_runtime=NS(state='connected'),
        shared_reads=NS(router=NS(election=election),current_scope=lambda slot:slot,snapshot=lambda: []))
    evidence={'REMOTE':dict(name='VM105',data_at='2026-09-23T08:00:00+07:00',connected_at='')}
    rows=member_rows(polling,evidence)
    assert rows[0]['name']=='VM103 · คอมนี้'
    assert rows[0]['role']=='ผู้อ่านหลัก / ผู้รับข้อมูล'
    assert 'จาก VM105' in rows[0]['details']
    assert rows[1]['connected_at']=='2026-09-23T09:10:00+07:00'
    assert rows[1]['data_at']=='2026-09-23T08:00:00+07:00'
    owners[1]='LOCAL'
    rows=member_rows(polling,evidence)
    assert rows[0]['role']=='ผู้อ่านหลัก'
    assert rows[1]['role']=='ผู้รับข้อมูล'
    states[0]['error']='unreachable'
    assert member_rows(polling,evidence)[1]['role']=='รอตรวจสอบบทบาท'


def test_latest_time_uses_timestamp_not_connection_or_text_order():
    assert newest_time(['invalid',None,'2026-09-23T10:00:00+07:00','2026-09-23T04:00:00+00:00'])=='2026-09-23T04:00:00+00:00'
    assert newest_time([None,'invalid'])==''
