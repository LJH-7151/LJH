"""Minimal Office exports; all data is encoded as literal text."""
import io
import json
import zipfile
from xml.sax.saxutils import escape


def _text(value):
    return escape(''.join(ch for ch in str(value) if ch in '\t\n\r' or 0x20<=ord(ch)<=0xD7FF or 0xE000<=ord(ch)<=0xFFFD or 0x10000<=ord(ch)<=0x10FFFF))


def _zip(parts):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,content in parts.items(): archive.writestr(name,content)
    return output.getvalue()


def _bar_chart(groups):
    """A compact, dependency-free PNG bar chart; labels accompany it in the document."""
    import struct
    import zlib
    values = []
    for group in groups[:12]:
        try:
            value = float(group['value'])
            if value < 0 or value != value or value == float('inf'):
                return None
            values.append(value)
        except (KeyError, TypeError, ValueError):
            return None
    if len(values) < 2 or max(values) <= 0:
        return None
    width, height = 600, 220
    canvas = bytearray([255] * (width * height * 3))
    for i, value in enumerate(values):
        x0 = 30 + i * 540 // len(values)
        x1 = 30 + (i + 1) * 540 // len(values) - 6
        y0 = 195 - int(165 * value / max(values))
        for y in range(y0, 195):
            for x in range(x0, x1):
                offset = (y * width + x) * 3
                canvas[offset:offset + 3] = bytes((51, 105, 165))
    raw = b''.join(b'\x00' + canvas[y * width * 3:(y + 1) * width * 3] for y in range(height))
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


