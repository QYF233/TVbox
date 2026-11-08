#!/usr/bin/env python3
"""源质量评分。

100 分制，只在「可验证的信号」上给分：
  可用性 40   —— 本次探测能加载配置
  spider  20  —— jar 可下载 / MD5 一致给满分；不需要 jar（直播、多仓、纯 CMS）给部分分
  站点数  20  —— 100 个有效站点封顶
  延迟    10  —— 越低越高
  稳定性  10  —— 7 日可用率

离线源按历史可用率折算，最高 15 分，避免把「偶尔抖动」和「彻底死掉」混为一谈。
"""
from __future__ import annotations

GRADES = (
    (85, "S"),
    (70, "A"),
    (55, "B"),
    (40, "C"),
    (0, "D"),
)


def grade(score: int) -> str:
    for threshold, label in GRADES:
        if score >= threshold:
            return label
    return "D"


def latency_points(ms: int) -> int:
    if not ms:
        return 0
    if ms <= 500:
        return 10
    if ms <= 1500:
        return 7
    if ms <= 3000:
        return 4
    return 1


def score_source(item: dict, history_entry: dict | None = None) -> int:
    """给单个源打分，返回 0~100 的整数。"""
    hist = history_entry or {}
    uptime = hist.get("uptime_7d")
    if not isinstance(uptime, (int, float)):
        uptime = 0.0
    uptime = max(0.0, min(1.0, float(uptime)))

    # 样本量置信度：探测次数少时，稳定性得分打折，避免新源直接满绩
    checks = hist.get("checks") or 0
    confidence = min(1.0, 0.5 + checks / 24.0)

    if not item.get("ok"):
        # 离线：按历史信誉给分，最高 15
        return int(round(uptime * confidence * 15))

    score = 40.0

    jar_status = item.get("jar_status") or "none"
    md5_match = item.get("jar_md5_match")
    # jar 不可用意味着所有 type=3 爬虫站点都会失效，属于硬伤
    jar_failed = (md5_match is False) or (jar_status == "fail")
    if jar_failed:
        pass                       # jar 分归零
    elif jar_status == "ok":
        score += 20
    elif jar_status in ("none", "local"):
        # 直播源、多仓、纯 CMS 不需要 jar，给部分分
        score += 12

    sites = item.get("sites_valid") or 0
    score += min(sites / 100.0, 1.0) * 20

    score += latency_points(int(item.get("ms") or 0))

    score += uptime * confidence * 10

    result = int(round(max(0.0, min(100.0, score))))
    if jar_failed:
        # 站点再多也救不回来，封顶 B 级
        result = min(result, 55)
    return result


def score_all(items: list[dict], hist_sources: dict | None = None) -> dict[str, dict]:
    """批量打分，返回 {source_id: {"score": int, "grade": str}}。"""
    hist_sources = hist_sources or {}
    result: dict[str, dict] = {}
    for item in items:
        sid = str(item.get("id") or item.get("url") or "")
        if not sid:
            continue
        score = score_source(item, hist_sources.get(sid) or {})
        result[sid] = {"score": score, "grade": grade(score)}
    return result
