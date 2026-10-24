import ast
import datetime as dt
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from financial_integrity import cashflow_ttm, aligned_income, financial_retry_due, current_flow_ttm
from finra_calendar import parse_calendar, available_date, load_calendar

ROOT=Path(__file__).resolve().parents[1]

class CashFlowTests(unittest.TestCase):
    def test_two_quarters_are_not_ttm(self):
        value,meta=cashflow_ttm({'2026-03-31':100,'2026-06-30':250})
        self.assertIsNone(value);self.assertFalse(meta['complete'])
    def test_missing_q2_cannot_make_q3_single(self):
        self.assertIsNone(cashflow_ttm({'2025-03-31':10,'2025-09-30':300,'2025-12-31':400,'2026-03-31':120,'2026-06-30':250})[0])
    def test_adjacent_ytd_across_year(self):
        value,m=cashflow_ttm({'2025-03-31':100,'2025-06-30':250,'2025-09-30':420,'2025-12-31':600,'2026-03-31':120,'2026-06-30':300})
        self.assertEqual(value,650);self.assertTrue(m['complete']);self.assertEqual(m['periods'],['2025Q3','2025Q4','2026Q1','2026Q2'])
    def test_latest_incomplete_must_not_use_older_complete_window(self):
        self.assertIsNone(cashflow_ttm({'2025-03-31':100,'2025-06-30':250,'2025-09-30':420,'2025-12-31':600,'2026-06-30':300})[0])
    def test_invalid_dates_and_nonfinite_not_zeros(self):
        self.assertIsNone(cashflow_ttm({'2026-02-28':2,'2026-03-30':4,'2026-06-30':float('nan'),'2026-09-30':True})[0])
    def test_negative_cashflow_is_valid(self):
        self.assertEqual(cashflow_ttm({'2025-03-31':-10,'2025-06-30':-20,'2025-09-30':-30,'2025-12-31':-50})[0],-50)
    def test_income_requires_same_periods_and_no_missing_zero_fill(self):
        q=['2025Q3','2025Q4','2026Q1','2026Q2']
        self.assertEqual(aligned_income(q,[100]*4,[10]*4,q),40e6)
        self.assertIsNone(aligned_income(q,[100]*3,[10]*4,q))
        self.assertIsNone(aligned_income(q,[100]*4,[10,None,10,10],q))
        self.assertIsNone(aligned_income(q,[100]*4,[10]*4,['2025Q2']+q[:3]))
    def test_retry_after_failure_not_wait_for_next_quarter(self):
        today=dt.date(2026,10,24)
        e={'ocfq':'2026Q2','fin':{'cf_quality':{'complete':False}},'fin_fetch':{'version':1,'attempt_date':'2026-10-23'}}
        self.assertTrue(financial_retry_due(e,'2026Q2',today))
        e['fin_fetch']['attempt_date']='2026-10-24'
        self.assertFalse(financial_retry_due(e,'2026Q2',today))
    def test_complete_same_quarter_not_repeated(self):
        e={'ocfq':'2026Q2','fin':{'cf_quality':{'complete':True},'fcf4':0},'fin_fetch':{'version':1}}
        self.assertFalse(financial_retry_due(e,'2026Q2',dt.date(2026,10,24)))

