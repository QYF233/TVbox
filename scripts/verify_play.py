#!/usr/bin/env python3
"""验证 CMS 站点是否真能播放，并给每个站打分。

对每个站执行三步：
  1. ?ac=videolist&pg=1      取第一部影片的 vod_id
  2. ?ac=detail&ids=<id>     取详情，解析 vod_play_url
  3. 请求第一个播放地址       判断是 m3u8 还是 mp4

只有第 3 步真的拿到媒体流，才算「可播放」。这是区别于「有影片列表」的关键一层。

输出：就地更新 cms_pool.json，为每个站补上 _playable / _score 等字段。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import http_get, is_blocked, normalize_url, ssl_context  # noqa: E402

TIMEOUT = 12
MEDIA_TIMEOUT = 10
WORKERS = 12


def api_call(api: str, params: str, timeout: int = TIMEOUT):
    """拼参数请求 maccms 接口，返回解析后的 dict。"""
    base = api.strip()
    sep = "&" if "?" in base else "?"
    ok, status, body, err = http_get(f"{base}{sep}{params}", timeout=timeout)
    if not ok or not body:
        return None, err or f"HTTP {status}"
    try:
        data = json.loads(body.decode("utf-8", "ignore"))
    except Exception:
        return None, "not-json"
    return (data if isinstance(data, dict) else None), ""


def first_video(api: str) -> tuple[dict | None, int, str]:
    """取第一页第一部影片，顺带返回总条数。"""
    data, err = api_call(api, "ac=videolist&pg=1")
    if not data:
        return None, 0, err
    videos = data.get("list")
    if not isinstance(videos, list) or not videos:
        return None, 0, "empty-list"
    first = videos[0]
    if not isinstance(first, dict) or first.get("vod_id") is None:
        return None, 0, "no-vod-id"
    total = data.get("total")
    try:
        count = int(total)
    except (TypeError, ValueError):
        count = len(videos)
    return first, count or len(videos), ""


def parse_play_urls(text) -> list[str]:
    """从 vod_play_url 里抽出播放地址。

    格式：`第01集$http://a.m3u8#第02集$http://b.m3u8`，
    多组播放源之间用 `$$$` 分隔，取第一组。也兼容不带集名的裸地址。
    """
    if not isinstance(text, str) or not text.strip():
        return []
    group = text.split("$$$")[0]
    urls: list[str] = []
    for entry in group.split("#"):
        entry = entry.strip()
        if not entry:
            continue
        if "$" in entry:
            candidate = entry.split("$", 1)[1].strip()
        else:
            candidate = entry
        if candidate.startswith(("http://", "https://")):
            urls.append(candidate)
    return urls


def probe_media(url: str) -> tuple[bool, str, str]:
    """请求播放地址，判断是否真的能取到媒体流。"""
    if is_blocked(url):
        return False, "", "blocked-host"
    headers = {
        "User-Agent": "okhttp/3.15",
        "Range": "bytes=0-2047",
        "Accept": "*/*",
    }
    try:
        req = urllib.request.Request(normalize_url(url), headers=headers)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl_context()),
        )
        with opener.open(req, timeout=MEDIA_TIMEOUT) as resp:
            body = resp.read(65536)
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as exc:
        return False, "", f"HTTP {exc.code}"
    except Exception as exc:
        return False, "", f"{type(exc).__name__}: {exc}"[:50]

    head = body[:4096]
    if b"#EXTM3U" in head:
        return True, "m3u8", ""
    if ctype.startswith("video/"):
        return True, ctype.split(";")[0], ""
    if len(body) > 8 and body[4:8] == b"ftyp":
        return True, "mp4", ""
    if len(body) == 0:
        return False, "", "empty-body"
    return False, "", f"not-media ctype={ctype[:24]}"


def verify_site(site: dict) -> dict:
    """完整验证一个站：列表 → 详情 → 播放。"""
    api = str(site.get("api") or "")
    result = {
        "api": api,
        "playable": False,
        "mediaKind": "",
        "video": "",
        "playUrl": "",
        "videos": 0,
        "ms": 0,
        "reason": "",
    }
    if not api:
        result["reason"] = "no-api"
        return result

    started = time.time()
    first, total, err = first_video(api)
    if not first:
        result["ms"] = int((time.time() - started) * 1000)
        result["reason"] = f"list: {err}"
        return result

    result["videos"] = total
    result["video"] = str(first.get("vod_name") or "")
    vod_id = first.get("vod_id")

    detail, derr = api_call(api, f"ac=detail&ids={vod_id}")
    play_urls: list[str] = []
    if detail and isinstance(detail.get("list"), list) and detail["list"]:
        entry = detail["list"][0]
        if isinstance(entry, dict):
            play_urls = parse_play_urls(entry.get("vod_play_url"))
            if not result["video"]:
                result["video"] = str(entry.get("vod_name") or "")

    if not play_urls:
        result["ms"] = int((time.time() - started) * 1000)
        result["reason"] = f"detail: {derr or 'no-play-url'}"
        return result

    result["playUrl"] = play_urls[0]
    ok, kind, nerr = probe_media(play_urls[0])
    if not ok:
        result["ms"] = int((time.time() - started) * 1000)
        result["reason"] = f"media: {nerr}"
        return result

    result["playable"] = True
    result["mediaKind"] = kind
    result["ms"] = int((time.time() - started) * 1000)
    return result


def score_site(item: dict, result: dict) -> int:
    """CMS 站评分：播放可用 40 + 影片数 20 + 延迟 20 + 详情完整 20。"""
    score = 0
    if result["playable"]:
        score += 40
    videos = result.get("videos") or item.get("_videos") or 0
    score += int(min(videos / 30.0, 1.0) * 20)
    ms = result.get("ms") or 0
    if ms:
        if ms <= 1500:
            score += 20
        elif ms <= 3000:
            score += 14
        elif ms <= 6000:
            score += 8
        else:
            score += 3
    if result.get("playUrl"):
        score += 20
    return max(0, min(100, score))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", default="cms_pool.json")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--timeout", type=int, default=TIMEOUT, help="保留参数，兼容旧调用")
    args = parser.parse_args()
    del args.timeout

    path = Path(args.pool)
    if not path.is_file():
        print(f"missing {path}", file=sys.stderr)
        return 1
    pool = json.loads(path.read_text(encoding="utf-8"))
    sites = pool.get("sites") or []
    if not sites:
        print("pool is empty", file=sys.stderr)
        return 1

    print(f"验证 {len(sites)} 个站的播放能力 ...", flush=True)
    started = time.time()
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(verify_site, site): str(site.get("api")) for site in sites}
        done = 0
        for future in as_completed(futures):
            api = futures[future]
            done += 1
            try:
                results[api] = future.result()
            except Exception as exc:
                results[api] = {"api": api, "playable": False, "mediaKind": "",
                                "video": "", "playUrl": "", "videos": 0, "ms": 0,
                                "reason": f"crash {exc}"[:50]}
            if done % 10 == 0:
                alive = sum(1 for r in results.values() if r["playable"])
                print(f"  {done}/{len(sites)}  可播放 {alive}", flush=True)

    playable = 0
    for site in sites:
        api = str(site.get("api") or "")
        result = results.get(api) or {}
        site["_playable"] = bool(result.get("playable"))
        site["_mediaKind"] = result.get("mediaKind", "")
        site["_playUrl"] = result.get("playUrl", "")
        site["_playMs"] = result.get("ms", 0)
        site["_playReason"] = result.get("reason", "")
        if result.get("video"):
            site["_sample"] = result["video"]
        site["_score"] = score_site(site, result)
        if site["_playable"]:
            playable += 1

    sites.sort(key=lambda s: (-int(s.get("_score") or 0), s.get("name") or ""))
    pool["sites"] = sites
    pool["verified_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pool["playable"] = playable
    pool["play_checked"] = len(sites)
    pool["play_elapsed_sec"] = round(time.time() - started, 1)
    path.write_text(json.dumps(pool, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n可播放 {playable}/{len(sites)}，用时 {pool['play_elapsed_sec']}s")
    print(f"写入 {path}")
    for site in sites[:12]:
        flag = "PLAY" if site.get("_playable") else "DEAD"
        print(f"  [{flag}] {site.get('_score', 0):3d}  {str(site.get('name'))[:22]:24s} "
              f"{site.get('_mediaKind') or '-':6s} {str(site.get('_playReason') or '')[:34]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
