"""Deterministic table calculations with explicit source-row provenance."""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import re

from .common import ValidationError


@dataclass(frozen=True)
class SourceRow:
    location: str
    values: dict


def _number(value):
    try:
        text=str(value).strip().replace('，',',')
        if text.endswith(('%','％')): text=text[:-1]
        if ',' in text and not re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?',text):
            raise InvalidOperation
        number = Decimal(text.replace(',',''))
        if not number.is_finite() or len(number.as_tuple().digits)>18 or abs(number.adjusted())>15:
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError):
        raise ValidationError('数值列包含无效数字') from None


def aggregate(rows, *, columns, operation, measure=None, group_by=None, filters=(), ignore_invalid=False):
    """Calculate from one table; never infer currency, units, or cross-table joins.

    The caller supplies source locations and unique columns; returned groups keep
    every contributing location so exported answers can be checked independently.
    """
    columns = tuple(columns)
    if not columns or len(set(columns)) != len(columns):
        raise ValidationError('列名不能为空或重复')
    if any(not isinstance(column, str) or not column.strip() for column in columns):
        raise ValidationError('列名不能为空或重复')
    if operation not in ('sum', 'average', 'min', 'max', 'count'):
        raise ValidationError('统计方式无效')
    if operation != 'count' and measure not in columns:
        raise ValidationError('数值列不存在')
    if group_by is not None and group_by not in columns:
        raise ValidationError('分组列不存在')
    if not isinstance(filters,(list,tuple)) or len(filters) > 8:
        raise ValidationError('最多使用8个筛选条件')
    for item in filters:
        if not isinstance(item, dict) or item.get('column') not in columns or item.get('operator') not in ('equals', 'contains','gte','lte') or not isinstance(item.get('value'), str):
            raise ValidationError('筛选条件无效')

    def matches(row, condition):
        actual=str(row.values.get(condition['column'], ''))
        expected=condition['value']
        operator=condition['operator']
        if operator=='equals': return actual==expected
        if operator=='contains': return expected in actual
        try:
            right = _number(expected)
        except ValidationError:
            left, right = actual, expected
        else:
            try: left = _number(actual)
            except ValidationError: return False
        return left>=right if operator=='gte' else left<=right

    groups = defaultdict(list)
    selected = missing = invalid = 0
    missing_locations=[]; invalid_locations=[]
    seen_locations = set()
    for row in rows:
        if not isinstance(row, SourceRow) or not row.location or row.location in seen_locations:
            raise ValidationError('来源行位置不能为空或重复')
        seen_locations.add(row.location)
        if any(not matches(row, condition) for condition in filters):
            continue
        selected += 1
        if operation == 'count':
            value = Decimal(1)
        else:
            raw = row.values.get(measure)
            if raw is None or not str(raw).strip():
                missing += 1
                missing_locations.append(row.location)
                continue
            try:
                value = _number(raw)
            except ValidationError:
                invalid += 1
                invalid_locations.append(row.location)
                if not ignore_invalid:
                    raise
                continue
        key = str(row.values.get(group_by, '')) if group_by is not None else '全部'
        groups[key].append((value, row.location))
        if len(groups) > 500:
            raise ValidationError('分组超过500组')
    result = []
    for key, entries in sorted(groups.items()):
        values = [value for value, _ in entries]
        with localcontext() as context:
            context.prec=80
            if operation in ('sum', 'count'):
                value = sum(values, Decimal(0))
            elif operation == 'average':
                value = sum(values, Decimal(0)) / len(values)
            elif operation == 'min':
                value = min(values)
            else:
                value = max(values)
        result.append({'group': key, 'value': str(value), 'count': len(entries),
                       'source_locations': [location for _, location in entries]})
    return {'operation': operation, 'measure': measure, 'group_by': group_by,
            'selected': selected, 'missing': missing, 'invalid': invalid, 'groups': result,
            'missing_locations':missing_locations,'invalid_locations':invalid_locations,
            'filters':list(filters),'ignore_invalid':ignore_invalid}
