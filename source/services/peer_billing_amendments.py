"""Durable, portable Web allocation decisions and verified delivery receipts.

Transfer decisions and evidence references, never a database or remote row IDs.
Recipients recompute against their own evidence and frozen accounting policy.
Missing evidence or different accounts remain pending rather than overwriting.
The authorizer must bind an authenticated member to the company/Slot/decision.
"""
from datetime import date, datetime, timezone, timedelta, UTC
import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.peer_settings_outbox import _peer, _now

FORMAT = "komi.billing.web-allocation-transfer.v1"
MAX_BYTES = 1024 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decision(preview, *, actor, reason):
    payload = {"format": FORMAT, "scope": preview["scope"], "serial": preview["template"][4],
        "events": preview["events"], "before": preview["before"], "categories": preview["categories"],
        "prices": preview["price_cents"], "discount": preview["discount"], "billing_day": preview["billing_day"],
        "currency": preview["currency"], "calendar": preview["calendar"], "actor": actor.strip(), "reason": reason.strip(),
        "after": [{key: row[key] for key in ("day", "delta", "period", "gross_cents", "net_cents", "intervals")}
                  for row in preview["changed"]]}
    payload = json.loads(_json(payload))  # One canonical representation across DBs/processes.
    document = {"id": hashlib.sha256(_json(payload).encode()).hexdigest(), "payload": payload}
    validate_document(document)
    return document


def validate_document(document):
    from services.report_detail_amendment import FORMAT as DETAIL_FORMAT, validate as validate_detail
    if isinstance(document, dict) and isinstance(document.get('payload'), dict) and document['payload'].get('format') == DETAIL_FORMAT:
        return validate_detail(document)
    from services.billing_correction_transfer import FORMAT as CORRECTION_FORMAT, validate
    if isinstance(document, dict) and isinstance(document.get('payload'), dict) and document['payload'].get('format') == CORRECTION_FORMAT:
        return validate(document)
    if not isinstance(document, dict) or set(document) != {"id", "payload"}:
        raise ValueError("Invalid amendment envelope")
    payload = document["payload"]
    keys = {"format", "scope", "serial", "events", "before", "categories", "prices", "discount",
            "billing_day", "currency", "calendar", "actor", "reason", "after"}
    if not isinstance(payload, dict) or set(payload) != keys or payload["format"] != FORMAT:
        raise ValueError("Invalid amendment format")
    encoded = _json(document)
    if len(encoded.encode()) > MAX_BYTES or hashlib.sha256(_json(payload).encode()).hexdigest() != document["id"]:
        raise ValueError("Altered or oversized amendment")
    scope = payload["scope"]
    if (not isinstance(scope, list) or len(scope) != 5 or type(scope[0]) is not int or scope[0] not in range(3)
            or any(not isinstance(v, str) or not v or len(v) > 256 for v in scope[1:])
            or not isinstance(payload["events"], list) or not 2 <= len(payload["events"]) <= 4096
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in payload["events"])
            or any(not isinstance(payload[k], str) or not payload[k].strip() or len(payload[k]) > 1000
                   for k in ("actor", "reason", "serial"))):
        raise ValueError("Invalid amendment scope or proof")
    return encoded


def _zone(calendar):
    if (not isinstance(calendar, dict) or set(calendar) != {"name", "iana", "offset_seconds"}
            or not isinstance(calendar["name"], str) or not calendar["name"]
            or type(calendar["offset_seconds"]) is not int or abs(calendar["offset_seconds"]) >= 86400):
        raise ValueError("Invalid amendment calendar timezone")
    if calendar["iana"] is not None:
        try:
            return ZoneInfo(calendar["iana"])
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("Required amendment timezone data is unavailable") from None
    return timezone(timedelta(seconds=calendar["offset_seconds"]), calendar["name"])


def enqueue_amendment(conn, preview, results, *, actor, reason, created_at):
    if not conn.in_transaction:
        raise ValueError("Accounting and outgoing amendment must commit together")
    document = decision(preview, actor=actor, reason=reason)
    conn.execute("""INSERT INTO peer_billing_amendments(amendment_id,document_json,results_json,created_at)
        VALUES(?,?,?,?)""", (document["id"], _json(document), _json(results), created_at))
    return document["id"]