def word_report(archive, reviews=()):
    parts = []
    images = []
    def paragraph(text, style=None):
        prop = '<w:pPr><w:pStyle w:val="' + style + '"/></w:pPr>' if style else ''
        parts.append('<w:p>' + prop + '<w:r><w:t xml:space="preserve">' + _text(text) + '</w:t></w:r></w:p>')
    paragraph(archive['question'], 'Title')
    paragraph('经营分析报告 · ' + archive['created_at'], 'Subtitle')
    paragraph('一、分析结论', 'Heading1')
    lookup = {source['id']: source for source in archive['sources']}
    for index, conclusion in enumerate(archive['conclusions'], 1):
        paragraph(str(index) + '. ' + conclusion['text'])
        for citation in conclusion.get('citations', []):
            source = lookup.get(citation.get('id'))
            if source:
                paragraph('依据：《' + source['title'] + '》' + source['location'] + '：' + citation['quote'])
    charts = []
    for source in archive['sources']:
        if source.get('metadata', {}).get('category') != '计算证据':
            continue
        try:
            detail = json.loads(source['content'])
            chart = _bar_chart(detail.get('groups', []))
        except (ValueError, TypeError):
            continue
        if chart:
            charts.append((detail, chart))
    if charts:
        paragraph('二、关键指标', 'Heading1')
        for detail, chart in charts[:4]:
            index = len(images) + 1
            images.append(chart)
            paragraph(str(detail.get('measure') or '指标') + ' · 按' + str(detail.get('group_by') or '分组'))
            parts.append('<w:p><w:r><w:drawing><wp:inline><wp:extent cx="5486400" cy="2011680"/><wp:docPr id="' + str(index) + '" name="Chart ' + str(index) + '"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="' + str(index) + '" name="Chart"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="img' + str(index) + '"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="5486400" cy="2011680"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
            paragraph('；'.join(str(g.get('group')) + '：' + str(g.get('value')) for g in detail.get('groups', [])[:12]))
            paragraph('口径：' + str(detail.get('operation')) + '；有效记录数：' + str(detail.get('selected', '')))
    paragraph('三、行动建议', 'Heading1')
    for action in archive.get('actions', []):
        paragraph('• ' + action.get('text', ''))
    if not archive.get('actions'):
        paragraph('结合上述结论安排责任人、执行时间和复核指标。')
    issues = archive.get('conflicts', []) + archive.get('legacy_conflicts', []) + archive.get('gaps', [])
    if issues or reviews:
        paragraph('四、待核对事项', 'Heading1')
        for issue in issues:
            paragraph(str(issue.get('title') or issue.get('metric') or '来源差异') + '：' + str(issue.get('reason') or issue.get('note') or '请核对期间、范围和口径。'))
        for review in reviews:
            paragraph(str(review['created_at']) + ' · ' + str(review['status']) + ' ? ' + str(review['note']))
    paragraph('分析说明', 'Heading1')
    for note in archive.get('limitations', []):
        paragraph(note)
    ns = ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
    relationships = ''.join('<Relationship Id="img' + str(i) + '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/chart' + str(i) + '.png"/>' for i in range(1, len(images) + 1))
    files = {
        '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/document.xml':'<w:document' + ns + '><w:body>' + ''.join(parts) + '<w:sectPr/></w:body></w:document>',
        'word/styles.xml':'<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:color w:val="666666"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:color w:val="315B85"/><w:sz w:val="28"/></w:rPr></w:style></w:styles>',
        'word/_rels/document.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' + relationships + '</Relationships>',
    }
    for i, chart in enumerate(images, 1):
        files['word/media/chart' + str(i) + '.png'] = chart
    return _zip(files)


def table_report(result, source_rows=()):
    rows=[['分组','结果','有效行数','来源位置','原始行 JSON 片段','片段序号','片段总数']]
    lookup={row['location']:row['values'] for row in source_rows}
    for group in result['groups']:
        for location in group['source_locations']:
            values=lookup.get(location,{})
            detail=json.dumps(values,ensure_ascii=False)
            pieces=[detail[index:index+15000] for index in range(0,len(detail),15000)] or ['']
            for index,piece in enumerate(pieces,1):
                rows.append([group['group'],group['value'],str(group['count']),location,piece,str(index),str(len(pieces))])
    for category,locations in [('缺失值',result.get('missing_locations',[])),('无效值',result.get('invalid_locations',[])),('旧版未分类行',result.get('unattributed_locations',[]))]:
        for location in locations:
            detail=json.dumps(lookup.get(location,{}),ensure_ascii=False)
            pieces=[detail[i:i+15000] for i in range(0,len(detail),15000)] or ['']
            for index,piece in enumerate(pieces,1): rows.append([category,'','',location,piece,str(index),str(len(pieces))])
    rows.extend([['统计方式',result['operation']],['数值列',result.get('measure') or ''],
                 ['来源表 SHA-256',result['table_sha256']],['筛选行数',str(result['selected'])],
                 ['空值',str(result['missing'])],['无效值',str(result['invalid'])],
                 ['筛选条件',json.dumps(result.get('filters',[]),ensure_ascii=False)]])
    rows.extend(result.get('summary_rows',[]))
    xml_rows=[]
    for number,row in enumerate(rows,1):
        cells=''.join(f'<c r="{chr(65+index)}{number}" t="inlineStr"><is><t xml:space="preserve">{_text(value)}</t></is></c>' for index,value in enumerate(row))
        xml_rows.append(f'<row r="{number}">{cells}</row>')
    return _zip({
        '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="统计结果" sheetId="1" r:id="r1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml':'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(xml_rows)+'</sheetData></worksheet>',
    })


def ledger_report(snapshot,records):
    groups=[{'group':record['kind'],'value':record['values'].get('amount',''),'count':1,'source_locations':[record['id']]} for record in records]
    source_rows=[{'location':record['id'],'values':record['values'] | {'来源批次':record['origins']}} for record in records]
    synthetic={'groups':groups,'operation':'订单退款快照','measure':'金额（元）','table_sha256':'多来源',
               'selected':len(records),'missing':0,'invalid':0,'filters':{'start':snapshot['start'],'end':snapshot['end'],
               'refund_cutoff':snapshot['refund_cutoff'],'refund_mode':snapshot.get('refund_mode','cohort'),
               'namespace':snapshot.get('namespace',''),'skus':snapshot.get('skus',[])},
               'summary_rows':[['支付金额',snapshot['paid']],['退款金额',snapshot['refunds']],['净额',snapshot['net']],
                               ['订单数',snapshot.get('order_count','')],['客单价',snapshot.get('average_order_value') or '不可计算'],
                               ['基准净额',snapshot.get('baseline_net') or '未设置'],['变化率（%）',snapshot.get('growth_percent') or '不可计算'],['快照编号',snapshot['id']]]}
    return table_report(synthetic,source_rows)
