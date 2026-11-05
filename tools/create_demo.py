"""Create fictional demo data in a new empty directory."""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence_app.service import Workspace


def main():
    parser=argparse.ArgumentParser(description='创建虚构企业演示资料')
    parser.add_argument('directory',type=Path,help='新的空目录')
    args=parser.parse_args()
    path=args.directory.resolve()
    if path.exists() and any(path.iterdir()):
        parser.error('演示目录必须为空，避免覆盖已有资料')
    workspace=Workspace(path)
    shared={'entity':'XX公司（虚构）','scope':'全公司','period':'2026-10'}
    docs=[]
    for name,text,category in [
        ('公司简介.txt','XX公司是虚构的企业服务公司，所有客户、金额和业务均为合成数据。','企业介绍'),
        ('财务月报.txt','2026年10月合同金额为100万元。付款期限为30天。','经营报表'),
        ('运营复盘.txt','2026年10月合同金额为110万元。付款期限为60天。差异为演示中有意设置。','业务复盘'),
        ('经营会议.txt','请财务、运营和法务核对合同金额与付款期限，检查统计口径和签署版本。','会议纪要'),
        ('合同摘要.txt','示例项目付款期限为30天；以签署合同及补充协议为准。','合同协议'),
        ('办公制度.txt','示例办公制度应按生效日期核对适用版本。','制度流程'),
        ('交付说明.txt','项目交付应保存验收记录，项目付款期限为60天，需核对补充协议。','项目资料'),
    ]:
        result=workspace.upload(name,text.encode('utf-8'))
        identifier=result['document']['id']; docs.append(identifier)
        workspace.catalog.update(identifier,shared | {'category':category,'source':'人工合成演示'})
    output=io.StringIO(newline=''); writer=csv.writer(output,lineterminator='\n')
    writer.writerow(['订单编号','期间','部门','客户编号','合同金额（元）','回款金额（元）'])
    for month in range(1,11):
        for number in range(1,201):
            amount=10000+((month*23+number*17)%100)*100
            writer.writerow([f'XX-{month:02d}-{number:04d}',f'2026-{month:02d}',
                             ['直销','渠道','线上','转介绍'][number%4],f'虚构客户{number%80:03d}',amount,amount if number%5 else amount//2])
    table=workspace.tables.import_csv('合成订单.csv',output.getvalue().encode('utf-8'))
    calculation=workspace.tables.calculate(table['id'],{'operation':'sum','measure':'合同金额（元）','group_by':'期间'})
    print(json.dumps({'synthetic_only':True,'workspace':str(path),'documents':len(docs),'rows':table['row_count'],
                      'dataset_id':table['id'],'calculation_id':calculation['id']},ensure_ascii=False))


if __name__=='__main__': main()
