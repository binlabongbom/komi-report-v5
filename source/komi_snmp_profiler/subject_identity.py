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


def numeric_name_aliases(names):
    """Only normalize unambiguous decimal IDs; never merge distinct accounts."""
    candidates = {}
    for sid, name in names.items():
        if str(sid).isdecimal():
            candidates.setdefault(str(int(sid)), set()).add(name)
    return {sid: next(iter(values)) for sid, values in candidates.items() if len(values) == 1}
