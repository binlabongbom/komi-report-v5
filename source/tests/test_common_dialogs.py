from ui.common_dialogs import AllCountersDialog, PinnedCountersDialog


def test_common_dialogs_are_available_from_the_extracted_ui_module():
    assert issubclass(AllCountersDialog, object)
    assert issubclass(PinnedCountersDialog, object)
