"""Limited, preregistered comparisons; chronological development/validation/final audit.
Historical periods have been studied before: final audit is NOT an unseen holdout.
"""
import argparse,datetime as dt,json,hashlib,subprocess
from pathlib import Path
from dataclasses import replace
import numpy as np
import short_bt_study as SB
from portfolio_research import Policy,simulate

VARIANTS={
 'baseline':Policy(),
 'score5':Policy(min_score=5),
 'avoid_20d_rise30':Policy(max_r20=.30),
 'gap3_cancel':Policy(max_gap=.03),
 'hold10':Policy(hold=10),
 'tp25':Policy(tp=.25),
 'trail10_after10_no_tp':Policy(tp=0,trail=.10,trail_arm=.10),
 'break_even_after10':Policy(break_even=.10),
 'cap_high_vol_size':Policy(risk_scale=True),
}
PERIODS={'development':('2016-01-01','2021-01-01'),'validation':('2021-01-01','2024-01-01'),'final_audit':('2024-01-01',None),'full':('2016-01-01',None)}

def prepare(S):
    SB.features(S)
    cal=sorted({d for e in S.values() for d in e['d']})
    weekly={d for d,n in zip(cal,cal[1:]) if dt.date.fromisoformat(d).isocalendar()[:2]!=dt.date.fromisoformat(n).isocalendar()[:2]}
    ranks={d:[] for d in weekly if d>='2016-01-01'}
    for sid,e in S.items():
        e['idx']={d:i for i,d in enumerate(e['d'])}
        # Correct legacy study's one-day volume-window shift; matches live i-24:i-4 exactly.
        v=e['a'][:,4];cs=np.r_[0,np.cumsum(v)];e['F']['v20b'][24:]=(cs[20:-5]-cs[:-25])/20
        for d,i in e['idx'].items():
            if d not in ranks:continue
            c=SB.score_day(e,i)
            if c:c.update(sid=sid,sec=e.get('sec') or '');ranks[d].append(c)
    for rows in ranks.values():rows.sort(key=lambda c:(-c['sc'],round(c['atrp']*100,2),c['sid']))
    return cal,ranks

def better(a,b):
    return (a['n']>=100 and a['avg_pct']>b['avg_pct'] and (a['win_pct']>b['win_pct'] or (a['profit_factor'] or 0)>(b['profit_factor'] or 0))
       and a['positive_years']>=b['positive_years'] and a['cagr_pct']>=b['cagr_pct'] and a['mdd_pct']>=b['mdd_pct'])

def main(out):
    root=Path(__file__).resolve().parent
    report={'generated':dt.datetime.now(dt.timezone.utc).isoformat(),'engine':'daily_cash_units_v1','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
      'cost_roundtrip':.006,'variants_predeclared':list(VARIANTS),'periods':PERIODS,'limitations':[
       '目前股庫與現今產業分類有倖存者偏差；不包含完整下市股','歷史期間曾經研究過，不能稱為真正未見資料',
       '日K同時觸停損停利採停損優先；但開盤成交優先','假設可成交、無逐筆流動性／漲跌停排隊與升降單位；未計現金利息',
       '以除權息還原價回測，與實際派息及稅務時點不同','研究score保留長序列KD近似，實盤僅重算最近31根；非實盤完全重播',
       '未完成持倉保留逐日市值，不當已結束交易；分段各自從現金開始'], 'results':[]}
    print('loading',flush=True);S=SB.load_all();cal,ranks=prepare(S)
    report['data']={'stocks':len(S),'first':cal[0],'last':cal[-1],'weekly_sessions':len(ranks)}
    print('prepared',report['data'],flush=True)
    runs={}
    for period in ['development','validation']:
        for name,p in VARIANTS.items():
            r=simulate(S,cal,ranks,p,*PERIODS[period]);runs[period,name]=r['metrics']
            row={'period':period,'variant':name,**r['metrics']};report['results'].append(row);print(json.dumps(row),flush=True)
    finalists=[n for n in VARIANTS if n!='baseline' and all(better(runs[p,n],runs[p,'baseline']) for p in ['development','validation'])]
    # Freeze finalists before final period. No second parameter search after audit.
    report['finalists']=finalists
    for period in ['final_audit','full']:
        for name in ['baseline']+finalists:
            r=simulate(S,cal,ranks,VARIANTS[name],*PERIODS[period]);runs[period,name]=r['metrics']
            row={'period':period,'variant':name,**r['metrics']};report['results'].append(row);print(json.dumps(row),flush=True)
            if period=='full':report.setdefault('daily_nav',{})[name]=r['curve'];report.setdefault('trade_ledger',{})[name]=r['trades']
    report['eligible']=[n for n in finalists if better(runs['final_audit',n],runs['final_audit','baseline']) and better(runs['full',n],runs['full','baseline'])]
    report['decision']='research_only_no_rule_change' if not report['eligible'] else 'eligible_requires_live_parity_review'
    # Higher cost robustness for fixed finalists + baseline only.
    for name in ['baseline']+finalists:
        r=simulate(S,cal,ranks,replace(VARIANTS[name],cost=.01),*PERIODS['full'])
        report['results'].append({'period':'full_cost1pct','variant':name,**r['metrics']})
    out.parent.mkdir(exist_ok=True,parents=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DECISION',report['decision'],report['eligible'],flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);main(ap.parse_args().output)
