import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from fetch_tw_financials import build_history, normalize, snapshot, encoded, quarter


def rows(values, kind='Revenue', sid='2330', name='營業收入'):
    return [{'stock_id':sid,'date':d,'type':kind,'value':v,'origin_name':name} for d,v in values]


def history(income=None, cf=None, balance=None, old=None):
    return build_history('2330',{'income':{'data':income or []},'cashflow':{'data':cf or []},'balance':{'data':balance or []}}, {},'2026-10-24T00:00:00+00:00',old)


class FinancialHistoryTests(unittest.TestCase):
    def test_quarter_end_only(self):
        self.assertIsNone(quarter('2025-06-29'));self.assertIsNone(quarter('2025-13-31'))
        self.assertIsNotNone(quarter('2025-06-30'))

    def test_single_income_not_differenced(self):
        h=history(rows([('2024-03-31',100),('2024-06-30',120),('2024-09-30',90),('2024-12-31',140)]))
        self.assertEqual(h['ttm']['revenue'],450);self.assertEqual(h['quarters'][1]['revenue'],120)

    def test_halfyear_income_not_treated_as_quarter(self):
        h=history(rows([('2024-06-30',200),('2024-12-31',300)]))
        self.assertIsNone(h['quarters'][0]['revenue']);self.assertIsNone(h['ttm']['revenue'])

    def test_ytd_cashflow_converts_with_year_reset(self):
        cf=rows([('2024-03-31',10),('2024-06-30',35),('2024-09-30',60),('2024-12-31',100),('2025-03-31',15)],'CashFlowsFromOperatingActivities')
        h=history(cf=cf);self.assertEqual([x['ocf'] for x in h['quarters']],[10,25,25,40,15]);self.assertEqual(h['ttm']['ocf'],105)

    def test_ytd_missing_predecessor_not_all_ytd(self):
        h=history(cf=rows([('2024-06-30',100),('2024-09-30',180)],'CashFlowsFromOperatingActivities'))
        self.assertIsNone(h['quarters'][0]['ocf']);self.assertEqual(h['quarters'][1]['ocf'],80)

    def test_same_four_quarters_and_positive_net_income_ratio(self):
        ds=[('2024-03-31',10),('2024-06-30',10),('2024-09-30',10),('2024-12-31',10)]
        cf=rows([('2024-03-31',20),('2024-06-30',40),('2024-09-30',60),('2024-12-31',80)],'CashFlowsFromOperatingActivities')
        h=history(income=rows(ds,'IncomeAfterTaxes'),cf=cf);self.assertEqual(h['ttm']['cash_conversion'],2)
        h=history(income=rows([(d,-v) for d,v in ds],'IncomeAfterTaxes'),cf=cf);self.assertIsNone(h['ttm']['cash_conversion'])

    def test_balance_is_point_in_time_and_units_not_multiplied(self):
        h=history(balance=rows([('2024-03-31',100000000),('2024-06-30',110000000)],'TotalAssets'))
        self.assertEqual(h['quarters'][1]['assets'],110000000)

    def test_ambiguous_duplicate_is_null(self):
        h=history(rows([('2024-03-31',100),('2024-03-31',101)]))
        self.assertIsNone(h['quarters'][0]['revenue']);self.assertEqual(len(h['diagnostics']['income']['conflicts']),1)

    def test_identical_duplicates_are_not_summed(self):
        h=history(rows([('2024-03-31',100),('2024-03-31',100)]));self.assertEqual(h['quarters'][0]['revenue'],100)

    def test_foreign_symbol_and_nonfinite_rejected(self):
        n,d=normalize('income',rows([('2024-03-31',9)],sid='2317')+rows([('2024-03-31',float('nan'))]),'2330')
        self.assertFalse(n);self.assertEqual(d['invalid_rows'],2)

    def test_missing_quarter_does_not_fall_back_to_older_ttm(self):
        h=history(rows([('2024-03-31',1),('2024-06-30',2),('2024-09-30',3),('2024-12-31',4),('2025-06-30',5)]))
        self.assertIsNone(h['ttm']['revenue']);self.assertEqual(h['coverage']['income']['missing_quarters'],['2025Q1'])

    def test_provider_omission_keeps_history_and_source_coverage(self):
        old=history(rows([('2024-03-31',100),('2024-06-30',200)]))
        h=history(rows([('2024-09-30',300)]),old=old)
        self.assertEqual(len(h['quarters']),3);self.assertEqual(h['quarters'][0]['revenue'],100)
        self.assertEqual(h['coverage']['income']['source_quarters'],1);self.assertEqual(h['coverage']['income']['retained_quarters'],2)

    def test_revised_cashflow_recomputes_using_retained_predecessor(self):
        old=history(cf=rows([('2024-03-31',10),('2024-06-30',30)],'CashFlowsFromOperatingActivities'))
        h=history(cf=rows([('2024-06-30',40)],'CashFlowsFromOperatingActivities'),old=old)
        self.assertEqual(h['quarters'][1]['ocf'],30)

    def test_current_conflict_never_repaired_from_old(self):
        old=history(rows([('2024-03-31',100)]))
        h=history(rows([('2024-03-31',200),('2024-03-31',201)]),old=old)
        self.assertIsNone(h['quarters'][0]['revenue'])

    def test_capex_requires_acquisition_label(self):
        h=history(cf=rows([('2024-03-31',100)],'CashFlowsFromOperatingActivities')+rows([('2024-03-31',-20)],'PropertyAndPlantAndEquipment',name='取得不動產廠房及設備'))
        self.assertEqual(h['quarters'][0]['fcf'],80)
        h=history(cf=rows([('2024-03-31',20)],'PropertyAndPlantAndEquipment',name='處分資產'))
        self.assertIsNone(h['quarters'][0]['capex'])

    def test_immutable_snapshot_roundtrip_and_hash(self):
        Path('.cache').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='.cache') as t:
            obj={'data':[{'value':1}]};ref=snapshot(Path(t),'archive',obj);p=Path(t)/ref['path'];before=p.read_bytes()
            self.assertEqual(hashlib.sha256(gzip.decompress(before)).hexdigest(),ref['sha256']);self.assertEqual(json.loads(gzip.decompress(before)),obj)
            snapshot(Path(t),'archive',obj);self.assertEqual(p.read_bytes(),before)

    def test_publication_and_per_share_not_invented(self):
        h=history(rows([('2024-03-31',1)],'EPS'))
        self.assertFalse(h['pit_eligible']);self.assertIsNone(h['published_at']);self.assertFalse(h['eps_basis_verified'])

    def test_retained_income_cannot_qualify_as_current_ttm(self):
        values=[('2024-03-31',10),('2024-06-30',20),('2024-09-30',30),('2024-12-31',40)]
        old=history(rows(values));h=history(rows(values[-1:]),old=old)
        self.assertEqual(len(h['quarters']),4);self.assertIsNone(h['ttm']['revenue'])

    def test_retained_ytd_predecessor_cannot_qualify_current_cf_ttm(self):
        values=[('2024-03-31',10),('2024-06-30',20),('2024-09-30',30),('2024-12-31',40)]
        old=history(cf=rows(values,'CashFlowsFromOperatingActivities'))
        h=history(cf=rows(values[1:],'CashFlowsFromOperatingActivities'),old=old)
        self.assertEqual(len(h['quarters']),4);self.assertIsNone(h['ttm']['ocf'])

    def test_future_quarters_rejected(self):
        h=history(rows([('2027-03-31',100),('2024-03-31',1)]))
        self.assertEqual(len(h['quarters']),1);self.assertEqual(h['quarters'][0]['period'],'2024Q1')

    def test_run_quota_preserves_completed_raw_and_retries_incomplete(self):
        from fetch_tw_financials import run, QuotaError, read_json
        Path('.cache').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='.cache') as tmp:
            root=Path(tmp);(root/'data.json').write_text(json.dumps({'stocks':[{'id':'2330','market':'TW'}]}),encoding='utf-8')
            args=SimpleNamespace(root=str(root),symbols='2330',limit=3,seconds=300,start='2015-01-01',delay=0)
            with patch('fetch_tw_financials.fetch',side_effect=[{'status':200,'data':rows([('2024-03-31',100)])},QuotaError('quota')]):
                run(args)
            idx=read_json(root/'fundamentals/tw/index.json');e=idx['stocks']['2330']
            self.assertFalse(e['complete_fetch']);self.assertEqual(e['coverage']['income']['quarters'],1)
            self.assertEqual(len(list((root/'archive/tw_financial/raw').rglob('*.gz'))),1)
            self.assertEqual(e['failed'],['balance'])

    def test_request_budget_stops_before_unfinishable_stock(self):
        from fetch_tw_financials import run
        Path('.cache').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='.cache') as tmp:
            root=Path(tmp);(root/'data.json').write_text(json.dumps({'stocks':[{'id':'2330','market':'TW'}]}),encoding='utf-8')
            with patch('fetch_tw_financials.fetch') as fetch:
                run(SimpleNamespace(root=str(root),symbols='2330',limit=2,seconds=300,start='2015-01-01',delay=0))
                fetch.assert_not_called()

if __name__=='__main__': unittest.main()
