"""One image catalog for the in-app and PDF source guide."""
SCREEN_NAMES = (
    "setup-company", "setup-printers", "setup-pricing", "setup-review",
    "overview", "devices", "reports-overview", "reports-usage", "reports-legacy",
    "settings", "advanced-lan", "advanced-tools", "manual",
)


def manual_screen_path(index, *, english=False):
    language = "en" if english else "th"
    return f"customer-guide/assets-v5.2.12-source/ui-{language}/{index:02d}-{SCREEN_NAMES[index-1]}.png"
