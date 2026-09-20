from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database import (
    _open,
    factory_reset_v5,
    get_db_path,
    reset_usage_data,
)
from services.installation_identity import installation_private_key_reference
from services.registration_vault import (
    SessionRegistrationSecretStore,
    installation_token_reference,
)

STAMP = "2026-08-31T09:00:00+07:00"


def _seed_reset_state() -> dict[str, object]:
    with _open() as connection:
        connection.execute('INSERT INTO peer_billing_amendments(amendment_id,document_json,results_json,created_at) VALUES(?,?,?,?)',
                           ('fixture-amendment', '{}', '[]', STAMP))
        connection.execute('INSERT INTO peer_billing_deliveries(member_id,amendment_id) VALUES(?,?)',
                           ('fixture-member', 'fixture-amendment'))
        connection.execute(
            """INSERT INTO devices(
                   slot,name,host,username,password,enabled,model,serial,updated_at
               ) VALUES(0,'Office','192.0.2.10','administrator','',1,
                        'bizhub C450i','SERIAL-RESET',?)""",
            (STAMP,),
        )
        reading_id = connection.execute(
            """INSERT INTO readings(
                   slot,machine_name,serial,read_date,read_date_iso,billing_month,
                   mode,data_json,imported_at,file_name,parser_name
               ) VALUES(0,'Office','SERIAL-RESET','2026-08-31','2026-08-31',
                        '2026-08','import','{}',?,'sample.txt','legacy')""",
            (STAMP,),
        ).lastrowid
        connection.execute(
            "INSERT INTO price_snapshot(reading_id,price_json,saved_at) VALUES(?,?,?)",
            (reading_id, "{}", STAMP),
        )
        connection.execute(
            """INSERT INTO config_log(config_key,old_value,new_value,changed_at)
               VALUES('billing_day','25','31',?)""",
            (STAMP,),
        )
        import_id = connection.execute(
            """INSERT INTO legacy_history_imports(
                   source_file_name,source_sha256,source_schema_version,date_min,date_max,
                   total_rows,imported_rows,duplicate_rows,rejected_rows,imported_at
               ) VALUES('legacy.db','hash',46,'2026-08-31','2026-08-31',1,1,0,0,?)""",
            (STAMP,),
        ).lastrowid
        connection.execute(
            """INSERT INTO legacy_history_items(
                   import_id,reading_id,source_row_id,row_fingerprint
               ) VALUES(?,?,?,?)""",
            (import_id, reading_id, "row-1", "fingerprint-1"),
        )
        daily_id = connection.execute(
            """INSERT INTO daily_meter_records(
                   device_slot,record_date,opening_json,closing_json,delta_json,
                   category_json,source_json,first_success,last_success,
                   sample_count,error_count,incomplete,created_at
               ) VALUES(0,'2026-08-31','{}','{}','{}','{}','{}',?,?,1,0,0,?)""",
            (STAMP, STAMP, STAMP),
        ).lastrowid
        connection.execute(
            """INSERT INTO daily_subject_records(
                   device_slot,record_date,subject_type,subject_id,subject_name,
                   opening_total,closing_total,delta_total,sample_count,
                   first_success,last_success,warnings_json,source_json,created_at
               ) VALUES(0,'2026-08-31','user','u-1','alice',10,12,2,1,?,?,
                        '[]','{}',?)""",
            (STAMP, STAMP, STAMP),
        )
        connection.execute(
            """INSERT INTO daily_raw_counter_records(
                   device_slot,record_date,canonical_field,label,source_path,
                   opening_value,closing_value,delta_value,sample_count,
                   first_success,last_success,source_name,device_name_snapshot,
                   device_serial_snapshot,created_at,updated_at
               ) VALUES(0,'2026-08-31','paper.a5','A5','/counter.xml',10,12,2,1,
                        ?,?,'legacy_xml','Office','SERIAL-RESET',?,?)""",
            (STAMP, STAMP, STAMP, STAMP),
        )
        connection.execute(
            """INSERT INTO billing_ledger(
                   entry_kind,device_slot,device_identity,device_name_snapshot,
                   device_serial_snapshot,record_date,period_start,period_end,
                   source_daily_record_id,source_hash,idempotency_key,delta_json,
                   category_json,price_cents_json,gross_cents,waste_basis_points,
                   net_cents,billing_day,attestation_json,created_at
               ) VALUES('posting',0,'SERIAL-RESET','Office','SERIAL-RESET',
                        '2026-08-31','2026-08-01','2026-08-31',?,
                        'source-hash','billing-key','{}','{}','{}',100,200,98,31,
                        '{}',?)""",
            (daily_id, STAMP),
        )
        connection.execute(
            """INSERT INTO price_history(
                   device_slot,effective_date,a3_color,a3_bw,a4_color,a4_bw,created_at
               ) VALUES(0,'2026-08-31',2,0.2,2,0.2,?)""",
            (STAMP,),
        )
        connection.execute(
            """INSERT INTO cost_category_history(
                   device_slot,raw_key,effective_date,category,created_at
               ) VALUES(0,'paper.a5','2026-08-31','other',?)""",
            (STAMP,),
        )
        connection.execute(
            """INSERT INTO parser_mapping_overrides(
                   device_serial,raw_key,source_field,source_path,target_field,updated_at
               ) VALUES('SERIAL-RESET','raw-key','paper.a5','/counter.xml',
                        'mapped.print.a4.color',?)""",
            (STAMP,),
        )
        connection.execute(
            """INSERT INTO parser_mapping_change_log(
                   device_serial,raw_key,old_target,new_target,changed_at
               ) VALUES('SERIAL-RESET','raw-key','','mapped.print.a4.color',?)""",
            (STAMP,),
        )
        connection.execute(
            """INSERT INTO registration_profile(
                   singleton_id,installation_id,company_name,client_first_started_at,
                   token_ref,status,updated_at
               ) VALUES(1,'legacy-installation','Company','2026-08-31',
                        'legacy-token-reference','registered',?)""",
            (STAMP,),
        )
        connection.execute(
            """INSERT INTO registration_outbox(
                   operation_id,event_type,idempotency_key,request_fingerprint,
                   payload_json,state,next_attempt_at,created_at,updated_at
               ) VALUES('legacy-op','register','legacy-idempotency','legacy-fingerprint',
                        '{}','pending',?,?,?)""",
            (STAMP, STAMP, STAMP),
        )
        connection.execute(
            """INSERT INTO registration_attempt_history(
                   operation_id,attempted_at,outcome,duration_ms
               ) VALUES('legacy-op',?,'retry',1)""",
            (STAMP,),
        )
        connection.execute(
            """INSERT INTO v52_runtime_state(
                   singleton_id,company_name,installation_id,first_started_at,
                   status,updated_at
               ) VALUES(1,'Company','v52-installation','2026-08-31',
                        'registered',?)""",
            (STAMP,),
        )
        connection.execute(
            """INSERT INTO v52_telemetry_outbox(
                   operation_id,event_type,idempotency_key,request_fingerprint,
                   payload_json,state,next_attempt_at,created_at,updated_at
               ) VALUES('v52-op','status','v52-idempotency','v52-fingerprint',
                        '{}','pending',?,?,?)""",
            (STAMP, STAMP, STAMP),
        )
        connection.execute(
            """INSERT INTO v52_telemetry_success(event_type,last_successful_at)
               VALUES('meter',?)""",
            (STAMP,),
        )
    cache_file = Path(get_db_path()).parent / "runtime-cache" / "slot-1" / "day.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{}", encoding="utf-8")
    return {
        "cache_file": cache_file,
        "registration_installation_ids": ("legacy-installation", "v52-installation"),
        "legacy_token_ref": "legacy-token-reference",
    }


