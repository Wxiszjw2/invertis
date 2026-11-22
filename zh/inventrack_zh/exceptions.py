"""InvenTrack CLI（简体中文版）领域自定义异常体系。"""


class InvenTrackError(Exception):
    """InvenTrack 领域全部业务异常的基类。"""


class DataFileNotFoundError(InvenTrackError):
    """当输入文件不存在或路径不是常规文件时抛出。"""


class UnsupportedFormatError(InvenTrackError):
    """当输入文件扩展名既不是 .csv 也不是 .json 时抛出。"""


class InvalidDataFormatError(InvenTrackError):
    """当文件结构、字符编码、JSON 根节点或 CSV 表头不合法时抛出。"""


class RecordValidationError(InvenTrackError):
    """当单条库存记录未通过字段类型或业务范围校验时抛出。"""

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
    """当 CLI 参数、筛选条件或用户交互输入不合法时抛出。"""
