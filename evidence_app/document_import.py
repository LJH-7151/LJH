"""Read selected document formats with explicit, non-fabricated locations."""
import io
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from .common import ValidationError
from .formats import parse_text, MAX_UPLOAD_BYTES

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def parse_document(name, data):
    suffix = PurePosixPath(name).suffix.lower() if isinstance(name, str) else ''
    if suffix in ('.txt', '.md'):
        return [(start, end, text, None) for start, end, text in parse_text(name, data)]
    if suffix not in ('.docx', '.pdf'):
        raise ValidationError('仅支持 TXT、Markdown、DOCX 和 PDF')
    if not name or name != name.strip() or len(name) > 160 or any(ord(c) < 32 for c in name) or '/' in name or '\\' in name:
        raise ValidationError('文件名无效')
    if not isinstance(data, bytes) or not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError('文件不能为空且不能超过24 MiB')
    if suffix == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValidationError('PDF 解析需要安装 pypdf') from None
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ValidationError('加密 PDF 需要先解密')
            if len(reader.pages) > 1000:
                raise ValidationError('PDF 最多支持1000页')
            result = []
            for page_number, page in enumerate(reader.pages, 1):
                text = page.extract_text().strip()
                if not text:
                    raise ValidationError('PDF 存在无文字页面，需要 OCR 及人工复核')
                result.append((page_number, page_number, text, f'第{page_number}页'))
        except ValidationError:
            raise
        except Exception:
            raise ValidationError('PDF 解析失败，请检查文件') from None
        if not result:
            raise ValidationError('PDF 没有可提取文字的页面')
        return result
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 5000 or sum(x.file_size for x in members) > 64 * 1024 * 1024:
                raise ValidationError('DOCX 解压后过大')
            raw = archive.read('word/document.xml')
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValidationError('文档 XML 包含不支持的声明')
        root = ET.fromstring(raw)
    except (KeyError, zipfile.BadZipFile, ET.ParseError):
        raise ValidationError('DOCX 文件格式无效') from None
    body = root.find(W+'body')
    if body is None:
        raise ValidationError('DOCX 缺少正文')
    chunks = []
    paragraph = table = 0
    for node in body:
        if node.tag == W+'p':
            paragraph += 1
            text = ''.join(element.text or '' for element in node.iter(W+'t')).strip()
            if text:
                chunks.append((paragraph, paragraph, text, f'正文第{paragraph}段'))
        elif node.tag == W+'tbl':
            table += 1
            for row_no, row in enumerate(node.findall(W+'tr'), 1):
                values = [''.join(element.text or '' for element in cell.iter(W+'t')).strip()
                          for cell in row.findall(W+'tc')]
                if any(values):
                    chunks.append((row_no, row_no, ' | '.join(values), f'表格{table}第{row_no}行'))
    if not chunks:
        raise ValidationError('DOCX 正文没有可提取文本')
    return chunks
