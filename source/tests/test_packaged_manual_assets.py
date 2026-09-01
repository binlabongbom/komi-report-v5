from pathlib import Path


def test_app_spec_packages_every_customer_guide_screenshot():
    source_root = Path(__file__).resolve().parents[1]
    project_root = source_root.parent
    asset_root = project_root / "docs" / "customer-guide" / "assets-v5.2"
    expected = [asset_root / f"{index:02d}-{name}.png" for index, name in enumerate(
        (
            "setup-company",
            "setup-printers",
            "setup-pricing",
            "setup-review",
            "overview",
            "devices",
            "reports-overview",
            "reports-usage",
            "reports-legacy",
            "settings",
            "advanced-lan",
            "advanced-tools",
            "manual",
        ),
        start=1,
    )]

    assert all(path.is_file() and path.stat().st_size > 0 for path in expected)
    spec = (source_root / "app.spec").read_text(encoding="utf-8")
    assert "../docs/customer-guide/assets-v5.2" in spec


def test_windows_customer_payload_builder_packages_manual_assets():
    source_root = Path(__file__).resolve().parents[1]
    builder = (source_root / "tools" / "build_windows_rc.py").read_text(
        encoding="utf-8"
    )

    assert 'PROJECT_ROOT / "docs" / "customer-guide" / "assets-v5.2"' in builder
    assert 'docs_destination / "customer-guide" / "assets-v5.2"' in builder
    assert "Customer guide screenshot assets are missing" in builder


def test_source_release_packages_manual_assets_for_cross_platform_builds():
    source_root = Path(__file__).resolve().parents[1]
    builder = (source_root / "tools" / "build_local_release.py").read_text(
        encoding="utf-8"
    )

    assert 'PROJECT_ROOT / "docs" / "customer-guide" / "assets-v5.2"' in builder
