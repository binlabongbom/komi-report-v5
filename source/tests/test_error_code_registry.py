from pathlib import Path
import re

from services.error_codes import ERROR_CODES
from services.support_diagnostics import CATALOG, diagnose, diagnostic_report, warning_report
from tools.export_error_codes import reference_markdown


def test_every_catalog_entry_has_a_unique_public_code():
    assert ERROR_CODES.keys() == CATALOG.keys()
    assert len(set(ERROR_CODES.values())) == len(ERROR_CODES)
    assert all(re.fullmatch(r'KOMI-[A-Z]+-\d{3}', code) for code in ERROR_CODES.values())
    # Published initial IDs: do not renumber when entries are inserted.
    assert ERROR_CODES['tls_handshake'] == 'KOMI-TLS-001'
    assert ERROR_CODES['password_rejected'] == 'KOMI-AUTH-003'
    assert ERROR_CODES['operation_failed'] == 'KOMI-APP-999'


def test_public_and_legacy_diagnostic_codes_round_trip():
    for key, public in ERROR_CODES.items():
        assert diagnose(f'Error Code: {public}').code == key
        assert diagnose(f'Code: {key}').error_code == public
    assert 'Error Code: KOMI-NET-002' in diagnostic_report(ConnectionRefusedError())


def test_generic_notice_has_stable_code_even_with_different_user_values():
    first = warning_report('Input', 'Missing file A')
    second = warning_report('Input', 'Missing file B')
    assert diagnose(first).error_code == diagnose(second).error_code == 'KOMI-UI-001'
    assert first != second  # Individual event evidence is retained.


def test_support_reference_matches_application_catalog():
    path = Path(__file__).resolve().parents[2] / 'ERROR_CODES.md'
    assert path.read_text(encoding='utf-8') == reference_markdown()
