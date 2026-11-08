#!/usr/bin/env python3
"""维护接口探测历史，计算连续可用次数、7 日可用率与状态变更。

输入：dist/probe.json（本次探测结果）
输出：dist/history.json（累积历史）、dist/changes.json（本次状态变更）
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "dist" / "probe.json"
HISTORY = ROOT / "dist" / "history.json"
CHANGES = ROOT / "dist" / "changes.json"

RECENT_KEEP = 30          # 每个源保留最近多少次结果
RUN_KEEP = 90             # 全局保留最近多少次运行
UPTIME_WINDOW = 28        # 7 日窗口（6 小时一次 ≈ 28 次）


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except (json.JSONDecodeError, OSError):
        return default


def uptime_ratio(recent: list[int]) -> float:
    window = recent[-UPTIME_WINDOW:]
    if not window:
        return 0.0
    return round(sum(window) / len(window), 4)


def main() -> int:
    if not PROBE.is_file():
        print("missing dist/probe.json — run scripts/probe.py first", file=sys.stderr)
        return 1

    probe = load_json(PROBE, {})
    items = probe.get("items") or []
    if not items:
        print("probe.json has no items", file=sys.stderr)
        return 1

    history = load_json(HISTORY, {"sources": {}, "runs": []})
    prev_sources: dict = history.get("sources") or {}
    stamp = probe.get("generated_at") or now_iso()

    changes: list[dict] = []
    new_sources: dict = {}

    for item in items:
        sid = str(item.get("id") or item.get("url") or "")
        if not sid:
            continue
        ok = bool(item.get("ok"))
        prev = prev_sources.get(sid) or {}
        recent = list(prev.get("recent") or [])
        recent.append(1 if ok else 0)
        recent = recent[-RECENT_KEEP:]

        prev_ok = prev.get("last_ok")
        if prev_ok is None:
            # 首次记录，不算状态变更
            change = ""
        elif prev_ok and not ok:
            change = "down"
        elif not prev_ok and ok:
            change = "up"
        else:
            change = ""

        if change:
            changes.append({
                "id": sid,
                "name": item.get("name", ""),
                "group": item.get("group", ""),
                "url": item.get("url", ""),
                "change": change,
                "from": "UP" if prev_ok else "DOWN",
                "to": "UP" if ok else "DOWN",
                "reason": "" if ok else (item.get("error") or item.get("kind") or ""),
            })

        # 连续状态计数
        if not prev:
            streak_up = 1 if ok else 0
            streak_down = 0 if ok else 1
        elif ok:
            streak_up = (prev.get("streak_up") or 0) + 1
            streak_down = 0
        else:
            streak_up = 0
            streak_down = (prev.get("streak_down") or 0) + 1

        entry = {
            "name": item.get("name", ""),
            "url": item.get("url", ""),
            "group": item.get("group", ""),
            "checks": (prev.get("checks") or 0) + 1,
            "ups": (prev.get("ups") or 0) + (1 if ok else 0),
            "streak_up": streak_up,
            "streak_down": streak_down,
            "recent": recent,
            "uptime_7d": uptime_ratio(recent),
            "last_ok": ok,
            "last_check_at": stamp,
            "last_change_at": stamp if change else prev.get("last_change_at", ""),
            "last_up_at": stamp if ok else prev.get("last_up_at", ""),
            "last_down_at": "" if ok else stamp,
        }
        new_sources[sid] = entry

    # 保留已从 sources.yaml 移除的源的历史，标记 inactive
    for sid, prev in prev_sources.items():
        if sid in new_sources:
            continue
        kept = dict(prev)
        kept["inactive"] = True
        kept["uptime_7d"] = uptime_ratio(kept.get("recent") or [])
        new_sources[sid] = kept

    runs = list(history.get("runs") or [])
    runs.append({
        "at": stamp,
        "up": sum(1 for x in items if x.get("ok")),
        "total": len(items),
        "jar_ok": sum(1 for x in items if x.get("jar_status") == "ok"),
    })
    runs = runs[-RUN_KEEP:]

    payload = {
        "updated_at": stamp,
        "recent_keep": RECENT_KEEP,
        "sources": new_sources,
        "runs": runs,
    }
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")

    CHANGES.write_text(json.dumps({
        "at": stamp,
        "count": len(changes),
        "items": changes,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    downs = [c for c in changes if c["change"] == "down"]
    ups = [c for c in changes if c["change"] == "up"]
    print(f"history updated: sources={len(new_sources)} runs={len(runs)} "
          f"changes={len(changes)} (up={len(ups)} down={len(downs)})")
    for c in changes:
        arrow = "↑" if c["change"] == "up" else "↓"
        print(f"  {arrow} {c['name']}: {c['from']} -> {c['to']} {c['reason'][:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