def _table_count(table: str) -> int:
    with _open(commit=False) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _seed_lan_membership(vault):
    from services.installation_identity import load_or_create_installation_identity
    from services.peer_membership import PeerMembership
    access = PeerMembership(path=get_db_path(), vault=vault,
        identity=load_or_create_installation_identity(vault, 'lan-installation'))
    access.initialize_primary('Synthetic LAN')
    with _open() as conn:
        conn.execute("INSERT INTO web_observation_state VALUES('origin','lan-origin') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    return access


def test_usage_reset_preserves_lan_membership_and_observation_identity():
    vault = SessionRegistrationSecretStore()
    access = _seed_lan_membership(vault)
    invitation = access.invitation()
    reset_usage_data()
    assert access.invitation() == invitation
    with _open(commit=False) as conn:
        assert conn.execute("SELECT value FROM web_observation_state WHERE key='origin'").fetchone() == ('lan-origin',)


@pytest.mark.parametrize('fail', [False, True])
def test_factory_reset_removes_lan_keys_atomically_with_group(fail):
    class Store(SessionRegistrationSecretStore):
        def delete(self, reference):
            super().delete(reference)
            if fail and ':lan:' in reference:
                raise RuntimeError('synthetic LAN vault failure')
    vault = Store()
    access = _seed_lan_membership(vault)
    original = access.invitation()
    capability_ref = access._reference(original['group_id'])
    key_ref = installation_private_key_reference(access.member_id)
    secrets = {ref: vault.load(ref) for ref in (capability_ref, key_ref)}
    if fail:
        with pytest.raises(RuntimeError, match='LAN vault failure'):
            factory_reset_v5(registration_secret_store=vault)
        assert access.invitation() == original
        assert {ref: vault.load(ref) for ref in secrets} == secrets
        assert _table_count('lan_peer_group') == 1
    else:
        factory_reset_v5(registration_secret_store=vault)
        assert _table_count('lan_peer_group') == _table_count('lan_peer_members') == 0
        assert all(vault.load(ref) is None for ref in secrets)
        assert _table_count('web_observation_state') == 0


def test_usage_reset_clears_report_history_and_preserves_configuration():
    state = _seed_reset_state()

    reset_usage_data()

    for table in (
        "peer_billing_deliveries",
        "peer_billing_amendments",
        "legacy_history_items",
        "billing_ledger",
        "daily_subject_records",
        "daily_raw_counter_records",
        "daily_meter_records",
        "legacy_history_imports",
        "price_snapshot",
        "config_log",
        "readings",
    ):
        assert _table_count(table) == 0
    for table in (
        "devices",
        "price_history",
        "cost_category_history",
        "parser_mapping_overrides",
        "parser_mapping_change_log",
        "registration_profile",
        "registration_outbox",
        "registration_attempt_history",
        "v52_runtime_state",
        "v52_telemetry_outbox",
        "v52_telemetry_success",
    ):
        assert _table_count(table) == 1
    assert not Path(state["cache_file"]).exists()
    with _open(commit=False) as connection:
        assert connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='trigger' AND name='billing_ledger_no_delete'"""
        ).fetchone()


def test_factory_reset_clears_v52_raw_parser_and_all_registration_secrets():
    state = _seed_reset_state()
    vault = SessionRegistrationSecretStore()
    references = {str(state["legacy_token_ref"])}
    for installation_id in state["registration_installation_ids"]:
        references.add(installation_token_reference(str(installation_id)))
        references.add(installation_private_key_reference(str(installation_id)))
    for index, reference in enumerate(sorted(references)):
        vault.save(reference, f"secret-{index}")

    factory_reset_v5(registration_secret_store=vault)

    for table in (
        "peer_billing_deliveries",
        "peer_billing_amendments",
        "registration_attempt_history",
        "registration_outbox",
        "registration_profile",
        "v52_telemetry_success",
        "v52_telemetry_outbox",
        "v52_runtime_state",
        "legacy_history_items",
        "billing_ledger",
        "daily_subject_records",
        "daily_raw_counter_records",
        "parser_mapping_change_log",
        "parser_mapping_overrides",
        "cost_category_history",
        "price_history",
        "daily_meter_records",
        "legacy_history_imports",
        "price_snapshot",
        "config_log",
        "readings",
        "devices",
    ):
        assert _table_count(table) == 0
    assert all(vault.load(reference) is None for reference in references)
    assert not Path(state["cache_file"]).exists()
    with _open(commit=False) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM settings WHERE key='first_run_complete'"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 9
        assert connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='trigger' AND name='billing_ledger_no_update'"""
        ).fetchone()


