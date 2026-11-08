#!/usr/bin/env python3
"""从探测结果生成订阅文件、状态表与可视化后台数据。

输出：
  dist/list.json        全量状态
  dist/tvbox.json       多仓列表（按实测质量排序）
  dist/status.md        可读状态表（含趋势列）
  docs/data/dashboard.json  可视化后台的唯一数据源
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import score_all  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "dist" / "probe.json"
HISTORY = ROOT / "dist" / "history.json"
MIRRORS = ROOT / "dist" / "mirrors.json"
MERGE_META = ROOT / "dist" / "merge-meta.json"
DEGRADED = ROOT / "dist" / "degraded.json"
DIST = ROOT / "dist"
DOCS_DATA = ROOT / "docs" / "data"

DEFAULT_REPO = "TVboxorg/TVbox"


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.is_file():
        return default or {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else (default or {})
    except (json.JSONDecodeError, OSError):
        return default or {}


def detect_repo() -> str:
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env and "/" in env:
        return env
    mirrors = load_json(MIRRORS)
    if mirrors.get("repo"):
        return str(mirrors["repo"])
    return DEFAULT_REPO


def latency_bucket(ms: int) -> str:
    if not ms:
        return "unknown"
    if ms < 800:
        return "fast"
    if ms < 2500:
        return "normal"
    return "slow"


def main() -> int:
    if not PROBE.is_file():
        print("missing dist/probe.json — run scripts/probe.py first", file=sys.stderr)
        return 1

    data = load_json(PROBE)
    items = data.get("items") or []
    history = load_json(HISTORY)
    hist_sources = history.get("sources") or {}
    scores = score_all(items, hist_sources)
    mirrors = load_json(MIRRORS)
    merge_meta = load_json(MERGE_META)
    degraded = load_json(DEGRADED) if DEGRADED.is_file() else {}
    repo = detect_repo()

    up_items = [x for x in items if x.get("ok")]
    pref_up = [x for x in up_items if x.get("group") == "pref"]
    back_up = [x for x in up_items if x.get("group") != "pref"]
    jar_ok = [x for x in up_items if x.get("jar_status") == "ok"]
    jar_mismatch = [x for x in up_items if x.get("jar_md5_match") is False]
    multi_up = [x for x in up_items if x.get("multi_count")]
    generated_at = data.get("generated_at") or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")

    all_scores = [v["score"] for v in scores.values()]
    online_ids = [str(x.get("id") or x.get("url")) for x in items if x.get("ok")]
    online_scores = [scores[i]["score"] for i in online_ids if i in scores]
    avg_score = round(sum(online_scores) / len(online_scores)) if online_scores else 0
    avg_all = round(sum(all_scores) / len(all_scores)) if all_scores else 0
    grade_counts: dict[str, int] = {}
    for v in scores.values():
        grade_counts[v["grade"]] = grade_counts.get(v["grade"], 0) + 1

    summary = {
        "total": len(items),
        "up": len(up_items),
        "down": len(items) - len(up_items),
        "jar_ok": len(jar_ok),
        "jar_md5_mismatch": len(jar_mismatch),
        "multi": len(multi_up),
        "sites_total": sum(x.get("sites_valid") or 0 for x in up_items),
        "netdisk_filtered": merge_meta.get("netdisk_filtered", 0),
        "cms_dead": merge_meta.get("cms_dead", 0),
        "mode": merge_meta.get("mode", "mixed"),
        "elapsed_sec": data.get("elapsed_sec"),
        "degraded": bool(degraded),
        "avg_score": avg_score,
        "avg_score_all": avg_all,
        "grades": grade_counts,
    }

    list_payload = {
        "name": repo,
        "homepage": "https://www.tvbox.org/",
        "repo": f"https://github.com/{repo}",
        "generated_at": generated_at,
        "probe_version": data.get("probe_version", 1),
        "elapsed_sec": data.get("elapsed_sec"),
        "summary": summary,
        "items": items,
    }
    (DIST / "list.json").write_text(
        json.dumps(list_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 多仓列表：可用优先 → jar 正常优先 → 延迟低优先
    ordered = sorted(
        pref_up + back_up,
        key=lambda x: (
            0 if x.get("jar_status") == "ok" else 1,
            x.get("ms") or 99999,
        ),
    )
    if not ordered:
        ordered = items
    tvbox_payload = {
        "urls": [
            {"url": x["url"], "name": x.get("name") or x["url"]}
            for x in ordered
        ],
        "homepage": "https://www.tvbox.org/",
        "generated_at": generated_at,
    }
    (DIST / "tvbox.json").write_text(
        json.dumps(tvbox_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---------- status.md ----------
    lines = [
        "# 接口探测状态",
        "",
        f"- 仓库：https://github.com/{repo}",
        f"- 生成时间（UTC）：`{generated_at}`",
        f"- 可用：**{len(up_items)}** / {len(items)}",
        f"- spider 可用：**{len(jar_ok)}**，MD5 不符：{len(jar_mismatch)}，多仓：{len(multi_up)}",
        f"- 可用站点合计：**{summary['sites_total']}**",
        f"- 聚合模式：**{'纯净（仅 CMS 接口，实测可出片）' if summary.get('mode') == 'pure-cms' else '混合'}**",
        f"- 已排除网盘站：**{summary.get('netdisk_filtered', 0)}** 个（需网盘会员，播放不了）",
        f"- 已排除失效 CMS 接口：**{summary.get('cms_dead', 0)}** 个（请求无影片列表）",
    ]
    if degraded:
        lines.append(f"- ⚠️ 本次聚合降级：`{degraded.get('reason')}`，沿用上次 official.json")
    lines += [
        "",
        "判定口径：先用 App 真实 UA `okhttp/3.15` 拉取；配置须能解析为 JSON 且 "
        "`sites` 内每项含 `key/type/api`；`spider` 非空时须可下载、是合法 zip、"
        "MD5 与 `;md5;` 声明一致。`urls` 存在按多仓处理。",
        "",
        "| 状态 | 分组 | 名称 | 站点 | jar | 多仓 | 7日 | 连续 | 耗时 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for x in items:
        sid = str(x.get("id") or x.get("url"))
        h = hist_sources.get(sid) or {}
        sc = scores.get(sid) or {}
        score_txt = f"{sc.get('grade', '-')}{sc.get('score', 0)}"
        mark = "UP" if x.get("ok") else "DOWN"
        desc = (x.get("desc") or x.get("error") or x.get("kind") or "").replace("|", "/")
        name = (x.get("name") or "").replace("|", "/")
        sites = x.get("sites_valid")
        jar = x.get("jar_status") or "-"
        if x.get("jar_md5_match") is False:
            jar = "md5!"
        multi = x.get("multi_count") or "-"
        uptime = h.get("uptime_7d")
        uptime_txt = f"{uptime * 100:.0f}%" if isinstance(uptime, (int, float)) else "-"
        if x.get("ok"):
            streak = f"↑{h.get('streak_up', 0)}"
        else:
            streak = f"↓{h.get('streak_down', 0)}"
        lines.append(
            f"| {mark} | {x.get('group','')} | {name} `{score_txt}` | {sites if sites else '-'} "
            f"| {jar} | {multi} | {uptime_txt} | {streak} | {x.get('ms', 0)}ms | {desc[:44]} |"
        )
    lines.append("")
    (DIST / "status.md").write_text("\n".join(lines), encoding="utf-8")

    # ---------- 可视化后台数据 ----------
    dashboard_sources = []
    for x in items:
        sid = str(x.get("id") or x.get("url"))
        h = hist_sources.get(sid) or {}
        sc = scores.get(sid) or {}
        dashboard_sources.append({
            "id": sid,
            "name": x.get("name", ""),
            "score": sc.get("score", 0),
            "grade": sc.get("grade", "D"),
            "group": x.get("group", ""),
            "url": x.get("url", ""),
            "desc": x.get("desc", ""),
            "ok": bool(x.get("ok")),
            "ms": x.get("ms", 0),
            "latency": latency_bucket(x.get("ms") or 0),
            "kind": x.get("kind", ""),
            "error": x.get("error", ""),
            "sitesTotal": x.get("sites_total", 0),
            "sitesValid": x.get("sites_valid", 0),
            "types": x.get("types") or {},
            "jarStatus": x.get("jar_status", "none"),
            "jarUrl": x.get("jar_url", ""),
            "jarNote": x.get("jar_note", ""),
            "jarMd5Match": x.get("jar_md5_match"),
            "jarSize": x.get("jar_size", 0),
            "multiCount": x.get("multi_count", 0),
            "isLive": bool(x.get("is_live")),
            "uaUsed": x.get("ua_used", ""),
            "uptime7d": h.get("uptime_7d"),
            "checks": h.get("checks", 0),
            "streakUp": h.get("streak_up", 0),
            "streakDown": h.get("streak_down", 0),
            "recent": h.get("recent") or [],
            "lastChangeAt": h.get("last_change_at", ""),
            "active": not h.get("inactive", False),
        })

    mirrors_out = {}
    for filename, rows in (mirrors.get("files") or {}).items():
        mirrors_out[filename] = [
            {"name": r.get("name"), "label": r.get("label"), "url": r.get("url"),
             "ok": bool(r.get("ok")), "status": r.get("status"),
             "size": r.get("size"), "ms": r.get("ms")}
            for r in rows if isinstance(r, dict)
        ]

    dashboard = {
        "generatedAt": generated_at,
        "repo": repo,
        "summary": summary,
        "sources": dashboard_sources,
        "runs": history.get("runs") or [],
        "mirrors": mirrors_out,
        "merge": {
            "primary": merge_meta.get("primary", ""),
            "primaryJarStatus": merge_meta.get("primary_jar_status", ""),
            "sites": merge_meta.get("sites", summary["sites_total"]),
            "parses": merge_meta.get("parses", 0),
            "lives": merge_meta.get("lives", 0),
            "sources": merge_meta.get("sources") or [],
        },
        "degraded": degraded or None,
    }

    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    (DOCS_DATA / "dashboard.json").write_text(
        json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"built list.json tvbox.json status.md + docs/data (up={len(up_items)}/{len(items)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
