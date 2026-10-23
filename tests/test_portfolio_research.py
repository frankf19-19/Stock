import unittest
import numpy as np
from portfolio_research import Policy,simulate,touch_exit
class PortfolioResearchTests(unittest.TestCase):
    def sample(self,rows,ds=None):
        ds=ds or [f'2024-01-{x:02d}' for x in range(2,len(rows)+2)]
        e={'d':ds,'a':np.array(rows,float),'sec':'a','idx':{d:i for i,d in enumerate(ds)}}
        c={'sid':'A','sc':5,'sec':'a','c':rows[0][3],'atrp':.03,'r20':0}
        return {'A':e},ds,{ds[0]:[c]}
    def test_open_target_precedes_later_low(self):
        self.assertEqual(touch_exit(125,130,70,85,120),(125,'gap_tp'))
    def test_ambiguous_range_stop_first(self):
        self.assertEqual(touch_exit(100,130,70,85,120),(85,'sl'))
    def test_no_same_day_fill_and_daily_unrealized_loss(self):
        s,d,c=self.sample([[100,101,99,100,1],[100,101,90,90,1],[90,92,85,90,1]])
        r=simulate(s,d,c,Policy(sl=.5,tp=1))
        self.assertEqual(r['curve'][0]['positions'],0);self.assertLess(r['curve'][1]['nav'],.98)
        self.assertEqual(r['trades'],[]);self.assertLess(r['metrics']['mdd_pct'],-1.9)
    def test_end_boundary_preserves_losing_open_position(self):
        s,d,c=self.sample([[100,101,99,100,1],[100,101,90,90,1],[90,150,90,140,1]])
        r=simulate(s,d,c,Policy(sl=.5,tp=1),end=d[2])
        self.assertEqual(len(r['curve']),2);self.assertEqual(r['metrics']['open_positions'],1);self.assertLess(r['metrics']['final_nav'],1)
    def test_costs_debited_cash_and_nav(self):
        s,d,c=self.sample([[100,100,100,100,1]]*3)
        r=simulate(s,d,c,Policy(hold=1))
        self.assertAlmostEqual(r['trades'][0]['r'],(1-.003)/(1+.003)-1)
        self.assertAlmostEqual(r['curve'][1]['nav'],.8+.2*(1-.003)/(1+.003))
    def test_gap_cancel_no_future_aware_replacement(self):
        s,d,c=self.sample([[100,101,99,100,1],[110,112,109,111,1]])
        s['B']={**s['A'],'sec':'b'};c[d[0]].append({**c[d[0]][0],'sid':'B','sec':'b'})
        r=simulate(s,d,c,Policy(slots=1,max_gap=.03))
        self.assertEqual(r['curve'][1]['positions'],0)
    def test_trailing_high_only_effective_next_session(self):
        s,d,c=self.sample([[100,101,99,100,1],[100,115,98,112,1],[112,113,100,105,1]])
        r=simulate(s,d,c,Policy(tp=0,trail=.10,trail_arm=.1))
        self.assertEqual(r['curve'][1]['positions'],1);self.assertAlmostEqual(r['trades'][0]['exit'],103.5)
    def test_cash_never_borrowed_and_max_five_slots(self):
        s,d,c=self.sample([[100,101,99,100,1]]*5)
        c[d[1]]=c[d[0]];c[d[2]]=c[d[0]]
        r=simulate(s,d,c);self.assertGreaterEqual(r['metrics']['min_cash'],0);self.assertLessEqual(max(x['positions'] for x in r['curve']),5)
    def test_future_mutation_does_not_change_prior_nav(self):
        rows=[[100,101,99,100,1],[100,101,99,100,1],[100,101,99,100,1],[100,150,50,140,1]]
        s,d,c=self.sample(rows);r=simulate(s,d,c)
        s['A']['a'][-1]=[200,210,190,205,1];r2=simulate(s,d,c)
        self.assertEqual(r['curve'][:-1],r2['curve'][:-1])
if __name__=='__main__':unittest.main()