def test_factory_reset_rolls_back_database_cache_and_vault_on_secret_failure():
    state = _seed_reset_state()

    class FailingSecondDeleteStore(SessionRegistrationSecretStore):
        def __init__(self) -> None:
            super().__init__()
            self.delete_count = 0

        def delete(self, reference: str) -> None:
            self.delete_count += 1
            super().delete(reference)
            if self.delete_count == 2:
                raise RuntimeError("synthetic vault failure")

    vault = FailingSecondDeleteStore()
    references = {str(state["legacy_token_ref"])}
    for installation_id in state["registration_installation_ids"]:
        references.add(installation_token_reference(str(installation_id)))
        references.add(installation_private_key_reference(str(installation_id)))
    original_secrets = {
        reference: f"secret-{index}"
        for index, reference in enumerate(sorted(references))
    }
    for reference, secret in original_secrets.items():
        vault.save(reference, secret)

    with pytest.raises(RuntimeError, match="synthetic vault failure"):
        factory_reset_v5(registration_secret_store=vault)

    assert _table_count("devices") == 1
    assert _table_count("daily_raw_counter_records") == 1
    assert _table_count("parser_mapping_overrides") == 1
    assert _table_count("v52_runtime_state") == 1
    assert _table_count("registration_profile") == 1
    assert Path(state["cache_file"]).is_file()
    assert {
        reference: vault.load(reference) for reference in original_secrets
    } == original_secrets
    with _open(commit=False) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM billing_ledger")
