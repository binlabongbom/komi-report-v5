"""Resolve display names from the selected report evidence, without database reads."""

from dataclasses import dataclass

from komi_snmp_profiler.subject_identity import prefer_subject_name, subject_name_is_placeholder


def subject_device_identity(record):
    identity = str(getattr(record, "device_identity", "") or "").strip()
    serial = str(getattr(record, "device_serial_snapshot", "") or "").strip()
    return identity or (f"serial:{serial}" if serial else f"slot:{int(record.device_slot)}")


def _name_day(record):
    # Compact Users evidence retains record_date, but not per-counter timestamps.
    # Use the same day resolution in the screen and export. latest_at reflects
    # an actual Subject observation; period_end may only be a requested boundary.
    observed = (getattr(record, "name_observed_on", None) or getattr(record, "latest_at", None)
                or getattr(record, "record_date", None)
                or getattr(record, "period_end", None) or "")
    return str(observed)[:10]


def _keep_name(names, key, name, rank):
    subject_id = key[3]
    name = str(name or "").strip()
    previous = names.get(key)
    if previous is None:
        names[key] = (prefer_subject_name(subject_id, "", name), rank)
        return
    current, current_rank = previous
    placeholder = subject_name_is_placeholder(subject_id, name)
    current_placeholder = subject_name_is_placeholder(subject_id, current)
    if (current_placeholder and not placeholder) or (
        placeholder == current_placeholder and rank >= current_rank
    ):
        names[key] = (prefer_subject_name(subject_id, current, name), rank)


@dataclass(frozen=True)
class SubjectNameIndex:
    names: dict
    slot_identities: dict

    def compatible_device_evidence(self, evidence):
        """Fill missing physical device-day keys from unambiguous legacy keys.

        Exact serial evidence wins. These are lookup aliases only: no amounts
        are added, and replacement printers never share a slot fallback.
        """
        for bucket in evidence:
            for (day, (slot, identity)), value in tuple(bucket.items()):
                if identity == f"slot:{slot}" and slot in self.slot_identities:
                    bucket.setdefault((day, (slot, self.slot_identities[slot])), value)
        return evidence

    def key(self, record):
        slot = int(record.device_slot)
        identity = subject_device_identity(record)
        if identity == f"slot:{slot}":
            identity = self.slot_identities.get(slot, identity)
        return slot, identity, str(record.subject_type), str(record.subject_id)

    def name(self, record):
        return self.names.get(self.key(record), prefer_subject_name(
            record.subject_id, "", getattr(record, "subject_name", "")))

    def group_key(self, record):
        slot, identity, kind, subject_id = self.key(record)
        name = self.name(record)
        if not subject_name_is_placeholder(subject_id, name):
            return f"{kind}:name:{name.casefold()}"
        return f"{kind}:slot:{slot}:device:{identity}:id:{subject_id}"


def build_subject_name_index(subjects, raw_records, *, checkpoint=None):
    """Keep the latest real name for each exact subject on a physical printer.

    A slot-only legacy record may join one known identity only when the entire
    selected evidence has no competing physical printer in that slot. Real
    names can still share a presentation row; placeholders cannot establish
    an identity across slots or printer replacements.
    """
    names, identities = {}, {}
    for source_rank, records in ((1, subjects), (0, raw_records)):
        for index, record in enumerate(records):
            if checkpoint is not None and index % 1024 == 0:
                checkpoint(index)
            slot = int(record.device_slot)
            identity = subject_device_identity(record)
            if identity != f"slot:{slot}":
                identities.setdefault(slot, set()).add(identity)
            kind = str(getattr(record, "subject_type", "") or "")
            subject_id = str(getattr(record, "subject_id", "") or "")
            if not kind or not subject_id:
                continue
            key = slot, identity, kind, subject_id
            _keep_name(names, key, getattr(record, "subject_name", ""), (_name_day(record), source_rank))
    slot_identities = {slot: next(iter(values)) for slot, values in identities.items() if len(values) == 1}
    resolved = {}
    for key, (name, rank) in names.items():
        slot, identity, kind, subject_id = key
        if identity == f"slot:{slot}":
            identity = slot_identities.get(slot, identity)
        _keep_name(resolved, (slot, identity, kind, subject_id), name, rank)
    return SubjectNameIndex({key: value[0] for key, value in resolved.items()}, slot_identities)
