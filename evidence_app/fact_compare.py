"""Conservative numeric comparisons; unknown context remains a review clue."""
import re
from decimal import Decimal
from itertools import combinations

PATTERN=re.compile(r'(营业收入|合同金额|回款率|付款期限|交付周期|员工人数)\s*(?:为|是|：|:|=)\s*([0-9]+(?:\.[0-9]+)?)\s*(万元|亿元|元|%|％|天|人)')
RULE=re.compile(r'(不允许|禁止|不得|允许)\s*(远程办公|转包|加班|报销|外包)')
UNIT={'元':('金额',Decimal(1)),'万元':('金额',Decimal(10000)),'亿元':('金额',Decimal(100000000)),
      '%':('百分比',Decimal(1)),'％':('百分比',Decimal(1)),'天':('天',Decimal(1)),'人':('人',Decimal(1))}


def compare(sources):
    facts=[]
    for source in sources:
        for match in PATTERN.finditer(source['content']):
            metric,raw,unit=match.groups(); dimension,multiplier=UNIT[unit]
            facts.append({'metric':metric,'value':str(Decimal(raw)*multiplier),'unit':dimension,
                          'display':raw+unit,'quote':match.group(0),'source_id':source['id'],
                          'document_id':source['document_id'],'sha256':source['sha256'],
                          'metadata':source.get('metadata',{})})
            if len(facts)>=200: break
        if len(facts)>=200: break
    for source in sources:
        for match in RULE.finditer(source['content']):
            verb,topic=match.groups()
            facts.append({'metric':topic,'value':'1' if verb=='允许' else '0','unit':'规则',
                          'display':match.group(0),'quote':match.group(0),'source_id':source['id'],
                          'document_id':source['document_id'],'sha256':source['sha256'],
                          'metadata':source.get('metadata',{})})
            if len(facts)>=200: break
        if len(facts)>=200: break
    results=[]
    for left,right in combinations(facts,2):
        if left['metric']!=right['metric'] or left['unit']!=right['unit'] or Decimal(left['value'])==Decimal(right['value']):
            continue
        if left['document_id']==right['document_id'] or left['sha256']==right['sha256']:
            continue
        a,b=left['metadata'],right['metadata']
        if any(a.get(key) and b.get(key) and a[key]!=b[key] for key in ('entity','period','scope')):
            continue
        related=a.get('supersedes')==right['document_id'] or b.get('supersedes')==left['document_id']
        complete=all(a.get(key) and b.get(key) for key in ('entity','period','scope'))
        state='版本差异' if related else '待核对差异' if complete else '可能存在差异'
        results.append({'metric':left['metric'],'state':state,'left':left,'right':right})
    return results[:100]