class SecFactsTests(unittest.TestCase):
    def facts(self,rows,tag='Revenues',unit='USD'):
        return {'facts':{'us-gaap':{tag:{'units':{unit:rows}}}}}
    def r(self,start,end,val,filed='2026-08-26',accn='Q',form='10-Q'):
        return dict(start=start,end=end,val=val,filed=filed,accn=accn,form=form)
    def nvda_rows(self):
        return [self.r('2025-01-27','2026-01-25',215938e6,'2026-02-25','K','10-K'),self.r('2026-01-26','2026-07-26',177837e6),self.r('2025-01-27','2025-07-27',90805e6)]
    def test_real_nvda_period_reconciliation(self):
        m=current_flow_ttm(self.facts(self.nvda_rows()),'rev',dt.date(2026,10,24))
        self.assertEqual(m['value'],302970);self.assertEqual(m['period_start'],'2025-07-28');self.assertFalse(m['pit_eligible']);self.assertIsNone(m['published_at'])
    def test_missing_comparable_cannot_be_ttm(self):
        self.assertFalse(current_flow_ttm(self.facts(self.nvda_rows()[:2]),'rev',dt.date(2026,10,24))['complete'])
    def test_future_filing_excluded(self):
        m=current_flow_ttm(self.facts(self.nvda_rows()),'rev',dt.date(2026,8,25))
        self.assertEqual(m['value'],215938);self.assertEqual(m['period_end'],'2026-01-25')
    def test_currency_not_silently_converted(self):
        self.assertFalse(current_flow_ttm(self.facts(self.nvda_rows(),unit='TWD'),'rev',dt.date(2026,10,24))['complete'])
    def test_no_unsupported_ifrs_or_eps_guess(self):
        self.assertFalse(current_flow_ttm({'facts':{'ifrs-full':{}}},'rev')['complete'])
        with self.assertRaises(KeyError):current_flow_ttm(self.facts([]),'eps')
    def test_wrong_ytd_start_rejected(self):
        rows=self.nvda_rows();rows[1]['start']='2026-02-01'
        self.assertFalse(current_flow_ttm(self.facts(rows),'rev',dt.date(2026,10,24))['complete'])
    def test_latest_concept_missing_comparable_not_replaced_by_old_annual(self):
        c=self.facts(self.nvda_rows()[:2]);c['facts']['us-gaap']['RevenueFromContractWithCustomerExcludingAssessedTax']={'units':{'USD':[self.r('2024-01-01','2024-12-31',100,'2025-02-01','OLD','10-K')]}}
        self.assertFalse(current_flow_ttm(c,'rev',dt.date(2026,10,24))['complete'])
    def test_filing_revision_selected_and_provenance_retained(self):
        rows=self.nvda_rows();rows.append(self.r('2026-01-26','2026-07-26',178000e6,'2026-09-01','QA','10-Q/A'))
        m=current_flow_ttm(self.facts(rows),'rev',dt.date(2026,10,24));self.assertEqual(m['value'],303133);self.assertEqual(m['filed'],'2026-09-01')

class FinraTests(unittest.TestCase):
    def test_actual_calendar_counterexample(self):
        dates=load_calendar();self.assertEqual(dates['2026-03-31'],'2026-04-10');self.assertEqual(available_date('2026-03-31',dates),'2026-04-11')
    def test_unknown_date_never_guessed(self):
        self.assertIsNone(available_date('2020-03-31',{}))
    def test_year_rollover(self):
        text='<h2>2026 Short Interest Reporting Dates</h2><table><tr><td>December 31 (Thursday)</td><td>January 5</td><td>January 12 (Monday)</td></tr></table>'
        self.assertEqual(parse_calendar(text),{'2026-12-31':'2027-01-12'})
    def test_changed_header_does_not_make_up_dates(self):
        self.assertEqual(parse_calendar('<h2>Unknown</h2><tr><td>March 31</td><td>April 2</td><td>April 10</td></tr>'),{})
    def test_frame_does_not_use_april9_or_publication_day(self):
        import pandas as pd
        tree=ast.parse((ROOT/'ext_build.py').read_text(encoding='utf-8'))
        ns={'pd':pd,'E':'archive/ext','load_calendar':load_calendar,'available_date':available_date,
            'gz':lambda *args:{'s':{'X':{'2026-03-31':[100,10,10]}}}}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='finra_frame'],type_ignores=[]),'finra_frame','exec'),ns)
        f=ns['finra_frame']({'X'},pd.to_datetime(['2026-04-09','2026-04-10','2026-04-13']))
        self.assertTrue(pd.isna(f.iloc[0,0]));self.assertTrue(pd.isna(f.iloc[1,0]));self.assertEqual(f.iloc[2,0],10)

