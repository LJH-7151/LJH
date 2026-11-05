"""Versioned order/refund ledger; calculations use exact decimal amounts."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from .common import ValidationError, digest, now, uid

ALIASES={
    'order_id':('订单号','订单编号'),'line_id':('明细号','明细编号','商品行号'),
    'refund_id':('退款号','退款编号'),'sku':('商品编码','SKU'),
    'amount':('金额','支付金额','退款金额'),'quantity':('数量','商品数量'),
    'paid_at':('支付时间','支付日期'),'refunded_at':('退款时间','退款日期'),
    'status':('状态','订单状态','退款状态'),'currency':('币种','货币'),
}
STATUS={'已支付':'paid','已完成':'completed','已退款':'refunded','待支付':'pending',
        '待退款':'pending','待处理':'pending','已取消':'cancelled','已完成退款':'completed'}


def map_columns(rows):
    """Map common labels to canonical fields without guessing among duplicates."""
    if not rows: return rows
    headers=list(rows[0]); mapping={}
    for field,aliases in ALIASES.items():
        matches=[name for name in headers if name.casefold() in {item.casefold() for item in (field,*aliases)}]
        if len(matches)>1: raise ValidationError('字段映射有歧义：'+field)
        if matches: mapping[field]=matches[0]
    output=[]
    for row in rows:
        item={field:row.get(name,'') for field,name in mapping.items()}
        if 'status' in item:
            state=str(item['status']).strip(); item['status']=STATUS.get(state,state.lower())
        if item.get('currency') in ('人民币','元'): item['currency']='CNY'
        output.append(item)
    return output


def money(value):
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number<0 or number.as_tuple().exponent < -2 or len(number.as_tuple().digits)>18 or number.adjusted()>15: raise InvalidOperation
        return number
    except (InvalidOperation,ValueError):
        raise ValidationError('金额必须为非负数且最多两位小数') from None


def date(value):
    if not isinstance(value,str): raise ValidationError('日期无效')
    try:
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed=parsed.astimezone(timezone(timedelta(hours=8)))
        return parsed.date().isoformat()
    except ValueError: raise ValidationError('日期需为 ISO 格式') from None


def key(record, fields):
    values=[]
    for field in fields:
        value=record.get(field)
        if not isinstance(value,str) or not value.strip() or len(value)>200 or '\x00' in value:
            raise ValidationError('业务编号无效')
        values.append(value.strip())
    return json.dumps(values,ensure_ascii=False,separators=(',',':'))


class SalesLedger:
    def __init__(self,store):
        self.store=store
        with store.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS ledger_records (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, business_key TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS ledger_heads (
                kind TEXT NOT NULL, business_key TEXT NOT NULL, record_id TEXT NOT NULL REFERENCES ledger_records(id),
                PRIMARY KEY(kind,business_key)
              );
              CREATE TABLE IF NOT EXISTS ledger_snapshots (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS ledger_batches (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, namespace TEXT NOT NULL,
                source_sha256 TEXT, counts TEXT NOT NULL, created_at TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS ledger_lineage (
                batch_id TEXT NOT NULL REFERENCES ledger_batches(id),
                record_id TEXT NOT NULL REFERENCES ledger_records(id), location TEXT NOT NULL
              );
            ''')
            columns={row['name'] for row in db.execute('PRAGMA table_info(ledger_batches)')}
            if 'source_name' not in columns: db.execute('ALTER TABLE ledger_batches ADD COLUMN source_name TEXT')

    def import_records(self,kind,namespace,records,allow_update=False,source_bytes=None,locations=None,source_name=None):
        if kind not in ('orders','refunds') or not isinstance(namespace,str) or not namespace.strip() or len(namespace)>100:
            raise ValidationError('导入类型或来源无效')
        namespace=namespace.strip()
        if not isinstance(records,list) or not 1<=len(records)<=20000:
            raise ValidationError('每批应包含1至2万行')
        if type(allow_update) is not bool: raise ValidationError('更新选项无效')
        if locations is not None and (not isinstance(locations,list) or len(locations)!=len(records) or any(not isinstance(x,str) or not x or len(x)>500 for x in locations)):
            raise ValidationError('来源行位置无效')
        if source_name is not None and (not isinstance(source_name,str) or not source_name or len(source_name)>180 or '/' in source_name or '\\' in source_name):
            raise ValidationError('来源文件名无效')
        sha=None
        if source_bytes is not None:
            if not isinstance(source_bytes,bytes) or not source_bytes or len(source_bytes)>24*1024*1024:
                raise ValidationError('来源文件无效')
            sha=digest(source_bytes); path=self.store.blob(sha)
            if not path.exists():
                try:
                    with path.open('xb') as stream: stream.write(source_bytes)
                except FileExistsError: pass
            if digest(path.read_bytes())!=sha: raise RuntimeError('原件完整性校验失败')
        prepared=[]; seen=set()
        for row in records:
            if not isinstance(row,dict): raise ValidationError('记录格式无效')
            fields=('order_id','line_id') if kind=='orders' else ('refund_id',)
            business_key=key({**row,'namespace':namespace},('namespace',)+fields)
            if business_key in seen: raise ValidationError('同批次存在重复业务编号')
            seen.add(business_key)
            payload={'namespace':namespace,'amount':format(money(row.get('amount')),'.2f'),'currency':row.get('currency','CNY') or 'CNY'}
            if payload['currency']!='CNY': raise ValidationError('当前仅支持人民币')
            if kind=='orders':
                payload.update({'order_id':row['order_id'].strip(),'line_id':row['line_id'].strip(),'sku':row.get('sku'),
                                'paid_at':date(row.get('paid_at')),'status':row.get('status')})
                payload['quantity']=format(money(row.get('quantity') or '1').normalize(),'f')
                if Decimal(payload['quantity'])<=0: raise ValidationError('商品数量必须大于零')
                if not isinstance(payload['sku'],str) or not payload['sku'].strip() or payload['status'] not in ('paid','completed','refunded','pending','cancelled'):
                    raise ValidationError('订单商品或状态无效')
                payload['sku']=payload['sku'].strip()
            else:
                key(row,('order_id','line_id'))
                payload.update({'refund_id':row['refund_id'].strip(),'order_id':row['order_id'].strip(),'line_id':row['line_id'].strip(),
                                'refunded_at':date(row.get('refunded_at')),'status':row.get('status')})
                if payload['status'] not in ('completed','pending','cancelled'): raise ValidationError('退款状态无效')
            prepared.append((business_key,payload))
        added=duplicate=updated=0; lineage=[]
        with self.store.connect() as db:
            for index,(business_key,payload) in enumerate(prepared):
                old=db.execute('''SELECT r.id,r.payload FROM ledger_heads h JOIN ledger_records r ON r.id=h.record_id
                                  WHERE h.kind=? AND h.business_key=?''',(kind,business_key)).fetchone()
                content=json.dumps(payload,ensure_ascii=False,sort_keys=True)
                if old and old['payload']==content:
                    duplicate+=1; lineage.append((old['id'],locations[index] if locations else str(index+1))); continue
                if old and not allow_update: raise ValidationError('已存在不同版本，需明确允许更新')
                identifier=uid('ledger')
                db.execute('INSERT INTO ledger_records VALUES (?,?,?,?,?)',(identifier,kind,business_key,content,now()))
                db.execute('INSERT OR REPLACE INTO ledger_heads VALUES (?,?,?)',(kind,business_key,identifier))
                lineage.append((identifier,locations[index] if locations else str(index+1)))
                if old: updated+=1
                else: added+=1
            heads=db.execute('''SELECT h.kind,r.payload FROM ledger_heads h JOIN ledger_records r ON r.id=h.record_id''').fetchall()
            orders={key(json.loads(row['payload']),('namespace','order_id','line_id')):json.loads(row['payload']) for row in heads if row['kind']=='orders'}
            totals={}
            for row in heads:
                if row['kind']!='refunds': continue
                refund=json.loads(row['payload']); order_key=key(refund,('namespace','order_id','line_id'))
                if order_key not in orders: raise ValidationError('退款缺少对应订单')
                order=orders[order_key]
                if refund['refunded_at']<order['paid_at']: raise ValidationError('退款不能早于支付')
                if refund['status']=='completed' and order['status'] not in ('paid','completed','refunded'):
                    raise ValidationError('已完成退款的订单必须已支付')
                if refund['status']=='completed': totals[order_key]=totals.get(order_key,Decimal(0))+money(refund['amount'])
            if any(amount>money(orders[k]['amount']) for k,amount in totals.items()):
                raise ValidationError('累计退款超过订单金额')
            batch=uid('batch'); counts={'added':added,'duplicate':duplicate,'updated':updated}
            db.execute('INSERT INTO ledger_batches (id,kind,namespace,source_sha256,counts,created_at,source_name) VALUES (?,?,?,?,?,?,?)',(batch,kind,namespace,sha,json.dumps(counts),now(),source_name))
            db.executemany('INSERT INTO ledger_lineage VALUES (?,?,?)',[(batch,identifier,location) for identifier,location in lineage])
        return counts | {'batch_id':batch,'source_sha256':sha}

    def calculate(self,start,end,refund_cutoff,refund_mode='cohort',namespace='',skus=None,baseline_start=None,baseline_end=None):
        start,end,refund_cutoff=date(start),date(end),date(refund_cutoff)
        if start>=end: raise ValidationError('结束日期必须晚于开始日期')
        if refund_mode not in ('cohort','occurred') or not isinstance(namespace,str) or len(namespace)>100:
            raise ValidationError('退款口径或来源无效')
        namespace=namespace.strip()
        if skus is None: skus=[]
        if not isinstance(skus,list) or len(skus)>200 or any(not isinstance(sku,str) or not sku or len(sku)>200 for sku in skus):
            raise ValidationError('商品范围无效')
        skus=[sku.strip() for sku in skus]
        if any(not sku for sku in skus): raise ValidationError('商品范围无效')
        if bool(baseline_start) != bool(baseline_end): raise ValidationError('基准期间需要同时填写开始和结束日期')
        baseline=None
        if baseline_start and baseline_end:
            baseline=self.calculate(baseline_start,baseline_end,refund_cutoff,refund_mode,namespace,skus)
        with self.store.connect() as db:
            heads=db.execute('''SELECT h.kind,r.id,r.payload FROM ledger_heads h JOIN ledger_records r ON r.id=h.record_id''').fetchall()
        orders=[(row['id'],json.loads(row['payload'])) for row in heads if row['kind']=='orders']
        refunds=[(row['id'],json.loads(row['payload'])) for row in heads if row['kind']=='refunds']
        eligible=[(identifier,row) for identifier,row in orders if row['status'] in ('paid','completed','refunded') and (not namespace or row['namespace']==namespace) and (not skus or row['sku'] in skus)]
        chosen=[(identifier,row) for identifier,row in eligible if start<=row['paid_at']<end]
        order_keys={key(row,('namespace','order_id','line_id')) for _,row in chosen}
        eligible_keys={key(row,('namespace','order_id','line_id')) for _,row in eligible}
        if refund_mode=='cohort':
            chosen_refunds=[(identifier,row) for identifier,row in refunds if row['status']=='completed' and row['refunded_at']<=refund_cutoff and key(row,('namespace','order_id','line_id')) in order_keys]
        else:
            chosen_refunds=[(identifier,row) for identifier,row in refunds if row['status']=='completed' and start<=row['refunded_at']<end and key(row,('namespace','order_id','line_id')) in eligible_keys]
        paid=sum((money(row['amount']) for _,row in chosen),Decimal(0))
        refunded=sum((money(row['amount']) for _,row in chosen_refunds),Decimal(0))
        related_keys={key(row,('namespace','order_id','line_id')) for _,row in chosen_refunds}
        prior_orders=[(identifier,row) for identifier,row in eligible if key(row,('namespace','order_id','line_id')) in related_keys-order_keys]
        order_count=len({(row['namespace'],row['order_id']) for _,row in chosen})
        baseline_net=Decimal(baseline['net']) if baseline else None
        growth=((paid-refunded-baseline_net)/baseline_net*100).quantize(Decimal('0.01')) if baseline_net is not None and baseline_net>0 else None
        snapshot={'id':uid('snapshot'),'start':start,'end':end,'refund_cutoff':refund_cutoff,'refund_mode':refund_mode,'namespace':namespace,'skus':skus,'paid':str(paid),
                  'refunds':str(refunded),'net':str(paid-refunded),'order_lines':len(chosen),
                  'order_count':order_count,'average_order_value':str((paid/order_count).quantize(Decimal('0.01'))) if order_count else None,
                  'quantity':str(sum((Decimal(row.get('quantity','1')) for _,row in chosen),Decimal(0))),
                  'baseline_id':baseline['id'] if baseline else None,'baseline_net':str(baseline_net) if baseline else None,
                  'growth_percent':str(growth) if growth is not None else None,
                  'record_ids':[identifier for identifier,_ in chosen+prior_orders+chosen_refunds],
                  'prior_order_ids':[identifier for identifier,_ in prior_orders], 'created_at':now(),
                  'note':('按支付日期选择订单，扣除截至指定日期的已完成退款。' if refund_mode=='cohort' else '按支付日期选择订单，扣除期间发生的已完成退款。')+'金额单位为人民币元。'}
        with self.store.connect() as db:
            db.execute('INSERT INTO ledger_snapshots VALUES (?,?,?)',(snapshot['id'],json.dumps(snapshot,ensure_ascii=False),snapshot['created_at']))
        return snapshot

    def history(self):
        with self.store.connect() as db:
            rows=db.execute('SELECT payload FROM ledger_snapshots ORDER BY rowid DESC LIMIT 100').fetchall()
        return [json.loads(row['payload']) for row in rows]

    def get(self,identifier):
        with self.store.connect() as db:
            row=db.execute('SELECT payload FROM ledger_snapshots WHERE id=?',(identifier,)).fetchone()
        if not row: raise LookupError('核算快照不存在')
        return json.loads(row['payload'])

    def sources(self,identifier):
        snapshot=self.get(identifier)
        records=[]
        with self.store.connect() as db:
            for record_id in snapshot['record_ids']:
                row=db.execute('SELECT kind,payload FROM ledger_records WHERE id=?',(record_id,)).fetchone()
                if row is None: raise RuntimeError('快照关联记录不存在')
                origins=db.execute('''SELECT l.location,b.id,b.source_sha256,b.source_name FROM ledger_lineage l
                    JOIN ledger_batches b ON b.id=l.batch_id WHERE l.record_id=?''',(record_id,)).fetchall()
                records.append({'id':record_id,'kind':row['kind'],'values':json.loads(row['payload']),
                                'origins':[dict(origin) for origin in origins]})
        return records

    def recompute(self,identifier):
        snapshot=self.get(identifier); records=self.sources(identifier); prior=set(snapshot.get('prior_order_ids',[]))
        orders=[row for row in records if row['kind']=='orders' and row['id'] not in prior]
        refunds=[row for row in records if row['kind']=='refunds']
        paid=sum((money(row['values']['amount']) for row in orders),Decimal(0))
        refunded=sum((money(row['values']['amount']) for row in refunds),Decimal(0))
        matches=(paid==Decimal(snapshot['paid']) and refunded==Decimal(snapshot['refunds']) and paid-refunded==Decimal(snapshot['net']))
        return {'id':identifier,'paid':str(paid),'refunds':str(refunded),'net':str(paid-refunded),
                'matches':matches,'record_count':len(records)}
