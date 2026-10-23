import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import uuid
import shutil
import os
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trends_history import atomic_json, read_archive, trend_stats, publish, rebuild

def row(day, keys):
    return {"d":day,"keys":keys}
def snap(day, keys=("a",), **kw):
    return {"v":1,"date":day,"gen":day+"T06:00:00+08:00","trends":[{"key":k,"name":k,"thesis":"原文","src":[]} for k in keys],**kw}
class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.base=Path(os.environ.get("STOCK_TEST_TMP",tempfile.gettempdir())).resolve()
        self.root=self.base/("stock-history-test-"+uuid.uuid4().hex)
        self.root.mkdir()
        self.directory=self.root/"trends"
        self.latest=self.root/"trends.json"
        self.directory.mkdir()
    def tearDown(self):
        assert self.root.resolve().parent == self.base and self.root.name.startswith("stock-history-test-")
        shutil.rmtree(self.root)
    def daily(self, day, keys=("a",)):
        atomic_json(self.directory/(day+".json"),snap(day,keys))
    def test_missing_day_breaks_streak(self):
        stats=trend_stats([row("2026-10-21",["a"]),row("2026-10-23",["a"])],"a","2026-10-23")
        self.assertEqual(stats["current_streak_days"],1)
        self.assertEqual(stats["missing_days"],1)
        self.assertEqual(stats["total_seen_days"],2)
    def test_absence_and_reappearance(self):
        stats=trend_stats([row("2026-10-21",["a"]),row("2026-10-22",[]),row("2026-10-23",["a"])],"a","2026-10-23")
        self.assertEqual(stats["first_seen"],"2026-10-21")
        self.assertEqual(stats["current_streak_start"],"2026-10-23")
        self.assertEqual(stats["missing_days"],0)
    def test_gap_in_old_history_still_strict(self):
        stats=trend_stats([row("2026-10-"+str(d),["a"]) for d in [17,18,20,21,22,23]],"a","2026-10-23")
        self.assertEqual(stats["current_streak_days"],4)
        self.assertEqual(stats["current_streak_start"],"2026-10-20")
        self.assertEqual(stats["first_seen"],"2026-10-17")
    def test_full_history_survives_502_days(self):
        first=dt.date(2025,6,9)
        hist=[row((first+dt.timedelta(days=i)).isoformat(),["a"]) for i in range(502)]
        atomic_json(self.directory/"history.json",{"hist":hist})
        self.daily(hist[-1]["d"])
        one=rebuild(self.directory,self.latest)
        next_day=(first+dt.timedelta(days=502)).isoformat()
        two=publish(snap(next_day),self.directory,self.latest)
        self.assertEqual(one["trends"][0]["current_streak_days"],502)
        self.assertEqual(two["trends"][0]["current_streak_days"],503)
        self.assertEqual(two["trends"][0]["first_seen"],first.isoformat())
        self.assertEqual(len(json.loads((self.directory/"history.json").read_text(encoding="utf8"))["hist"]),503)
    def test_rebuild_preserves_daily_and_old_latest(self):
        self.daily("2026-10-23")
        path=self.directory/"2026-10-23.json";before=path.read_bytes()
        old=snap("2026-10-23",hist=[row("2026-10-22",["a"])])
        atomic_json(self.latest,old)
        result=rebuild(self.directory,self.latest)
        self.assertEqual(path.read_bytes(),before)
        self.assertNotIn("hist",result)
        self.assertEqual(result["trends"][0]["total_seen_days"],2)
        self.assertTrue(any(json.loads(p.read_text(encoding="utf8"))==old for p in (self.directory/"revisions"/"2026-10-23").glob("*.json")))
    def test_same_day_rerun_retains_first_and_uses_one_revision(self):
        self.daily("2026-10-23")
        before=(self.directory/"2026-10-23.json").read_bytes()
        publish(snap("2026-10-23",("b",)),self.directory,self.latest,raw={"ai":"原始回應"})
        again=publish(snap("2026-10-23",("b",)),self.directory,self.latest)
        self.assertEqual((self.directory/"2026-10-23.json").read_bytes(),before)
        self.assertEqual(again["trends"][0]["key"],"b")
        self.assertEqual(again["trends"][0]["total_seen_days"],1)
        self.assertTrue(list((self.directory/"raw"/"2026-10-23").glob("*.json")))
    def test_corrupt_latest_can_be_rebuilt(self):
        self.daily("2026-10-23");self.latest.write_text("{bad",encoding="utf8")
        self.assertEqual(rebuild(self.directory,self.latest)["date"],"2026-10-23")
    def test_corrupt_daily_is_unknown_not_absence(self):
        self.daily("2026-10-21");self.daily("2026-10-23")
        (self.directory/"2026-10-22.json").write_text("{bad",encoding="utf8")
        result=rebuild(self.directory,self.latest)
        self.assertEqual(result["trends"][0]["missing_days"],1)
        self.assertTrue(result["history_warnings"])
    def test_no_valid_day_does_not_replace_latest(self):
        atomic_json(self.latest,{"important":"keep"})
        before=self.latest.read_bytes()
        with self.assertRaises(ValueError):rebuild(self.directory,self.latest)
        self.assertEqual(self.latest.read_bytes(),before)
    def test_active_path_cannot_escape_archive(self):
        atomic_json(self.directory/"active.json",{"dates":{"2026-10-23":"../outside.json"}})
        with self.assertRaises(ValueError):read_archive(self.directory)
    def test_new_source_count_deduplicates(self):
        old=snap("2026-10-22");old["trends"][0]["src"]=[{"l":"https://one"}]
        atomic_json(self.directory/"2026-10-22.json",old)
        new=snap("2026-10-23");new["trends"][0]["src"]=[{"l":"https://one"},{"l":"https://two"},{"l":"https://two"}]
        result=publish(new,self.directory,self.latest)
        self.assertEqual(result["trends"][0]["new_source_count"],1)
    def test_calendar_cross_year(self):
        stats=trend_stats([row("2025-12-31",["a"]),row("2026-01-01",["a"])],"a","2026-01-01")
        self.assertEqual(stats["current_streak_days"],2)
    def test_invalid_dates_do_not_enter_history(self):
        atomic_json(self.directory/"2026-10-42.json",snap("2026-10-42"))
        history,docs,_=read_archive(self.directory)
        self.assertEqual(history,[]);self.assertEqual(docs,{})
if __name__=="__main__":unittest.main()
