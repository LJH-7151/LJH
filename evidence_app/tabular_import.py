"""Bounded CSV ingestion with physical line locations and explicit encoding."""
import csv
from datetime import datetime, timedelta
import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET
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


def parse_xlsx(content, header_row=1, sheet_name=None):
    """Parse a chosen worksheet using cached formula values and exact row numbers."""
    if not isinstance(content, bytes) or not content or len(content) > MAX_BYTES:
        raise ValidationError('XLSX 文件为空或超过24 MB')
    if type(header_row) is not int or not 1 <= header_row <= 100:
        raise ValidationError('表头行必须在1至100之间')
    s = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    r = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    rel = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 5000 or sum(x.file_size for x in members) > 128*1024*1024:
                raise ValidationError('XLSX 解压后过大')
            def xml(path):
                data = archive.read(path)
                if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                    raise ValidationError('表格包含不支持的 XML 声明')
                return ET.fromstring(data)
            book = xml('xl/workbook.xml')
            relationships = xml('xl/_rels/workbook.xml.rels')
            sheets = book.findall(s+'sheets/'+s+'sheet')
            choices = [sheet for sheet in sheets if sheet.get('state', 'visible') == 'visible']
            selected = next((sheet for sheet in choices if sheet.get('name') == sheet_name), None) if sheet_name else (choices[0] if choices else None)
            if selected is None:
                raise ValidationError('找不到所选的可见工作表')
            name = selected.get('name')
            target = next((item.get('Target') for item in relationships.findall(rel+'Relationship')
                           if item.get('Id') == selected.get(r+'id') and item.get('TargetMode') != 'External'), None)
            if not target:
                raise ValidationError('工作表位置无效')
            path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
            if not path.startswith('xl/'):
                raise ValidationError('工作表位置无效')
            worksheet = xml(path)
            if worksheet.find(s+'mergeCells') is not None:
                raise ValidationError('工作表包含合并单元格，请拆分后导入')
            if any(row.get('hidden') in ('1','true') for row in worksheet.findall(s+'sheetData/'+s+'row')) or any(col.get('hidden') in ('1','true') for col in worksheet.findall(s+'cols/'+s+'col')):
                raise ValidationError('工作表包含隐藏行或列，请先检查并取消隐藏')
            date_styles=set()
            try:
                styles=xml('xl/styles.xml')
                custom={int(item.get('numFmtId')):item.get('formatCode','') for item in styles.findall(s+'numFmts/'+s+'numFmt')}
                for index,item in enumerate(styles.findall(s+'cellXfs/'+s+'xf')):
                    fmt=int(item.get('numFmtId','0'))
                    code=re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', '', custom.get(fmt,'')).lower()
                    if fmt in set(range(14,23)) | {45,46,47} or (code and any(c in code for c in 'yd') and any(c in code for c in 'md')):
                        date_styles.add(index)
            except KeyError:
                pass
            workbook_properties=book.find(s+'workbookPr')
            epoch=datetime(1904,1,1) if workbook_properties is not None and workbook_properties.get('date1904') in ('1','true') else datetime(1899,12,30)
            try:
                strings_xml = xml('xl/sharedStrings.xml')
                strings = [''.join(x.text or '' for x in node.iter(s+'t')) for node in strings_xml.findall(s+'si')]
            except KeyError:
                strings = []
            columns, rows = None, []
            for row in worksheet.findall(s+'sheetData/'+s+'row'):
                number = int(row.get('r', '0'))
                if number < header_row:
                    continue
                cells = {}
                for cell in row.findall(s+'c'):
                    match = re.fullmatch(r'([A-Z]+)([1-9][0-9]*)', cell.get('r',''))
                    if not match or int(match.group(2)) != number:
                        raise ValidationError('单元格位置无效')
                    column = 0
                    for ch in match.group(1):
                        column = column * 26 + ord(ch) - ord('A') + 1
                    if column > MAX_COLUMNS:
                        raise ValidationError('工作表最多200列')
                    raw = cell.find(s+'v')
                    if cell.find(s+'f') is not None and (raw is None or raw.text is None):
                        raise ValidationError('公式缺少缓存值，请重新计算并保存')
                    kind = cell.get('t', 'n')
                    if kind == 'inlineStr':
                        value = ''.join(x.text or '' for x in cell.iter(s+'t'))
                    elif raw is None or raw.text is None:
                        value = ''
                    elif kind == 's':
                        value = strings[int(raw.text)]
                    elif kind == 'e':
                        raise ValidationError('工作表包含错误值')
                    else:
                        value = raw.text
                        if kind == 'n' and int(cell.get('s','0')) in date_styles:
                            serial=float(value)
                            if not 0<=serial<=2958465: raise ValidationError('日期数值超出范围')
                            adjusted=serial+1 if epoch.year==1899 and 0<serial<60 else serial
                            stamp=epoch+timedelta(days=adjusted)
                            value=stamp.date().isoformat() if stamp.time().isoformat()=='00:00:00' else stamp.isoformat(timespec='seconds')
                    if len(value) > MAX_FIELD or column in cells:
                        raise ValidationError('单元格过长或位置重复')
                    cells[column] = value
                if number == header_row:
                    width = max(cells, default=0)
                    columns = tuple(cells.get(i, '').strip() for i in range(1, width+1))
                    if not columns or any(not c for c in columns) or len(columns) != len(set(columns)):
                        raise ValidationError('表头必须非空且唯一')
                    continue
                if not any(value.strip() for value in cells.values()):
                    continue
                if columns is None or any(index > len(columns) for index in cells):
                    raise ValidationError('数据列超出表头或找不到表头')
                if len(rows) >= MAX_ROWS:
                    raise ValidationError('单表最多2万行')
                rows.append(SourceRow(f'{name} 第{number}行',
                                      {column:cells.get(i, '') for i, column in enumerate(columns, 1)}))
    except ValidationError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError, ValueError, TypeError, OverflowError):
        raise ValidationError('XLSX 文件格式无效') from None
    if columns is None:
        raise ValidationError('找不到指定表头行')
    return Table(columns, tuple(rows), 'xlsx:'+name)