class PeerBillingAmendments:
    def __init__(self, *, authorize, path=None, today=date.today):
        from services.billing_web_amendment import BillingWebAmendmentService
        if not callable(authorize):
            raise TypeError("A verified amendment authorizer is required")
        self.authorize = authorize
        self.service = BillingWebAmendmentService(database_path=path, today=today)

    def _allowed(self, member, document):
        _peer(member)
        if self.authorize(member, document) is not True:
            raise PermissionError("Member cannot exchange this billing amendment")

    @staticmethod
    def _result_present(conn, result):
        if result.get('kind') == 'detail':
            return conn.execute('SELECT 1 FROM report_detail_revisions WHERE id=? AND amendment_id=?',
                                (result['id'], result['key'])).fetchone() is not None
        return conn.execute('SELECT 1 FROM billing_ledger WHERE id=? AND idempotency_key=?',
                            (result['id'], result['key'])).fetchone() is not None

    def contains(self, member, document):
        validate_document(document)
        self._allowed(member, document)
        with self.service._connection() as conn:
            saved = conn.execute('SELECT document_json,results_json FROM peer_billing_amendments WHERE amendment_id=?',
                                 (document['id'],)).fetchone()
            present = bool(saved and saved[0] == _json(document) and all(self._result_present(conn, r)
                for r in json.loads(saved[1])))
            self._allowed(member, document)
        return {'amendment_id': document['id'], 'present': present}

    def recheck(self, member, transport, *, after=0, limit=16):
        """On reconnect, recheck bounded old receipts after receiver restore."""
        _peer(member)
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 64:
            raise ValueError('Invalid amendment receipt audit cursor')
        with self.service._connection() as conn:
            rows = conn.execute('''SELECT a.sequence,a.document_json FROM peer_billing_amendments a
                JOIN peer_billing_deliveries d ON d.amendment_id=a.amendment_id
                WHERE d.member_id=? AND d.acknowledged_at IS NOT NULL AND a.sequence>?
                ORDER BY a.sequence LIMIT ?''', (member, after, limit)).fetchall()
        for sequence, encoded in rows:
            document = json.loads(encoded)
            self._allowed(member, document)
            receipt = transport.amendment_contains(document)
            self._allowed(member, document)
            if (not isinstance(receipt, dict) or set(receipt) != {'amendment_id', 'present'}
                    or receipt['amendment_id'] != document['id'] or type(receipt['present']) is not bool):
                raise ValueError('Invalid amendment resume receipt')
            if not receipt['present']:
                with self.service._connection(write=True) as conn:
                    self._allowed(member, document)
                    conn.execute('UPDATE peer_billing_deliveries SET acknowledged_at=NULL,retry_at=0 '
                                 'WHERE member_id=? AND amendment_id=?', (member, document['id']))
            after = sequence
        return {'after': after, 'more': len(rows) == limit}

    def receive(self, member, document):
        from services.billing_web_amendment import _preview
        validate_document(document)
        self._allowed(member, document)
        payload = document["payload"]
        with self.service._connection(write=True) as conn:
            saved = conn.execute("SELECT document_json,results_json FROM peer_billing_amendments WHERE amendment_id=?",
                                 (document["id"],)).fetchone()
            if saved:
                if saved[0] != _json(document) or any(not self._result_present(conn, r) for r in json.loads(saved[1])):
                    raise ValueError("Stored amendment receipt is incomplete")
            else:
                from services.billing_correction_transfer import FORMAT as CORRECTION_FORMAT, apply
                from services.report_detail_amendment import FORMAT as DETAIL_FORMAT, preview as detail_preview, document_for, commit
                if payload['format'] == CORRECTION_FORMAT:
                    apply(conn, document)
                elif payload['format'] == DETAIL_FORMAT:
                    from services.web_usage_projection import CounterIdentity
                    slot, epoch, start, end = payload['scope']
                    candidate = detail_preview(conn, self.service.path, slot, epoch, date.fromisoformat(start), date.fromisoformat(end),
                        _zone(payload['calendar']), CounterIdentity(*payload['counter']), self.service.today())
                    if document_for(candidate, payload['actor'], payload['reason']) != document:
                        raise ValueError('Local detail evidence differs; amendment needs review')
                    commit(conn, self.service.path, document)
                else:
                    slot, epoch, start, end, zone = payload["scope"]
                    preview = _preview(conn, slot, epoch, date.fromisoformat(start), date.fromisoformat(end),
                                       _zone(payload["calendar"]), self.service.today())
                    if decision(preview, actor=payload["actor"], reason=payload["reason"]) != document:
                        raise ValueError("Local evidence or accounting differs; amendment needs review")
                    self.service._commit(conn, preview, actor=payload["actor"], reason=payload["reason"])
            self._allowed(member, document)  # Revocation while processing rolls back everything.
            self._ack(conn, member, document["id"], datetime.now(UTC).isoformat())
        from services.peer_change_events import committed
        committed(self.service.path)
        return {"amendment_id": document["id"], "committed": True}

    @staticmethod
    def _ack(conn, member, amendment_id, stamp):
        conn.execute("""INSERT INTO peer_billing_deliveries(member_id,amendment_id,acknowledged_at)
            VALUES(?,?,?) ON CONFLICT(member_id,amendment_id) DO UPDATE SET
            acknowledged_at=COALESCE(peer_billing_deliveries.acknowledged_at,excluded.acknowledged_at),
            retry_at=0,error_code=''""", (member, amendment_id, stamp))

    def pending(self, member, *, now=None, reconnect=False):
        _peer(member)
        stamp = _now(now)
        with self.service._connection() as conn:
            row = conn.execute("""SELECT a.document_json,COALESCE(d.retry_at,0) FROM peer_billing_amendments a
                LEFT JOIN peer_billing_deliveries d ON d.amendment_id=a.amendment_id AND d.member_id=?
                WHERE d.acknowledged_at IS NULL ORDER BY a.sequence LIMIT 1""", (member,)).fetchone()
        if row is None:
            return None
        document = json.loads(row[0])
        validate_document(document)
        self._allowed(member, document)
        return document if reconnect or row[1] <= stamp else None

    def acknowledge(self, member, receipt):
        if (not isinstance(receipt, dict) or set(receipt) != {"amendment_id", "committed"}
                or receipt["committed"] is not True):
            raise ValueError("A durable amendment receipt is required")
        with self.service._connection(write=True) as conn:
            row = conn.execute("SELECT document_json FROM peer_billing_amendments WHERE amendment_id=?",
                               (receipt["amendment_id"],)).fetchone()
            if row is None:
                raise ValueError("Unknown amendment receipt")
            self._allowed(member, json.loads(row[0]))
            self._ack(conn, member, receipt["amendment_id"], datetime.now(UTC).isoformat())

    def failed(self, member, amendment_id, *, code, now=None):
        if code not in {"transport", "unauthorized", "conflict", "invalid_response"}:
            raise ValueError("Invalid amendment delivery error")
        stamp = _now(now)
        with self.service._connection(write=True) as conn:
            row = conn.execute("SELECT document_json FROM peer_billing_amendments WHERE amendment_id=?", (amendment_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown amendment")
            _peer(member)
            previous = conn.execute("SELECT attempts,acknowledged_at FROM peer_billing_deliveries WHERE member_id=? AND amendment_id=?",
                                    (member, amendment_id)).fetchone()
            if previous and previous[1]:
                return
            attempts = (previous[0] if previous else 0) + 1
            conn.execute("""INSERT INTO peer_billing_deliveries(member_id,amendment_id,attempts,retry_at,error_code)
                VALUES(?,?,?,?,?) ON CONFLICT(member_id,amendment_id) DO UPDATE SET
                attempts=excluded.attempts,retry_at=excluded.retry_at,error_code=excluded.error_code""",
                (member, amendment_id, attempts, stamp + min(300, 2 ** min(9, attempts)), code))

    def deliver_one(self, member, transport, *, reconnect=False):
        document = self.pending(member, reconnect=reconnect)
        if document is None:
            return False
        try:
            receipt = transport.amendment(document)
            if not isinstance(receipt, dict) or receipt.get("amendment_id") != document["id"]:
                raise ValueError("Peer acknowledged a different amendment")
            self.acknowledge(member, receipt)
        except Exception as error:
            code = "unauthorized" if isinstance(error, PermissionError) else "conflict" if isinstance(error, ValueError) else "transport"
            self.failed(member, document["id"], code=code)
            raise
        return True
