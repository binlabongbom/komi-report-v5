"""One bounded maintenance interface for Web and daily detail archives."""
from services.web_observation_archive import WebObservationArchive
from services.report_detail_archive import ReportDetailArchive


class HistoryArchive:
    def __init__(self, database_path=None):
        self.archives = (WebObservationArchive(database_path), ReportDetailArchive(database_path))
        self.next_kind = 0

    def archive_batch(self, *, today=None):
        # Alternate kinds so years of Web rounds cannot starve daily history.
        for _ in self.archives:
            archive = self.archives[self.next_kind]
            self.next_kind = (self.next_kind + 1) % len(self.archives)
            result = archive.archive_batch(today=today)
            if result is not None:
                return result
        return None

    def stats(self, *, today=None):
        values = [archive.stats(today=today) for archive in self.archives]
        return {key: sum(value[key] for value in values) for key in ("eligible", "archived", "files")}
