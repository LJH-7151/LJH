"""Reproducible summaries for explicitly identified management metrics."""
import re

from .common import ValidationError

_METRICS = (
    (r'经营|发展|收入|营收|财务|利润', ('营业收入（元）', '模拟营业收入（元）'), 'sum'),
    (r'经营|发展|成本|财务|利润', ('营业成本（元）', '模拟营业成本（元）'), 'sum'),
    (r'经营|发展|利润|财务', ('净利润（元）', '模拟净利润（元）'), 'sum'),
    (r'经营|发展|合同|签约', ('合同金额（元）', '签约实际（元）'), 'sum'),
    (r'经营|发展|回款', ('同期回款金额（元）', '回款实际（元）', '回款金额（元）'), 'sum'),
    (r'未回款|应收|余额', ('未回款金额（元）',), 'sum'),
    (r'经营|发展|成本|费用|财务|利润', ('费用金额（元）', '经营费用样本（元）'), 'sum'),
    (r'发展|交付|周期|效率', ('交付周期（天）', '实际周期（天）', '平均交付周期（天）'), 'average'),
    (r'客户|发展|经营', ('签约客户数（户）',), 'sum'),
    (r'客户|发展|经营|获客', ('新增成交客户数（户）',), 'sum'),
    (r'客户|发展|经营|留存', ('月成交客户留存率（%）',), 'average'),
    (r'客户|发展|经营|获客', ('获客成本估算（元/户）',), 'average'),
    (r'客户|发展|经营|推广|获客', ('推广费用/新增客户（元/户）',), 'average'),
)


def calculate(workspace, question, selected_ids, attached):
    available = [t for t in workspace.tables.list() if not t['metadata'].get('archived')
                 and (selected_ids is None or t['id'] in selected_ids)]
    existing = {(workspace.tables.result(i)['table_id'], workspace.tables.result(i)['measure']) for i in attached}
    calculated = []
    for pattern, columns, operation in _METRICS:
        if not re.search(pattern, question):
            continue
        candidates = []
        for table in available:
            group = next((c for c in ('期间', '签约期间', '月份') if c in table['columns']), None)
            if not group:
                continue
            for rank, column in enumerate(columns):
                if column in table['columns'] and (table['id'], column) not in existing:
                    candidates.append((rank, table['row_count'], table['name'], table, column, group))
        if not candidates:
            continue
        _, _, _, table, column, group = min(candidates, key=lambda c: c[:3])
        if column in ('月成交客户留存率（%）', '获客成本估算（元/户）', '推广费用/新增客户（元/户）'):
            # A mean of already computed rates is only meaningful when each period has one observation.
            with workspace.store.connect() as db:
                rows = db.execute('SELECT values_json FROM enterprise_table_rows WHERE table_id=?', (table['id'],)).fetchall()
            import json
            values = [json.loads(r['values_json']) for r in rows]
            periods = [str(v.get(group, '')) for v in values if str(v.get(column, '')).strip()]
            if len(periods) != len(set(periods)):
                continue
        try:
            result = workspace.tables.calculate(table['id'], {'operation': operation, 'measure': column, 'group_by': group})
        except ValidationError:
            continue
        calculated.append(result['id'])
        existing.add((table['id'], column))
    if re.search(r'客户|渠道|产品|销售|发展|经营', question):
        candidates = [t for t in available if {'订单编号', '签约日期', '产品', '渠道', '合同金额（元）'} <= set(t['columns'])]
        if candidates:
            table = min(candidates, key=lambda t: (t['row_count'], t['name']))
            for group in ('产品', '渠道'):
                try:
                    result = workspace.tables.calculate(table['id'], {'operation':'sum', 'measure':'合同金额（元）', 'group_by':group})
                except ValidationError:
                    continue
                calculated.append(result['id'])
    if re.search(r'回款|合同|余额|逾期|发展|经营', question):
        candidates = [t for t in available if {'订单编号', '余额状态', '未回款金额（元）'} <= set(t['columns'])]
        if candidates:
            table = min(candidates, key=lambda t: (t['row_count'], t['name']))
            try:
                result = workspace.tables.calculate(table['id'], {'operation':'sum', 'measure':'未回款金额（元）', 'group_by':'余额状态'})
            except ValidationError:
                pass
            else:
                calculated.append(result['id'])
    return calculated
