import ast,unittest
from pathlib import Path
SRC=Path(__file__).resolve().parents[1]/'aip3.py'
def load_functions():
    tree=ast.parse(SRC.read_text(encoding='utf-8'));names={'execution_contract','fill_and_track'}
    ns={'US_DIP':{'sl':.2,'tp':.3,'hold':90},'_tk':lambda v,us,mode='near':round(v,2)}
    exec(compile(ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in names],type_ignores=[]),str(SRC),'exec'),ns)
    return ns
class StrategyEngineTests(unittest.TestCase):
    def test_slot_legacy_rules_not_rewritten(self):
        n=load_functions();r=n['execution_contract']({'entry':100,'sl_r':.15,'tp_r':.2,'hold_r':60},'mid',True)
        self.assertEqual((r['sl'],r['tp'],r['hold_max']),(85,120,60))
    def test_new_us_slot_rule(self):
        r=load_functions()['execution_contract']({'entry':100},'mid',True)
        self.assertEqual((r['sl'],r['tp'],r['hold_max']),(80,130,90))
    def test_mid_fixed_atr_stop_not_recomputed(self):
        r=load_functions()['execution_contract']({'entry':100,'sl_px':72,'lv':{'sl':90}},'mid')
        self.assertEqual((r['sl'],r['tp']),(72,125))
    def test_long_no_automatic_exits(self):
        r=load_functions()['execution_contract']({'entry':100,'lv':{'sl':92,'tp':140}},'long')
        self.assertFalse(r['automatic']);self.assertIsNone(r['sl']);self.assertIsNone(r['tp'])
    def test_weekly_leg_is_authoritative(self):
        execution={'sl':197.61,'tp':307.49};self.assertIs(load_functions()['execution_contract']({'execution':execution},'short',True),execution)
    def engine(self,bar,**kw):
        n=load_functions();p={'id':'X','name':'X','sel_d':'2026-10-20','fill_d':None,'entry':None,'st':'pend','hi':None,'lo':None};p.update(kw)
        n['raw_bars']=lambda sid,us:[('2026-10-21',bar)]
        T={'slots':[p],'hist':[{'id':str(i)} for i in range(400)]};n['fill_and_track'](T,False,tp=.2,sl=.15,hold_max=15);return T,p
    def test_same_bar_both_hit_stop_first(self):
        t,p=self.engine([100,130,80,110,100]);self.assertEqual(p['xw'],'sl');self.assertEqual(p['xp'],85)
    def test_gap_stop_uses_worse_open(self):
        t,p=self.engine([70,80,65,75,100],fill_d='2026-10-20',entry=100,hi=100,lo=100);self.assertEqual(p['xp'],70)
    def test_history_exceeds_400_without_truncation(self):
        t,p=self.engine([100,130,90,120,100]);self.assertEqual(len(t['hist']),401);self.assertEqual(t['hist'][0]['id'],'0')
    def test_unfilled_without_future_bars_stays_pending(self):
        n=load_functions();n['raw_bars']=lambda sid,us:[];t={'slots':[{'id':'X','st':'pend'}],'hist':[]};n['fill_and_track'](t,False,tp=.2,sl=.15);self.assertEqual(t['slots'][0]['st'],'pend')
    def test_split_validation_excludes_post_period_exit(self):
        source=(SRC.parent/'plan_bt_study.py').read_text(encoding='utf-8');tree=ast.parse(source);ns={}
        exec(compile(ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='simulate'],type_ignores=[]),'sim','exec'),ns)
        self.assertIn('d[xi] >= end',source)
if __name__=='__main__':unittest.main()
