#!/usr/bin/env python3
"""Merge working upstream TVBox configs into one pasteable official.json."""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import score_source  # noqa: E402
from validate import check_cms_api  # noqa: E402

PROBE = ROOT / "dist" / "probe.json"
HISTORY = ROOT / "dist" / "history.json"
OUT = ROOT / "dist" / "official.json"
META = ROOT / "dist" / "merge-meta.json"
DEGRADED = ROOT / "dist" / "degraded.json"
TIMEOUT = 18
UA = "TVboxorg-TVbox-merge/1.0 (+https://www.tvbox.org/; +https://github.com/TVboxorg/TVbox)"
MAX_SITES = 300
MAX_SOURCES = 12  # fetch budget: pref first, then back


def strip_json_noise(text: str) -> str:
    """Strip // and /* */ comments outside strings; tolerate trailing commas."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    esc = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                i += 2
                while i < n and text[i] not in "\r\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i = min(i + 2, n)
                continue
        out.append(ch)
        i += 1
    cleaned = "".join(out)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    return cleaned


def fetch(url: str) -> bytes:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
        return resp.read(2_000_000)


def parse_config(raw: bytes) -> dict[str, Any] | None:
    text = raw.decode("utf-8", errors="replace").lstrip("\ufeff").strip()
    if not text:
        return None
    for candidate in (text, strip_json_noise(text)):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and (
            "sites" in data or "lives" in data or "spider" in data
        ):
            return data
    return None


def abs_url(base: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("./") or value.startswith("../") or value.startswith("/"):
        return urllib.parse.urljoin(base, value)
    # jar;md5 or jar;md5;key style — take first segment if looks like path
    first = value.split(";")[0].strip()
    if first.startswith("http://") or first.startswith("https://"):
        return value  # keep full spider string with md5
    if first.startswith("./") or first.startswith("/"):
        joined = urllib.parse.urljoin(base, first)
        rest = value[len(first) :]
        return joined + rest
    return value


def spider_http(spider: str) -> str:
    """Extract http(s) jar URL from spider field (may include ;md5)."""
    if not spider:
        return ""
    first = spider.split(";")[0].strip()
    if first.startswith("http://") or first.startswith("https://"):
        return first
    return ""


def is_http_api(api: Any) -> bool:
    if not isinstance(api, str):
        return False
    api = api.strip()
    return api.startswith("http://") or api.startswith("https://")


def site_score(
    site: dict[str, Any],
    *,
    group: str,
    from_primary: bool,
    health: float = 0.0,
    source_ms: int = 0,
) -> int:
    """站点综合评分。

    排序依据以「可验证的信号」为准：主源优先、pref 分组、可移植性、
    来源历史可用率、实测延迟。不再依赖名字里有没有「4K」这类营销词。
    """
    score = 0
    if from_primary:
        score += 40
    if group == "pref":
        score += 20

    api = str(site.get("api") or "")
    stype = site.get("type")
    if site.get("searchable") in (1, True, "1"):
        score += 8
    if site.get("quickSearch") in (1, True, "1"):
        score += 4
    # type=1/4 是纯 HTTP 接口，不依赖 jar，迁移后存活率最高
    if stype in (1, 4):
        score += 15
    if stype == 3 and site.get("jar"):
        score += 6
    if is_http_api(api):
        score += 5

    # 来源历史可用率 0~1 → 0~25 分
    score += round(max(0.0, min(1.0, health)) * 25)

    # 延迟惩罚：每 500ms 扣 1 分，最多扣 8 分
    if source_ms:
        score -= min(int(source_ms // 500), 8)

    # 内容类别降权（保持原有过滤口径）
    name = str(site.get("name") or "")
    for bad in ("伦理", "福利", "色情", "成人"):
        if bad in name:
            score -= 30
    return score


def normalize_key(raw: str, source_id: str) -> str:
    key = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", raw or "site")
    key = key.strip("_")[:40] or "site"
    return f"tv_{source_id}_{key}"


# 网盘类站点：播放需要登录对应网盘账号，普通用户点进去也看不了，默认剔除
# 除了显式网盘名，还要覆盖「4K / 原盘 / 盘库 / 盘搜」这批实为网盘分享的站点，
# 以及 Emby / WebDAV / Alist 这类需要自建服务才能用的站
NETDISK_NAME = re.compile(
    r"网盘|云盘|夸克|天翼|115|alist|小雅|迅雷|uc网盘|百度网盘"
    r"|4k|原盘|盘库|盘搜|emby|webdav", re.I)
# api 形如 csp_PanCms / csp_AListGuard / csp_MyPanGuard；
# 用负向断言排掉 csp_PanConfigGuard 这类设置面板
NETDISK_API = re.compile(
    r"^csp_(?!.*Config).*(Pan|Quark|AList|AliYun|Uc|Baidu|Tianyi|115|Xiaoya)", re.I)
# ext 里出现网盘域名也判定为网盘源
NETDISK_EXT = re.compile(
    r"quark\.cn|aliyundrive|alipan|cloud\.189|115\.com|pan\.baidu|xiaoya|alist", re.I)


def is_netdisk_site(site: dict) -> bool:
    name = str(site.get("name") or "")
    api = str(site.get("api") or "")
    ext = site.get("ext")
    ext_str = ext if isinstance(ext, str) else json.dumps(ext, ensure_ascii=False) if ext else ""
    if NETDISK_NAME.search(name) or NETDISK_API.search(api) or NETDISK_EXT.search(ext_str):
        return True
    return False


def adapt_site(
    site: dict[str, Any],
    *,
    source_id: str,
    source_name: str,
    spider: str,
    primary: bool,
    jar_ok: bool = True,
) -> dict[str, Any] | None:
    if not isinstance(site, dict):
        return None
    api = site.get("api")
    stype = site.get("type")
    try:
        stype_i = int(stype) if stype is not None else -1
    except (TypeError, ValueError):
        stype_i = -1

    out = dict(site)
    out["type"] = stype_i if stype_i >= 0 else stype

    if primary:
        # 主源的站点原样保留，key/name 不改写
        return out

    # 非主源：只保留可合并的站点
    jar = spider_http(spider)
    if stype_i in (0, 1, 4) and is_http_api(api):
        pass
    elif stype_i == 3 and jar and isinstance(api, str) and api.startswith("csp_"):
        # jar 探测失败的源，其 type=3 站点依赖的 jar 必然不可用
        if not jar_ok:
            return None
        out["jar"] = jar
    else:
        return None

    orig_key = str(site.get("key") or site.get("name") or "site")
    out["key"] = normalize_key(orig_key, source_id)
    name = str(site.get("name") or orig_key)
    tag = source_name[:8]
    if tag and tag not in name:
        out["name"] = f"{name}·{tag}"
    return out


def merge_list(dst: list, src: list, keyfn) -> None:
    seen = {keyfn(x) for x in dst if isinstance(x, dict)}
    for item in src:
        if not isinstance(item, dict):
            continue
        k = keyfn(item)
        if not k or k in seen:
            continue
        seen.add(k)
        dst.append(item)


def load_health() -> dict[str, float]:
    """从 history.json 读取各源 7 日可用率，缺失时返回空表。"""
    if not HISTORY.is_file():
        return {}
    try:
        data = json.loads(HISTORY.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    sources = data.get("sources") or {}
    health: dict[str, float] = {}
    for sid, entry in sources.items():
        if not isinstance(entry, dict):
            continue
        ratio = entry.get("uptime_7d")
        if isinstance(ratio, (int, float)):
            health[sid] = float(ratio)
    return health


def load_cms_pool() -> list[dict]:
    """读取离线发现的 CMS 站点池（scripts/discover_cms.py 的产物）。"""
    path = ROOT / "cms_pool.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    sites = data.get("sites") if isinstance(data, dict) else None
    if not isinstance(sites, list):
        return []
    return [s for s in sites
            if isinstance(s, dict) and str(s.get("api") or "").startswith(("http://", "https://"))]


def write_degraded(reason: str, detail: dict | None = None) -> None:
    """记录本次聚合失败，但不覆盖已有 official.json。"""
    payload = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason,
        "detail": detail or {},
        "kept_previous": OUT.is_file(),
    }
    DEGRADED.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"degraded: {reason} (kept_previous={payload['kept_previous']})",
          file=sys.stderr)


def pick_sources(items: list[dict]) -> list[dict]:
    up = [x for x in items if x.get("ok")]
    pref = [x for x in up if x.get("group") == "pref"]
    back = [x for x in up if x.get("group") != "pref"]
    ordered = pref + back
    return ordered[:MAX_SOURCES]


def main() -> int:
    if not PROBE.is_file():
        print("missing dist/probe.json — run scripts/probe.py first", file=sys.stderr)
        return 1

    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    health_map = load_health()
    # 环境变量为空（CI 里仓库变量未设置）时按默认值处理
    exclude_netdisk = (os.environ.get("KEEP_NETDISK") or "0").strip() != "1"
    # 默认纯净模式：只保留纯 HTTP 接口站，内容可在本地直接验证，绝不含网盘
    only_cms = (os.environ.get("ONLY_CMS") or "1").strip() != "0"
    netdisk_skipped = 0
    cms_skipped = 0
    cms_dead = 0
    sources = pick_sources(probe.get("items") or [])
    if not sources:
        write_degraded("no-up-source", {"total": probe.get("count")})
        return 0 if OUT.is_file() else 1

    fetched: list[dict[str, Any]] = []
    for i, src in enumerate(sources, 1):
        name = src.get("name") or src.get("id")
        url = src["url"]
        print(f"[{i}/{len(sources)}] fetch {name} ...", flush=True)
        try:
            raw = fetch(url)
            cfg = parse_config(raw)
            if not cfg:
                print("  -> skip (parse fail)", flush=True)
                continue
            spider = abs_url(url, str(cfg.get("spider") or ""))
            sites = cfg.get("sites") if isinstance(cfg.get("sites"), list) else []
            print(f"  -> sites={len(sites)} spider={spider[:60]!r}", flush=True)
            fetched.append(
                {
                    "src": src,
                    "cfg": cfg,
                    "spider": spider,
                    "base": url,
                    "site_count": len(sites),
                }
            )
        except Exception as e:
            print(f"  -> err {type(e).__name__}: {e}", flush=True)

    if not fetched:
        write_degraded("no-config-fetched",
                       {"picked": [str(s.get("id")) for s in sources]})
        return 0 if OUT.is_file() else 1

    # 纯 CMS 模式：先并发验证每个接口是否真能返回影片列表
    cms_cache: dict[str, tuple[bool, int, str]] = {}
    if only_cms:
        candidates: set[str] = set()
        for row in fetched:
            for site in row["cfg"].get("sites") or []:
                if not isinstance(site, dict):
                    continue
                if site.get("type") in (0, 1, 4):
                    api = str(site.get("api") or "")
                    if is_http_api(api):
                        candidates.add(api)
        if candidates:
            print(f"验证 {len(candidates)} 个 CMS 接口 ...", flush=True)
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(check_cms_api, api): api for api in candidates}
                for future in as_completed(futures):
                    api = futures[future]
                    try:
                        cms_cache[api] = future.result()
                    except Exception as exc:
                        cms_cache[api] = (False, 0, str(exc)[:40])
            alive = sum(1 for v in cms_cache.values() if v[0])
            print(f"  CMS 可用 {alive}/{len(cms_cache)}", flush=True)

    # 主源：pref 分组优先，组内按综合评分（可用性+jar+站点数+延迟+稳定性）
    def primary_rank(row: dict) -> tuple:
        src = row["src"]
        pref = 1 if src.get("group") == "pref" else 0
        uptime = health_map.get(str(src.get("id")), 0.0)
        sc = score_source(src, {"uptime_7d": uptime})
        return (pref, sc, row["site_count"])

    fetched.sort(key=primary_rank, reverse=True)
    primary = fetched[0]
    primary_id = str(primary["src"].get("id") or "primary")

    sites_scored: list[tuple[int, dict]] = []
    parses: list = []
    lives: list = []
    rules: list = []
    flags: list = []
    ads: list = []
    doh: list = []

    meta_sources = []

    for idx, row in enumerate(fetched):
        src = row["src"]
        cfg = row["cfg"]
        is_primary = idx == 0
        sid = str(src.get("id") or f"s{idx}")
        sname = str(src.get("name") or sid)
        spider = row["spider"]
        added = 0
        skipped = 0
        for site in cfg.get("sites") or []:
            if exclude_netdisk and isinstance(site, dict) and is_netdisk_site(site):
                netdisk_skipped += 1
                continue
            if only_cms and isinstance(site, dict) and site.get("type") not in (0, 1, 4):
                cms_skipped += 1
                continue
            if only_cms and isinstance(site, dict) and site.get("type") in (0, 1, 4):
                api = str(site.get("api") or "")
                if is_http_api(api):
                    res = cms_cache.get(api)
                    if res is not None and not res[0]:
                        cms_dead += 1
                        continue
            adapted = adapt_site(
                site,
                source_id=sid,
                source_name=sname,
                spider=spider,
                primary=is_primary,
                jar_ok=src.get("jar_status") == "ok",
            )
            if not adapted:
                skipped += 1
                continue
            score = site_score(
                adapted,
                group=str(src.get("group") or ""),
                from_primary=is_primary,
                health=health_map.get(sid, 0.0),
                source_ms=int(src.get("ms") or 0),
            )
            sites_scored.append((score, adapted))
            added += 1

        if isinstance(cfg.get("parses"), list):
            merge_list(parses, cfg["parses"], lambda x: str(x.get("url") or x.get("name") or ""))
        if isinstance(cfg.get("lives"), list):
            # absolutize common url fields
            fixed = []
            for live in cfg["lives"]:
                if not isinstance(live, dict):
                    continue
                live = dict(live)
                for field in ("url", "epg", "logo"):
                    if isinstance(live.get(field), str):
                        live[field] = abs_url(row["base"], live[field]) or live[field]
                fixed.append(live)
            merge_list(lives, fixed, lambda x: str(x.get("url") or x.get("name") or ""))
        if is_primary:
            if isinstance(cfg.get("rules"), list):
                rules = list(cfg["rules"])
            if isinstance(cfg.get("flags"), list):
                flags = list(cfg["flags"])
            if isinstance(cfg.get("ads"), list):
                ads = list(cfg["ads"])
            if isinstance(cfg.get("doh"), list):
                doh = list(cfg["doh"])

        meta_sources.append(
            {
                "id": sid,
                "name": sname,
                "group": src.get("group"),
                "url": src.get("url"),
                "primary": is_primary,
                "sites_added": added,
                "sites_skipped": skipped,
                "jar_status": src.get("jar_status"),
                "jar_md5_match": src.get("jar_md5_match"),
                "spider": spider_http(spider) or spider[:120],
            }
        )

    # 并入离线发现的 CMS 站点池（每个都实测过能返回影片列表）
    pool_sites = load_cms_pool()
    pool_added = 0
    for item in pool_sites:
        if is_netdisk_site(item):
            continue
        site = {field: item[field] for field in
                ("key", "name", "api", "searchable", "quickSearch", "filterable", "ext")
                if item.get(field) is not None}
        site["type"] = 1
        site["key"] = normalize_key(str(site.get("key") or site.get("name") or "cms"), "pool")
        videos = item.get("_videos") or 0
        score = 32 + int(min(videos / 30.0, 1.0) * 8)
        sites_scored.append((score, site))
        pool_added += 1
    if pool_added:
        print(f"  并入 CMS 站点池 {pool_added} 个", flush=True)

    # Deduplicate sites by api+type or key
    sites_scored.sort(key=lambda x: x[0], reverse=True)
    final_sites: list[dict] = []
    seen_api: set[str] = set()
    seen_key: set[str] = set()
    for score, site in sites_scored:
        key = str(site.get("key") or "")
        api = str(site.get("api") or "")
        stype = str(site.get("type"))
        api_sig = f"{stype}|{api}"
        if key in seen_key:
            continue
        if api and api_sig in seen_api:
            continue
        seen_key.add(key)
        if api:
            seen_api.add(api_sig)
        final_sites.append(site)
        if len(final_sites) >= MAX_SITES:
            break

    # Ensure douban / config helpers stay near top if present
    def pin_rank(site: dict) -> tuple:
        name = str(site.get("name") or "")
        key = str(site.get("key") or "")
        pin = 0
        for token in ("豆瓣", "Douban", "配置", "本地", "预告"):
            if token in name or token in key:
                pin = 1
                break
        return (0 if pin else 1, name)

    # Keep score order mostly; only stable pin known helpers to front among equals — simpler: move 豆瓣 to index 0
    pinned = []
    rest = []
    for s in final_sites:
        n = str(s.get("name") or "") + str(s.get("key") or "")
        if "豆瓣" in n or "Douban" in n:
            pinned.append(s)
        else:
            rest.append(s)
    final_sites = pinned + rest

    if not final_sites:
        write_degraded("no-valid-site-after-merge",
                       {"fetched": [row["src"].get("name") for row in fetched]})
        return 0 if OUT.is_file() else 1

    pcfg = primary["cfg"]
    official = {
        "spider": primary["spider"] or pcfg.get("spider") or "",
        "wallpaper": pcfg.get("wallpaper") or "",
        "logo": pcfg.get("logo") or "",
        "sites": final_sites,
        "parses": parses,
        "lives": lives,
        "homepage": "https://www.tvbox.org/",
        "warning": ("聚合自公开接口，自动筛选；已排除需要网盘会员的站点。"
                    "若部分站失效请换多仓或单线路。仅供学习交流。"),
    }
    if rules:
        official["rules"] = rules
    if flags:
        official["flags"] = flags
    if ads:
        official["ads"] = ads
    if doh:
        official["doh"] = doh
    # retain headers if primary has them
    if isinstance(pcfg.get("headers"), list):
        official["headers"] = pcfg["headers"]

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    primary_jar_status = primary["src"].get("jar_status")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(official, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    meta = {
        "generated_at": generated_at,
        "homepage": "https://www.tvbox.org/",
        "repo": "https://github.com/TVboxorg/TVbox",
        "primary": meta_sources[0]["name"] if meta_sources else "",
        "primary_jar_status": primary_jar_status,
        "sites": len(final_sites),
        "mode": "pure-cms" if only_cms else "mixed",
        "netdisk_filtered": netdisk_skipped,
        "cms_filtered": cms_skipped,
        "cms_dead": cms_dead,
        "pool_added": pool_added,
        "parses": len(parses),
        "lives": len(lives),
        "sources": meta_sources,
        "subscribe": "https://raw.githubusercontent.com/TVboxorg/TVbox/main/dist/official.json",
        "subscribe_cdn": "https://cdn.jsdelivr.net/gh/TVboxorg/TVbox@main/dist/official.json",
    }
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 本次聚合成功，清掉上一次的降级标记
    if DEGRADED.is_file():
        DEGRADED.unlink()

    if primary_jar_status == "fail":
        print(
            f"WARNING: primary source '{meta_sources[0]['name']}' spider jar 探测失败，"
            "聚合配置可能无法加载",
            file=sys.stderr,
        )
    if primary["src"].get("jar_md5_match") is False:
        print(
            f"WARNING: primary source '{meta_sources[0]['name']}' spider jar "
            "MD5 与声明不符",
            file=sys.stderr,
        )

    print(
        f"wrote {OUT} sites={len(final_sites)} parses={len(parses)} lives={len(lives)} "
        f"primary={meta['primary']} jar={primary_jar_status} "
        f"netdisk_filtered={netdisk_skipped} cms_dead={cms_dead}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
