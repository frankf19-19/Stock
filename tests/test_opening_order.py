import unittest
import test_strategy_engine as fixtures
class OpeningOrderTests(unittest.TestCase):
    engine=fixtures.StrategyEngineTests.engine
    def test_gap_above_target_exits_before_later_stop(self):
        t,p=self.engine([125,130,70,100,100],fill_d='2026-10-20',entry=100,hi=100,lo=100)
        self.assertEqual(p['xp'],125);self.assertEqual(p['xw'],'tp')
    def test_queued_open_exit_precedes_later_stop_and_target(self):
        t,p=self.engine([100,130,70,100,100],fill_d='2026-10-20',entry=100,hi=100,lo=100,x_open='2026-10-20',x_why='rank')
        self.assertEqual(p['xp'],100);self.assertEqual(p['xw'],'rank')
    def test_tighter_fixed_stop_wins(self):
        t,p=self.engine([100,105,88,95,100],fill_d='2026-10-20',entry=100,hi=100,lo=100,sl_px=90)
        self.assertEqual(p['xp'],90)
if __name__=='__main__':unittest.main()
import ast
from pathlib import Path
class DipTrackerPreservationTests(unittest.TestCase):
    def track(self,bar):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'strat_os.py').read_text(encoding='utf-8'))
        ns={'DD':-.4,'TP':.2,'SL':.15,'HOLD':60,'LIQ':2e7,'RULE_V':40}
        exec(compile(ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='run'],type_ignores=[]),'strat_os','exec'),ns)
        class A:
            def bars_of(self,sid):return ['2026-10-23'],[bar]
        old=[{'id':str(i),'ret':0,'r':40} for i in range(400)]
        p={'id':'X','name':'X','fill':'2026-10-22','entry':100,'tp':120,'sl':85,'n':1,'r':40}
        t={'os':{'open':[p],'pend':[],'closed':old[:]}}
        return ns['run'](A(),{'stocks':[]},t,'2026-10-23',log=lambda *x:None),old
    def test_closed_trades_beyond_400_remain(self):
        t,old=self.track([125,130,70,100,1]);self.assertEqual(len(t['closed']),401);self.assertEqual(t['closed'][:400],old);self.assertEqual(t['closed'][-1]['xp'],125)
    def test_intraday_ambiguous_stop_first(self):
        t,_=self.track([100,130,70,100,1]);self.assertEqual(t['closed'][-1]['xp'],85)
