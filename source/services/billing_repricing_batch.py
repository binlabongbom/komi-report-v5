"""Atomic, reviewed dated-price corrections across a bounded usage range."""
from datetime import date, datetime
import json
from pathlib import Path

from database import _open
from services.billing_ledger import _source_hash
from services.billing_repricing import _discount_policy, _period_policy, _preview, confirm_in_transaction
from services.billing_period_amendment import prepare_archives, rebuild_archives
from services.peer_change_events import notify_local_change

MAX_BATCH_ROWS = 2000


def _range_preview(conn, start, end, slots, *, apply_current_discount=False, apply_current_period=False, include_archives=False):
    # Validate the selected policy once even if the range is empty or all held.
    discount = _discount_policy(conn, apply_current_discount)
    billing_day = _period_policy(conn, apply_current_period)
    if (type(start) is not date or type(end) is not date or start > end
            or not isinstance(slots, (list, tuple)) or not slots or len(set(slots)) != len(slots)
            or any(type(slot) is not int or slot not in range(3) for slot in slots)):
        raise ValueError("Invalid repricing date range or printer slots")
    slots = tuple(sorted(slots))
    rows = conn.execute(f"""SELECT b.id,b.entry_kind,b.source_hash FROM billing_ledger b
        WHERE b.record_date>=? AND b.record_date<=? AND b.device_slot IN ({','.join('?' for _ in slots)})
        AND NOT EXISTS(SELECT 1 FROM billing_ledger newer
            WHERE newer.source_daily_record_id=b.source_daily_record_id AND newer.id>b.id)
        ORDER BY b.record_date,b.device_slot,b.id LIMIT ?""", (start.isoformat(), end.isoformat(), *slots, MAX_BATCH_ROWS + 1)).fetchall()
    if len(rows) > MAX_BATCH_ROWS:
        raise ValueError("มีรายการมากเกินไป กรุณาเลือกช่วงวันที่สั้นลง")
    changed, unchanged, skipped = [], 0, []
    previews = []
    for ledger_id, _kind, _hash in rows:
        try:
            preview, _source = _preview(conn, ledger_id, apply_current_discount=apply_current_discount,
                                       apply_current_period=apply_current_period)
        except ValueError:
            skipped.append(ledger_id)
        else:
            previews.append(preview)
            if preview["changed"]:
                changed.append(preview)
            else:
                unchanged += 1
    database_path = str(Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve())
    archives, archive_revision = prepare_archives(conn, changed) if apply_current_period else ([], None)
    revision = _source_hash({"scope": (start.isoformat(), end.isoformat(), slots), "database": database_path,
                             "rows": rows, "previews": previews, "skipped": skipped,
                             "apply_current_discount": apply_current_discount, "discount": discount,
                             "apply_current_period": apply_current_period, "billing_day": billing_day,
                             "archive_revision": archive_revision})
    result = {"revision": revision, "start": start.isoformat(), "end": end.isoformat(), "slots": slots,
            "changed": changed, "unchanged": unchanged, "skipped": skipped,
            "apply_current_discount": apply_current_discount, "discount_basis_points": discount,
            "apply_current_period": apply_current_period, "billing_day": billing_day, "archive_count": len(archives),
            "old_net_cents": sum(row["old_net_cents"] for row in changed),
            "net_cents": sum(row["net_cents"] for row in changed)}
    if include_archives:
        result["archives"] = archives
    return result


class BatchRepricingService:
    def preview(self, start, end, slots, *, apply_current_discount=False, apply_current_period=False):
        with _open(commit=False) as conn:
            conn.execute("BEGIN")
            return _range_preview(conn, start, end, slots, apply_current_discount=apply_current_discount,
                                  apply_current_period=apply_current_period)

    @notify_local_change
    def confirm(self, start, end, slots, *, expected_revision, actor, reason, apply_current_discount=False,
                apply_current_period=False):
        if type(apply_current_discount) is not bool:
            raise ValueError("Discount selection must be boolean")
        if type(apply_current_period) is not bool:
            raise ValueError("Period selection must be boolean")
        if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Actor and reason are required")
        request = {"start": start.isoformat(), "end": end.isoformat(), "slots": sorted(slots),
                   "actor": actor.strip(), "reason": reason.strip()}
        if apply_current_discount:
            request["apply_current_discount"] = True
        if apply_current_period:
            request["apply_current_period"] = True
        with _open() as conn:
            conn.execute("BEGIN IMMEDIATE")
            receipt = conn.execute("SELECT new_value FROM config_log WHERE config_key='billing_reprice_batch' AND old_value=? ORDER BY id DESC LIMIT 1",
                                   (expected_revision,)).fetchone()
            if receipt:
                saved = json.loads(receipt[0])
                if saved["request"] != request:
                    raise ValueError("Batch retry differs from the confirmed request")
                if any(not conn.execute("SELECT 1 FROM billing_ledger WHERE id=? AND idempotency_key=?", (row["id"], row["key"])).fetchone()
                       for row in saved["results"]):
                    raise ValueError("Previously confirmed billing history is no longer present")
                return tuple(row["id"] for row in saved["results"])
            preview = _range_preview(conn, start, end, slots, apply_current_discount=apply_current_discount,
                                     apply_current_period=apply_current_period, include_archives=True)
            if preview["revision"] != expected_revision:
                raise ValueError("Prices or billing evidence changed after preview")
            if not preview["changed"]:
                raise ValueError("No price changes to apply")
            results = []
            for row in preview["changed"]:
                result_id = confirm_in_transaction(conn, row["ledger_id"], expected_revision=row["revision"], actor=actor, reason=reason,
                                                   apply_current_discount=apply_current_discount,
                                                   apply_current_period=apply_current_period, enqueue=False)
                key = conn.execute("SELECT idempotency_key FROM billing_ledger WHERE id=?", (result_id,)).fetchone()[0]
                results.append({"id": result_id, "key": key})
            rebuild_archives(conn, preview["archives"])
            from services.report_detail_amendment import refresh_period_summaries
            refresh_period_summaries(conn, preview['changed'])
            from services.billing_correction_transfer import enqueue_corrections
            enqueue_corrections(conn, [(row['ledger_id'], result['id'], 'reprice')
                for row, result in zip(preview['changed'], results)], actor=actor, reason=reason,
                created_at=datetime.now().astimezone().isoformat())
            conn.execute("INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)",
                ("billing_reprice_batch", expected_revision, json.dumps({"request": request, "results": results}, sort_keys=True),
                 datetime.now().astimezone().isoformat()))
            return tuple(row["id"] for row in results)
