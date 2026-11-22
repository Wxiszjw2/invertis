"""Hierarki custom exception untuk aplikasi InvenTrack CLI."""


class InvenTrackError(Exception):
    """Base exception untuk seluruh kesalahan domain InvenTrack."""


class DataFileNotFoundError(InvenTrackError):
    """Dilempar ketika file input tidak ditemukan atau bukan file reguler."""


class UnsupportedFormatError(InvenTrackError):
    """Dilempar ketika ekstensi file input bukan .csv atau .json."""


class InvalidDataFormatError(InvenTrackError):
    """Dilempar ketika struktur file, encoding, atau header tidak valid."""


class RecordValidationError(InvenTrackError):
    """Dilempar ketika satu baris record gagal melewati validasi tipe atau nilai."""

    def __init__(
        self,
        message: str,
        *,
        row_number: int | None = None,
        field_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.row_number = row_number
        self.field_name = field_name


class InvalidUserInputError(InvenTrackError):
    """Dilempar ketika parameter CLI, filter, atau input pengguna tidak sesuai."""
