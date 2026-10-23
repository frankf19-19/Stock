"""r1154:永久趨勢索引、嚴格逐日統計及不可變修訂。只用標準函式庫。"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile


def valid_day(value):
    try:
        return isinstance(value, str) and dt.date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError):
        return False


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)  # 只清本次未發布的臨時檔,不碰歷史


def immutable_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    try:
        with path.open("x", encoding="utf-8") as f:
            f.write(raw)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != raw:
            raise ValueError("歷史檔已存在且內容不同:" + str(path))


def archive_value(directory, day, value, kind="revisions"):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    relative = Path(kind) / day / (digest + ".json")
    immutable_json(Path(directory) / relative, value)
    return relative.as_posix()


def read_archive(directory="trends", previous=None):
    directory = Path(directory)
    active = read_json(directory / "active.json", {}) or {}
    pointers = active.get("dates", {})
    if not isinstance(pointers, dict):
        raise ValueError("趨勢有效版本索引格式錯誤")
    dates = {p.stem for p in directory.glob("????-??-??.json") if valid_day(p.stem)}
    dates.update(d for d in pointers if valid_day(d))
    saved = read_json(directory / "history.json", {}) or {}
    previous_rows = list(saved.get("hist") or []) + list((previous or {}).get("hist") or [])
    history = {h["d"]: dict(h) for h in previous_rows if isinstance(h, dict) and valid_day(h.get("d"))}
    docs, warnings = {}, []
    for day in sorted(dates):
        name = pointers.get(day, day + ".json")
        target = (directory / name).resolve()
        if not target.is_relative_to(directory.resolve()):
            raise ValueError("趨勢版本路徑超出資料夾")
        doc = read_json(target)
        ok = isinstance(doc, dict) and doc.get("date") == day and isinstance(doc.get("trends"), list)
        if ok:
            ok = all(isinstance(t, dict) and isinstance(t.get("key"), str) and t["key"] for t in doc["trends"])
        if not ok:
            history[day] = {"d": day, "keys": None, "status": "invalid"}
            warnings.append(day + " 日檔無法驗證")
            continue
        docs[day] = doc
        history[day] = {"d": day, "keys": sorted({t["key"] for t in doc["trends"]}), "status": "ok"}
    return sorted(history.values(), key=lambda h: h["d"]), docs, warnings


def trend_stats(history, key, day):
    if not valid_day(day):
        raise ValueError("日期格式錯誤")
    rows = {h["d"]: h for h in history if valid_day(h.get("d")) and h["d"] <= day}
    observed = {d: set(h["keys"]) for d, h in rows.items()
                if isinstance(h.get("keys"), list) and h.get("status", "ok") == "ok"}
    seen = sorted(d for d, keys in observed.items() if key in keys)
    today = dt.date.fromisoformat(day)
    count, start, cursor = 0, None, today
    while key in observed.get(cursor.isoformat(), set()):
        count += 1
        start = cursor.isoformat()
        cursor -= dt.timedelta(days=1)
    first_observed = min(rows) if rows else day
    begin = max(today - dt.timedelta(days=13), dt.date.fromisoformat(first_observed))
    window = [(begin + dt.timedelta(days=i)).isoformat() for i in range((today - begin).days + 1)]
    return {
        "first_seen": seen[0] if seen else None, "last_seen": seen[-1] if seen else None,
        "current_streak_days": count, "current_streak_start": start, "total_seen_days": len(seen),
        "window_days": len(window), "observed_days": sum(d in observed for d in window),
        "seen_last_14_days": sum(key in observed.get(d, set()) for d in window),
        "missing_days": sum(d not in observed for d in window),
    }


def decorate(snapshot, history, docs):
    result = dict(snapshot)
    day = result["date"]
    result["v"] = 2
    result["stats_through"] = day
    result["history_days"] = len(history)
    result["trends"] = []
    for original in snapshot.get("trends", []):
        t = dict(original)
        stats = trend_stats(history, t["key"], day)
        t.update(stats)
        t["days"], t["first"] = stats["current_streak_days"], stats["first_seen"]  # 舊版相容
        old_urls = {s.get("l") for d, doc in docs.items() if d < day
                    for prev in doc.get("trends", []) if prev.get("key") == t["key"]
                    for s in prev.get("src", []) if s.get("l")}
        current_urls = {s.get("l") for s in t.get("src", []) if s.get("l")}
        t["new_source_count"] = len(current_urls - old_urls)
        result["trends"].append(t)
    result.pop("hist", None)  # 完整索引另存,不讓每次開站下載全部歷史
    return result


def publish(snapshot, directory="trends", latest="trends.json", raw=None):
    directory = Path(directory)
    old = read_json(latest)
    if old and valid_day(old.get("date")):
        archive_value(directory, old["date"], old)  # 遷移前原 latest（含 hist）完整保留
    snapshot = {k: v for k, v in snapshot.items() if k != "hist"}
    day = snapshot["date"]
    if not valid_day(day):
        raise ValueError("發布日期無效")
    revision = archive_value(directory, day, snapshot)
    if raw is not None:
        archive_value(directory, day, raw, "raw")
    daily = directory / (day + ".json")
    if not daily.exists():
        immutable_json(daily, snapshot)  # 首版日檔永不覆寫
    active = read_json(directory / "active.json", {"v": 1, "dates": {}})
    if not isinstance(active, dict) or not isinstance(active.get("dates"), dict):
        raise ValueError("有效版本索引格式錯誤")
    active["dates"][day] = revision
    atomic_json(directory / "active.json", active)
    return rebuild(directory, latest, previous=old)


def rebuild(directory="trends", latest="trends.json", previous=None):
    """不呼叫 AI,從永久有效版本重建 latest 及完整索引。壞日檔明確記為未知。"""
    old = previous if previous is not None else read_json(latest)
    if old and valid_day(old.get("date")):
        archive_value(directory, old["date"], old)
    history, docs, warnings = read_archive(directory, old)
    if not docs:
        raise ValueError("沒有可用的永久日檔,保留原 latest")
    day = max(docs)
    result = decorate(docs[day], history, docs)
    result["history_warnings"] = warnings
    atomic_json(Path(directory) / "history.json", {"v": 2, "hist": history, "warnings": warnings})
    atomic_json(latest, result)
    return result
