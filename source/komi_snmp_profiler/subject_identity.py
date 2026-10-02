"""Subject display-name checks shared by collection and reporting."""


def subject_name_is_placeholder(subject_id, subject_name):
    sid, name = str(subject_id or "").strip(), str(subject_name or "").strip()
    if not name:
        return True
    if not sid:
        return False
    if name.casefold() == sid.casefold():
        return True
    if name.isdigit() and sid.isdigit():
        try:
            return int(name) == int(sid)
        except ValueError:
            # Digit-like glyphs such as superscripts may be intentional names;
            # they are not decimal IDs and must not crash or be overwritten.
            return False
    return False


def prefer_subject_name(subject_id, current_name, candidate_name):
    """Prefer a newly confirmed name without letting an ID erase a known name.

    Callers must establish the same printer/subject identity and chronological
    order first; matching display names alone never establishes identity.
    """
    current = str(current_name or "").strip()
    candidate = str(candidate_name or "").strip()
    if not subject_name_is_placeholder(subject_id, candidate):
        return candidate
    if not subject_name_is_placeholder(subject_id, current):
        return current
    return str(subject_id or "").strip() or candidate or current


def numeric_name_aliases(names):
    """Only normalize unambiguous decimal IDs; never merge distinct accounts."""
    candidates = {}
    for sid, name in names.items():
        if str(sid).isdecimal():
            candidates.setdefault(str(int(sid)), set()).add(name)
    return {sid: next(iter(values)) for sid, values in candidates.items() if len(values) == 1}
