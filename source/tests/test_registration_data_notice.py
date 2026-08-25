from services.registration_data_notice import DRAFT_NOTICE_VERSION, registration_data_notice


def test_registration_data_notice_is_bilingual_and_scoped_to_non_personal_data():
    thai = registration_data_notice("th")
    english = registration_data_notice("en")

    assert DRAFT_NOTICE_VERSION in thai
    assert DRAFT_NOTICE_VERSION in english
    assert "Aggregate Total Meter" in thai
    assert "aggregate Total Meter" in english
    assert "Raw SNMP/XML/Error" in thai
    assert "raw SNMP/XML/errors" in english
    assert "ไม่ใช่ข้อมูลส่วนบุคคล" in thai
    assert "not personal data" in english
    assert "ห้ามกรอกชื่อบุคคล" in thai
    assert "must not enter a person's name" in english


def test_registration_data_notice_matches_payload_and_exclusions():
    thai = registration_data_notice("th")
    english = registration_data_notice("en")

    for expected in ("Installation ID", "Serial Number", "Version", "12 เดือน", "90 วัน"):
        assert expected in thai
    for expected in ("Installation ID", "serial number", "application version", "12 months", "90 days"):
        assert expected in english

    assert "ไม่ส่ง IP address" in thai
    assert "does not send IP address" in english
    assert "ไม่ถูกจัดเก็บ" in thai
    assert "is not retained" in english
    assert "https://www.dmskm.com/" in thai
    assert "https://www.dmskm.com/" in english
