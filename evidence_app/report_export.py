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


def word_report(archive,reviews=()):
    paragraphs=[archive['question'], '证据分析档案 · '+archive['created_at']]
    for conclusion in archive['conclusions']:
        paragraphs.append(conclusion['text'])
        for citation in conclusion['citations']:
            source=next((item for item in archive['sources'] if item['id']==citation['id']),None)
            if source: paragraphs.append(f"来源：《{source['title']}》{source['location']}，SHA-256 {source['sha256']}：{citation['quote']}")
    for issue in archive.get('conflicts',[]):
        paragraphs.append(f"{issue.get('state','待核对')}：{issue.get('metric','')}，{issue['left']['display']} / {issue['right']['display']}")
        paragraphs.append('原文：'+issue['left']['quote']+'；'+issue['right']['quote'])
    for issue in archive.get('legacy_conflicts',[]):
        paragraphs.append(f"{issue.get('state','待核对')}：{issue.get('metric','')} {issue.get('note','')}")
    for gap in archive.get('gaps',[]):
        paragraphs.append(f"材料缺口：{gap.get('title','')} {gap.get('reason','')} {gap.get('material','')}")
    for action in archive.get('actions',[]): paragraphs.append('建议：'+action.get('text',''))
    for review in reviews:
        paragraphs.append(f"核对记录：{review['created_at']} {review['status']} {review['note']}")
    paragraphs.extend(archive['limitations'])
    body=''.join('<w:p><w:r><w:t xml:space="preserve">'+_text(value)+'</w:t></w:r></w:p>' for value in paragraphs)
    return _zip({
        '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/document.xml':'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+body+'</w:body></w:document>',
    })


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
