"""Compatibility imports for v5_pages; new code imports the owning ui module."""

from ui.policy import (
    OFFLINE_ACTIVATION_ENABLED as OFFLINE_ACTIVATION_ENABLED,
)
from ui.components.notices import (
    show_compact_information as show_compact_information,
)
from ui.setup.controls import (
    SetupDeviceStatusDelegate as SetupDeviceStatusDelegate,
    WizardComboBox as WizardComboBox,
)
from ui.setup.workers import (
    DeviceTestResult as DeviceTestResult,
    DeviceTestWorker as DeviceTestWorker,
    NetworkDiscoveryWorker as NetworkDiscoveryWorker,
    SecondaryPeerDiscoveryWorker as SecondaryPeerDiscoveryWorker,
    SetupConnectivityWorker as SetupConnectivityWorker,
    SecondarySnapshotWorker as SecondarySnapshotWorker,
    EnrollmentCommitWorker as EnrollmentCommitWorker,
)
from ui.setup.legacy_import import (
    LegacyHistoryImportDialog as LegacyHistoryImportDialog,
)
from ui.setup.wizard import (
    SetupWizardV5 as SetupWizardV5,
)
from ui.pages.device_overview import (
    PageDeviceOverview as PageDeviceOverview,
)
from ui.pages.activity import (
    PagePipelineLog as PagePipelineLog,
)
from ui.pages.devices import (
    _TonerLevelBar as _TonerLevelBar,
    _PulsingStatusIndicator as _PulsingStatusIndicator,
    PageImportV5 as PageImportV5,
)
from ui.reports.export_dialog import (
    ReportExportPeriodDialog as ReportExportPeriodDialog,
)
from ui.reports.page import (
    CloudReportsExportData as CloudReportsExportData,
    export_cloud_reports_xlsx as export_cloud_reports_xlsx,
    suggested_cloud_reports_filename as suggested_cloud_reports_filename,
    PageHistoryV5 as PageHistoryV5,
)
from ui.settings.controls import (
    ScheduleTimeRangeEditor as ScheduleTimeRangeEditor,
    WeekdaySelector as WeekdaySelector,
    WebAccessCodeDialog as WebAccessCodeDialog,
)
from ui.settings.fleet import (
    PageFleetSettings as PageFleetSettings,
)
from ui.settings.billing_audit import (
    _pretty_audit_json as _pretty_audit_json,
    audit_row_detail_text as audit_row_detail_text,
    BillingAuditDetailDialog as BillingAuditDetailDialog,
    _load_billing_audit_view as _load_billing_audit_view,
    PageBillingAudit as PageBillingAudit,
)
from ui.settings.page import (
    PageSettingsV5 as PageSettingsV5,
)
