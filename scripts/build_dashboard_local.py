#!/usr/bin/env python3
"""为内网部署生成监控台数据（docs/data/dashboard.json 的本地版）。

数据源只有 cms_pool.json，不依赖 probe/merge。字段名与云端版本保持一致，
页面无需区分布局，只在表头文案上按 mode 切换。
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "cms_pool.json"
OUT = ROOT / "dist" / "dashboard.json"
RUNS = ROOT / "dist" / "runs_local.json"
LIMIT = 90


def grade_of(score: int) -> str:
    for threshold, label in ((85, "S"), (70, "A"), (55, "B"), (40, "C")):
        if score >= threshold:
            return label
    return "D"


def latency_bucket(ms: int) -> str:
    if not ms:
        return "unknown"
    if ms < 1500:
        return "fast"
    if ms < 3500:
        return "normal"
    return "slow"


def main() -> int:
    if not POOL.is_file():
        print(f"missing {POOL}", file=sys.stderr)
        return 1
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    sites = [s for s in (pool.get("sites") or []) if isinstance(s, dict)]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sources = []
    for item in sites:
        api = str(item.get("api") or "")
        playable = bool(item.get("_playable"))
        score = int(item.get("_score") or 0)
        videos = int(item.get("_videos") or 0)
        ms = int(item.get("_playMs") or 0)
        sources.append({
            "id": hashlib.md5(api.encode("utf-8")).hexdigest()[:12],
            "name": str(item.get("name") or ""),
            "group": "cms",
            "url": api,
            "desc": str(item.get("_sample") or ""),
            "ok": playable,
            "ms": ms,
            "latency": latency_bucket(ms),
            "kind": "cms",
            "error": str(item.get("_playReason") or ""),
            "sitesTotal": videos,
            "sitesValid": videos,
            "types": {"1": 1},
            "jarStatus": "ok" if playable else "fail",
            "jarUrl": str(item.get("_playUrl") or ""),
            "jarNote": str(item.get("_mediaKind") or ""),
            "jarMd5Match": None,
            "jarSize": 0,
            "multiCount": 0,
            "isLive": False,
            "uaUsed": "okhttp/3.15",
            "uptime7d": None,
            "checks": 1,
            "streakUp": 1 if playable else 0,
            "streakDown": 0 if playable else 1,
            "recent": [1 if playable else 0],
            "lastChangeAt": str(pool.get("verified_at") or ""),
            "active": True,
            "score": score,
            "grade": grade_of(score),
        })

    sources.sort(key=lambda s: (-s["score"], s["name"]))
    playable = sum(1 for s in sources if s["ok"])
    scores = [s["score"] for s in sources]
    grades: dict[str, int] = {}
    for s in sources:
        grades[s["grade"]] = grades.get(s["grade"], 0) + 1

    runs: list[dict] = []
    if RUNS.is_file():
        try:
            loaded = json.loads(RUNS.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                runs = loaded
        except (json.JSONDecodeError, OSError):
            runs = []
    runs.append({"at": stamp, "up": playable, "total": len(sources),
                 "jar_ok": playable})
    runs = runs[-LIMIT:]
    RUNS.write_text(json.dumps(runs, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")

    dashboard = {
        "generatedAt": stamp,
        "repo": "10.0.0.1/tvbox",
        "mode": "local",
        "summary": {
            "total": len(sources),
            "up": playable,
            "down": len(sources) - playable,
            "jar_ok": playable,
            "jar_md5_mismatch": 0,
            "multi": 0,
            "sites_total": sum(s["sitesValid"] for s in sources),
            "netdisk_filtered": 0,
            "cms_dead": len(sources) - playable,
            "elapsed_sec": pool.get("play_elapsed_sec") or 0,
            "degraded": False,
            "avg_score": round(sum(scores) / len(scores)) if scores else 0,
            "avg_score_all": round(sum(scores) / len(scores)) if scores else 0,
            "grades": grades,
            "mode": "local",
        },
        "sources": sources,
        "runs": runs,
        "mirrors": {},
        "merge": {
            "primary": "内网直出",
            "primaryJarStatus": "ok",
            "sites": len(sources),
            "parses": 0,
            "lives": 0,
            "sources": [],
        },
        "degraded": None,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT}  站点 {len(sources)} / 可播 {playable} / 均分 "
          f"{dashboard['summary']['avg_score']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
