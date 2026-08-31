from services.snmp_probe import PaperTrayStatus, SnmpTotalProbe


def test_primary_total_oid_wins_when_device_exposes_multiple_markers():
    selected = SnmpTotalProbe.select_total(
        [
            ("1.3.6.1.2.1.43.10.2.1.4.9.9", 999_999),
            (SnmpTotalProbe.PRIMARY_TOTAL_OID, 12_345),
        ]
    )

    assert selected == (SnmpTotalProbe.PRIMARY_TOTAL_OID, 12_345)


def test_largest_nonnegative_marker_is_legacy_fallback():
    selected = SnmpTotalProbe.select_total(
        [
            ("1.3.6.1.2.1.43.10.2.1.4.2.1", 100),
            ("1.3.6.1.2.1.43.10.2.1.4.3.1", 500),
        ]
    )

    assert selected[1] == 500


def test_web_calibrated_oid_wins_over_primary_marker():
    calibrated_oid = "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.1.0"
    selected = SnmpTotalProbe.select_total(
        [
            (SnmpTotalProbe.PRIMARY_TOTAL_OID, 12_345),
            (calibrated_oid, 54_321),
        ],
        calibrated_oid,
    )

    assert selected == (calibrated_oid, 54_321)


def test_c12010s_profile_selects_private_total_before_web_calibration():
    private_oid = "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.1.0"

    selected = SnmpTotalProbe.select_total_for_model(
        [
            (SnmpTotalProbe.PRIMARY_TOTAL_OID, 250_132),
            (private_oid, 250_206),
        ],
        "KONICA MINOLTA AccurioPress C12010S",
    )

    assert selected == (private_oid, 250_206)


def test_targeted_core_oids_cover_total_identity_and_serial_without_walk():
    assert SnmpTotalProbe.required_exact_oids() == (
        SnmpTotalProbe.PRIMARY_TOTAL_OID,
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.1.0",
        SnmpTotalProbe.MODEL_OID,
        SnmpTotalProbe.SERIAL_OID,
    )


def test_toner_levels_are_joined_by_supply_row_and_converted_to_percent():
    levels = SnmpTotalProbe.parse_toner_levels(
        [
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.1", "Black Toner"),
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.2", "Cyan Toner"),
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.3", "Magenta Toner"),
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.4", "Yellow Toner"),
        ],
        [
            (f"{SnmpTotalProbe.SUPPLY_CAPACITY_ROOT}.1.1", "100"),
            (f"{SnmpTotalProbe.SUPPLY_CAPACITY_ROOT}.1.2", "200"),
            (f"{SnmpTotalProbe.SUPPLY_CAPACITY_ROOT}.1.3", "100"),
            (f"{SnmpTotalProbe.SUPPLY_CAPACITY_ROOT}.1.4", "100"),
        ],
        [
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.1", "88"),
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.2", "122"),
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.3", "80"),
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.4", "74"),
        ],
    )

    assert levels == {"C": 61, "Y": 74, "M": 80, "K": 88}


def test_toner_parser_ignores_drums_and_unknown_negative_levels():
    levels = SnmpTotalProbe.parse_toner_levels(
        [
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.1", "Black Imaging Unit"),
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.2", "Cyan Toner"),
        ],
        [
            (f"{SnmpTotalProbe.SUPPLY_CAPACITY_ROOT}.1.1", "100"),
            (f"{SnmpTotalProbe.SUPPLY_CAPACITY_ROOT}.1.2", "100"),
        ],
        [
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.1", "70"),
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.2", "-3"),
        ],
    )

    assert levels == {}


def test_accuriopress_toner_detail_uses_direct_percent_with_sentinel_capacity():
    levels = SnmpTotalProbe.parse_toner_levels(
        [
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.1", "Toner bottle(Cyan)"),
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.2", "Toner bottle detail(Cyan)"),
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.3", "Toner bottle detail(Magenta)"),
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.4", "Toner bottle detail(Yellow)"),
            (f"{SnmpTotalProbe.SUPPLY_DESCRIPTION_ROOT}.1.5", "Toner bottle detail(Black)"),
        ],
        [
            (f"{SnmpTotalProbe.SUPPLY_CAPACITY_ROOT}.1.{index}", "-2")
            for index in range(1, 6)
        ],
        [
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.1", "-3"),
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.2", "91"),
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.3", "28"),
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.4", "71"),
            (f"{SnmpTotalProbe.SUPPLY_LEVEL_ROOT}.1.5", "64"),
        ],
    )

    assert levels == {"C": 91, "Y": 71, "M": 28, "K": 64}


def test_paper_trays_are_sorted_by_numeric_input_index():
    trays = SnmpTotalProbe.parse_paper_trays(
        [],
        [
            (f"{SnmpTotalProbe.INPUT_CAPACITY_ROOT}.1.19", "1540"),
            (f"{SnmpTotalProbe.INPUT_CAPACITY_ROOT}.1.2", "1080"),
            (f"{SnmpTotalProbe.INPUT_CAPACITY_ROOT}.1.10", "250"),
        ],
        [],
        [],
    )

    assert [tray.input_index for tray in trays] == [2, 10, 19]


def test_paper_status_reports_empty_only_for_explicit_empty_evidence():
    trays = SnmpTotalProbe.parse_paper_trays(
        [(f"{SnmpTotalProbe.INPUT_NAME_ROOT}.1.1", "Tray 1")],
        [(f"{SnmpTotalProbe.INPUT_CAPACITY_ROOT}.1.1", "500")],
        [(f"{SnmpTotalProbe.INPUT_LEVEL_ROOT}.1.1", "0")],
        [(f"{SnmpTotalProbe.INPUT_STATUS_ROOT}.1.1", "6")],
    )

    summary = SnmpTotalProbe.summarize_paper(trays)

    assert trays == (PaperTrayStatus("Tray 1", 0, 500, 6, 1),)
    assert summary.state == "empty"
    assert summary.trays == ("Tray 1",)


def test_paper_status_does_not_mislabel_unknown_or_unavailable_tray_as_empty():
    unknown = SnmpTotalProbe.summarize_paper((PaperTrayStatus("Tray 1", -2, 500, 6),))
    known_available = SnmpTotalProbe.summarize_paper((PaperTrayStatus("Tray 2", -3, 500, 4),))

    assert unknown.state == "attention"
    assert known_available.state == "available"


def test_paper_status_does_not_mark_whole_machine_empty_when_only_bypass_is_empty():
    summary = SnmpTotalProbe.summarize_paper(
        (
            PaperTrayStatus("Bypass", 0, 100, 6),
            PaperTrayStatus("Tray 1", 250, 500, 4),
        )
    )

    assert summary.state == "attention"
    assert summary.trays == ("Bypass",)