class PipelineTests(unittest.TestCase):
    def functions(self,raw):
        tree=ast.parse((ROOT/'update_data.py').read_text(encoding='utf-8'))
        names={'fm_stock_ocf','fm_stock_fin','backfill_perstock'}
        ns={'dt':dt,'time':SimpleNamespace(sleep=lambda _:None),'re':__import__('re'),'numf':lambda x:float(x) if x is not None else None,
            'cashflow_ttm':cashflow_ttm,'aligned_income':aligned_income,'financial_retry_due':financial_retry_due,
            '_fm_raw':lambda *a:raw,'_FIN_TYPES_LOGGED':{'n':1},'save_fin_source':lambda *a:'archive/test-source.json.gz',
            'latest_due_quarter':lambda:'2026Q2'}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'update_data','exec'),ns)
        return ns
    def test_original_function_now_rejects_two_quarters(self):
        rows=[{'date':d,'type':'CashFlowsFromOperatingActivities','value':v} for d,v in [('2026-03-31',100),('2026-06-30',250)]]
        self.assertIsNone(self.functions(rows)['fm_stock_ocf']('2330'))
    def test_failed_backfill_preserves_legacy_snapshot_and_retries(self):
        ns=self.functions([]);refs=[];ns['save_fin_source']=lambda *a:refs.append(a) or 'archive/legacy.json.gz';ns['fm_stock_fin']=lambda _:None
        e={'fq':['2025Q3','2025Q4','2026Q1','2026Q2'],'fin':{'q':'2026Q2','ocf4':99,'fcf4':88},'ocfr':2,'ocfq':'2026Q2'}
        ns['backfill_perstock']({'2330':e},[{'id':'2330','market':'TW'}],0,0,1)
        self.assertTrue(refs);self.assertEqual(refs[0][1]['legacy_fin']['ocf4'],99);self.assertIsNone(e['fin']['ocf4']);self.assertIsNone(e['ocfr']);self.assertEqual(e['fin_fetch']['status'],'failed')
    def test_immutable_raw_snapshot_roundtrip(self):
        import os
        tree=ast.parse((ROOT/'update_data.py').read_text(encoding='utf-8'));ns={'re':__import__('re'),'json':json}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='save_fin_source'],type_ignores=[]),'archivefn','exec'),ns)
        before=Path.cwd()
        (ROOT/".cache").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/".cache") as temp:
            try:
                os.chdir(temp);p=Path(ns['save_fin_source']('2330',{'cf':[1,2]}));first=p.read_bytes();self.assertEqual(json.loads(gzip.decompress(first)),{'cf':[1,2]});ns['save_fin_source']('2330',{'cf':[1,2]});self.assertEqual(first,p.read_bytes())
            finally:os.chdir(before)

class SourcePackTests(unittest.TestCase):
    def test_packed_raw_checksum_roundtrip_and_no_delete(self):
        import os
        import fetch_sec_ttm as F
        from unittest.mock import patch
        (ROOT/'.cache').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as temp:
            with patch.object(F,'ROOT',Path(temp)):
                payload=json.dumps({'cik':123,'facts':{'us-gaap':{}}}).encode()
                path,digest=F.archive_bytes('123',payload)
                entries={'123':{'raw_path':path,'sha256':digest}}
                F.pack_sources(entries)
                self.assertTrue(Path(path).exists());self.assertTrue(Path(entries['123']['raw_pack']).exists())
                self.assertEqual(F.read_source(entries['123'])['cik'],123)
                entries['123']['sha256']='bad'
                with self.assertRaises(ValueError):F.read_source(entries['123'])
    def test_repeated_current_data_with_zero_requests_keeps_update_time(self):
        # Current rows are never relabeled with a fresh success timestamp when no request succeeds.
        import fetch_sec_ttm as F
        from unittest.mock import patch
        old={'updated':'2026-10-24T00:00:00Z','issuers':{'1':{'last_success':dt.datetime.now(dt.timezone.utc).isoformat(),'metrics':{}}}}
        captured=[]
        def read(path,default):
            return old if str(path)=='sec_ttm.json' else {'stocks':[{'id':'X','market':'US'}]} if str(path)=='data.json' else {'X':1}
        with patch.object(F,'read_json',side_effect=read),patch.object(F,'archive_bytes'),patch.object(F,'atomic_json',side_effect=lambda p,v:captured.append(v.copy())),patch.object(F,'pack_sources'):
            F.main(0,0)
        self.assertEqual(captured[-1]['updated'],old['updated'])

if __name__=='__main__':unittest.main()
