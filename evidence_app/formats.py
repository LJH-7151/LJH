"""Read UTF-8 text while preserving its original source line numbers."""
from pathlib import PurePosixPath

from .common import ValidationError

MAX_UPLOAD_BYTES = 24 * 1024 * 1024


def parse_text(name, content):
    if not isinstance(name, str) or not 0 < len(name) <= 160:
        raise ValidationError("文件名不能为空，且最多160个字符")
    if name != name.strip() or any(ord(char) < 32 for char in name) or "/" in name or "\\" in name:
        raise ValidationError("请使用不包含路径或控制字符的文件名")
    if PurePosixPath(name).suffix.lower() not in (".txt", ".md"):
        raise ValidationError("第一阶段只支持 UTF-8 编码的 TXT 和 Markdown 文件")
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_UPLOAD_BYTES:
        raise ValidationError("文件不能为空，且不能超过24 MiB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode('gb18030')
        except UnicodeDecodeError:
            raise ValidationError("文本编码应为 UTF-8 或 GB18030") from None
    if "\x00" in text or not text.strip():
        raise ValidationError("文件必须包含有效的非空文本")

    # Blank source lines separate paragraphs. The displayed text is never
    # interpreted as HTML or Markdown; original bytes remain downloadable.
    chunks = []
    paragraph = []
    start_line = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not paragraph:
                start_line = line_number
            paragraph.append(line)
        elif paragraph:
            chunks.append((start_line, line_number - 1, "\n".join(paragraph)))
            paragraph = []
    if paragraph:
        chunks.append((start_line, line_number, "\n".join(paragraph)))
    return chunks
