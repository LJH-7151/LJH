import unittest
from evidence_app.fact_compare import compare


def source(identifier,text,**metadata):
    return {'id':identifier,'document_id':identifier,'sha256':identifier,'content':text,'metadata':metadata}


class FactComparisonTests(unittest.TestCase):
    def test_policy_difference_is_version_when_linked(self):
        common={'entity':'虚构公司','period':'2026-10','scope':'全公司'}
        a=source('a','制度允许远程办公',**common)
        b=source('b','新制度禁止远程办公',**common,supersedes='a')
        result=compare([a,b])
        self.assertEqual(result[0]['metric'],'远程办公')
        self.assertEqual(result[0]['state'],'版本差异')
    def test_units_context_and_versions(self):
        common={'entity':'虚构公司','period':'2026-10','scope':'全公司'}
        a=source('a','合同金额为1万元',**common)
        same=source('b','合同金额为10000.0元',**common)
        different=source('c','合同金额为11000元',**common)
        version=source('d','合同金额为12000元',**common,supersedes='a')
        self.assertEqual(compare([a,same]),[])
        self.assertEqual(compare([a,different])[0]['state'],'待核对差异')
        self.assertEqual(compare([a,version])[0]['state'],'版本差异')
        self.assertEqual(compare([a,source('x','合同金额为12000元',entity='其他公司')]),[])
        self.assertEqual(compare([a,source('x','合同金额为12000元')])[0]['state'],'可能存在差异')


if __name__=='__main__': unittest.main()
