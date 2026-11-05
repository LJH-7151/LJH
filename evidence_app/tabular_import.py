"""Bounded CSV ingestion with physical line locations and explicit encoding."""
import csv
import io
from dataclasses import dataclass

from .common import ValidationError
from .table_analysis import SourceRow

MAX_BYTES = 24 * 1024 * 1024
MAX_ROWS = 20000
MAX_COLUMNS = 200
MAX_FIELD = 1024 * 1024


@dataclass(frozen=True)
class Table:
    columns: tuple
    rows: tuple
    encoding: str


def parse_csv(content, header_row=1):
    if not isinstance(content, bytes) or not content or len(content) > MAX_BYTES:
        raise ValidationError('CSV 文件为空或超过24 MB')
    if type(header_row) is not int or not 1 <= header_row <= 100:
        raise ValidationError('表头行必须在1至100之间')
    try:
        text = content.decode('utf-8-sig')
        encoding = 'utf-8'
    except UnicodeDecodeError:
        try:
            text = content.decode('gb18030')
            encoding = 'gb18030'
        except UnicodeDecodeError:
            raise ValidationError('CSV 编码应为 UTF-8 或 GB18030') from None
    if '\x00' in text:
        raise ValidationError('CSV 不能包含空字符')
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    columns, rows = None, []
    previous = 0
    try:
        for record_number, record in enumerate(reader, start=1):
            start, end = previous + 1, reader.line_num
            previous = end
            if any(len(value) > MAX_FIELD for value in record):
                raise ValidationError('单元格内容过长')
            if record_number < header_row:
                continue
            if record_number == header_row:
                columns = tuple(value.strip() for value in record)
                if not columns or len(columns) > MAX_COLUMNS or any(not value for value in columns) or len(columns) != len(set(columns)):
                    raise ValidationError('表头必须非空、唯一且不超过200列')
                continue
            if not record or all(not value.strip() for value in record):
                continue
            if len(record) != len(columns):
                raise ValidationError(f'第{start}至{end}行的列数与表头不一致')
            if len(rows) >= MAX_ROWS:
                raise ValidationError('单表最多2万行')
            location = f'CSV 第{start}行' if start == end else f'CSV 第{start}–{end}行'
            rows.append(SourceRow(location, dict(zip(columns, record))))
    except csv.Error:
        raise ValidationError('CSV 格式无效，请检查引号和字段长度') from None
    if columns is None:
        raise ValidationError('没有找到指定表头行')
    return Table(columns, tuple(rows), encoding)
