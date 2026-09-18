"""Run operational source files separately to isolate Windows Qt lifetime state."""
import json
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
source = root / "source"
names = """
test_agent_handoff test_agent_tray test_background_agent_lifecycle test_tray_lifecycle
test_background_polling test_manual_polling_coordination test_startup_sync test_reader_jobs
test_app_setup test_setup_settings test_setup_wizard_v5 test_setup_connectivity
test_shared_settings test_shared_price_history test_shared_slot_review test_shared_settings_history_ui
test_peer_settings_history test_peer_settings_outbox test_peer_settings_pages test_peer_sync_authorization
test_slot_epoch_store test_slot_epoch_exchange test_slot_meter_continuity test_slot_replacement
test_peer_history_session test_peer_history_runtime test_network_activity
test_web_observations test_web_catchup test_web_usage_projection test_web_evidence_report
test_web_observation_archive test_archive_maintenance test_archive_recovery test_report_detail_archive
test_archive_settings_ui test_billing_period_amendment test_billing_repricing test_billing_repricing_batch
test_billing_ledger test_billing_audit_ui test_billing_day_consistency test_billing_v5
test_subject_history test_subject_counter_review test_raw_counter_history test_raw_counter_review
test_daily_cache test_counter_review test_counter_review_ui test_report_snapshot
test_report_custom_period test_report_excel_export test_reporting_facade test_summary_service
test_reports_background_loading test_reports_startup_prefetch test_reports_responsive_layout
test_settings_v5 test_settings_navigation test_sidebar_navigation test_overview_v5_ui
test_database test_database_reset_v5 test_migrations test_desktop_shortcuts test_web_report_launcher
test_lan_discovery test_lan_tls test_registration_recovery test_registration_client
test_registration_worker test_v5_2_runtime test_runtime_snapshots test_web_api
""".split()
parser = argparse.ArgumentParser()
parser.add_argument("--remaining", action="store_true", help="Other source tests, excluding release/build suites")
args = parser.parse_args()
excluded = {"test_phase4_release_candidate", "test_phase5_pilot_release", "test_phase6_customer_release",
            "test_release_builder", "test_prepare_web_runtime", "test_mac_v528_validation"}
if args.remaining:
    covered = set(names)
    names = sorted(str(path.relative_to(source / "tests").with_suffix("")).replace("\\", "/")
                   for path in (source / "tests").rglob("test_*.py")
                   if path.stem not in covered | excluded)
report = root / ("docs/qa/v5.2.12/additional-source-regression.json" if args.remaining else
                 "docs/qa/v5.2.12/source-regression.json")
report.parent.mkdir(parents=True, exist_ok=True)
bootstrap = '''
import ipaddress, sys
def local_only(event, args):
    if event in ('socket.connect', 'socket.sendto'):
        address = args[1]
        if isinstance(address, tuple):
            host = str(address[0])
            if host == 'localhost':
                return
            try:
                if ipaddress.ip_address(host).is_loopback:
                    return
            except ValueError:
                pass
            raise PermissionError('Source regression forbids non-loopback traffic')
sys.addaudithook(local_only)
import pytest
sys.exit(pytest.main(sys.argv[1:]))
'''
env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "KOMI_DISCOVERY_DISABLED": "1", "PYTHONIOENCODING": "utf-8"}
state = {"scope": f"{len(names)} selected operational source files; each in a fresh pytest process",
         "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
         "working_tree_status": subprocess.check_output(["git", "status", "--short"], cwd=root, text=True),
         "excluded_release_build_files": sorted(excluded) if args.remaining else [],
         "non_loopback_network": "denied by an audit hook in each pytest process; subprocess fixtures are separately isolated",
         "installer_or_release_build": False,
         "complete": False, "results": []}
for name in names:
    start = time.monotonic()
    try:
        result = subprocess.run([sys.executable, "-c", bootstrap, f"tests/{name}.py", "-q"], cwd=source,
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        row = {"file": name + ".py", "exit_code": result.returncode,
               "seconds": round(time.monotonic() - start, 2), "output": (result.stdout + result.stderr)[-14000:]}
    except subprocess.TimeoutExpired as error:
        row = {"file": name + ".py", "exit_code": "timeout", "seconds": 180,
               "output": str(error.stdout or b'')[-10000:]}
    state["results"].append(row)
    report.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(state['results'])}/{len(names)} {name}: {row['exit_code']}", flush=True)
state["complete"] = True
state["file_count"] = len(names)
state["failed_files"] = [r["file"] for r in state["results"] if r["exit_code"] != 0]
report.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
sys.exit(bool(state["failed_files"]))
