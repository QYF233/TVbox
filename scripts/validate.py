"""TVBox 配置校验核心。

判定规则全部来自 TVBoxOSC 源码 ApiConfig.parseJson / loadJar：
  - 顶层必须是 JSON object
  - sites 取自 json.video.sites 或 json.sites，必须是数组
  - 每个 site 必须含 key / type / api，type 必须是数字（缺失会 NPE）
  - sites 为空数组合法，但无站点可用
  - urls 键存在表示多仓（Depot），不需要 sites
  - spider 非空时 jar 必须可下载且为合法 zip

只依赖标准库，可直接在 GitHub Actions 跑。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Any

TIMEOUT = 15
HEAD_BYTES = 8 * 1024 * 1024
UA_APP = "okhttp/3.15"
UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8"
)


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def normalize_url(url: str) -> str:
    """中文域名转 punycode，路径/查询串做 percent-encode。"""
    try:
        parts = urllib.parse.urlsplit(url.strip())
        host = parts.hostname or ""
        try:
            host_ascii = host.encode("idna").decode("ascii")
        except Exception:
            host_ascii = host
        port = f":{parts.port}" if parts.port else ""
        path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
        query = urllib.parse.quote(parts.query, safe="=&%:@!$'()*+,;/?-._~")
        return urllib.parse.urlunsplit(
            (parts.scheme, host_ascii + port, path, query, "")
        )
    except Exception:
        return url


def http_get(url: str, *, ua: str = UA_APP, timeout: int = TIMEOUT,
             limit: int = HEAD_BYTES) -> tuple[bool, int, bytes, str]:
    """直连 GET（不走系统代理）。返回 (ok, status, body, error)。"""
    headers = {
        "User-Agent": ua,
        "Accept": ACCEPT,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
    }
    try:
        req = urllib.request.Request(normalize_url(url), headers=headers)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl_context()),
        )
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read(limit)
            return True, getattr(resp, "status", 200) or 200, raw, ""
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(limit)
        except Exception:
            body = b""
        return False, exc.code, body, f"HTTP {exc.code}"
    except Exception as exc:
        return False, 0, b"", f"{type(exc).__name__}: {exc}"[:120]


def strip_json_noise(text: str) -> str:
    """去掉 // 与 /* */ 注释（字符串内的不算），容忍尾逗号。"""
    out: list[str] = []
    i, n = 0, len(text)
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
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def parse_config(body: bytes) -> tuple[dict[str, Any] | None, str]:
    """把响应体解析成配置 dict。返回 (obj, error)。"""
    text = None
    for enc in ("utf-8", "gbk", "utf-8-sig"):
        try:
            text = body.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None, "decode-fail"
    text = text.lstrip("\ufeff").strip()
    if not text:
        return None, "empty"

    candidates = [text]
    cleaned = strip_json_noise(text)
    if cleaned != text:
        candidates.append(cleaned)
    # JSON 前面可能挂了说明文字，从第一个 { 起再试一次
    idx = cleaned.find("{")
    if idx > 0:
        candidates.append(cleaned[idx:])

    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data, ""
    head = text[:40].replace("\n", " ")
    if head.startswith("<"):
        return None, "html"
    return None, "not-json"


def validate_sites(obj: dict[str, Any]) -> dict[str, Any]:
    """按源码规则校验 sites，返回统计信息。"""
    sites = None
    video = obj.get("video")
    if isinstance(video, dict) and isinstance(video.get("sites"), list):
        sites = video["sites"]
    if sites is None and isinstance(obj.get("sites"), list):
        sites = obj["sites"]

    if sites is None:
        return {"total": 0, "valid": 0, "bad": 0, "reason": "no-sites-key",
                "types": {}, "valid_sites": []}

    valid: list[dict[str, Any]] = []
    bad = 0
    for site in sites:
        if not isinstance(site, dict):
            bad += 1
            continue
        if "key" not in site or "type" not in site or "api" not in site:
            bad += 1
            continue
        if not isinstance(site.get("type"), (int, float)):
            bad += 1
            continue
        valid.append(site)

    types: dict[str, int] = {}
    for site in valid:
        key = str(site.get("type"))
        types[key] = types.get(key, 0) + 1

    reason = ""
    if not valid:
        reason = "no-valid-site" if sites else "sites-empty"
    return {"total": len(sites), "valid": len(valid), "bad": bad,
            "reason": reason, "types": types, "valid_sites": valid}


def split_spider(spider: str) -> tuple[str, str, bool]:
    """拆出 jar 地址、声明 md5、是否 img+ 伪装。"""
    spider = (spider or "").strip()
    md5 = ""
    if ";md5;" in spider:
        spider, md5 = spider.split(";md5;", 1)
        md5 = md5.strip()
    img = spider.startswith("img+")
    if img:
        spider = spider[4:]
    return spider.strip(), md5, img


def validate_jar(spider: str, *, timeout: int = TIMEOUT) -> dict[str, Any]:
    """校验 spider jar：可下载 + 合法 zip + MD5 匹配。"""
    result = {"status": "none", "url": "", "note": "", "md5_match": None,
              "size": 0}
    if not spider or not spider.strip():
        return result

    url, declared_md5, img_plus = split_spider(spider)
    result["url"] = url
    if not url:
        return result
    if url.startswith(("assets://", "clan://", "file://")):
        result["status"] = "local"
        result["note"] = "local-path"
        return result

    ok, status_code, body, err = http_get(url, timeout=timeout)
    if not ok or not body:
        result["status"] = "fail"
        result["note"] = f"download {status_code} {err}"[:90]
        return result

    result["size"] = len(body)
    payload = body

    if img_plus:
        marker = re.search(rb"[A-Za-z0]{8}\*\*", body)
        if not marker:
            result["status"] = "fail"
            result["note"] = "img+ marker missing"
            return result
        try:
            payload = base64.b64decode(body[body.index(marker.group()) + 10:],
                                       validate=False)
        except Exception:
            result["status"] = "fail"
            result["note"] = "img+ base64 decode fail"
            return result

    if declared_md5:
        actual = hashlib.md5(body).hexdigest()
        result["md5_match"] = actual.lower() == declared_md5.lower()
        if not result["md5_match"]:
            result["status"] = "fail"
            result["note"] = f"md5 mismatch {actual[:8]}!={declared_md5[:8]}"
            return result

    if payload[:2] != b"PK":
        result["status"] = "fail"
        result["note"] = f"not zip head={payload[:6]!r}"
        return result

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
        names = archive.namelist()
    except Exception as exc:
        result["status"] = "fail"
        result["note"] = f"zip broken {exc}"[:70]
        return result

    has_dex = any(name.endswith(".dex") for name in names)
    result["status"] = "ok"
    result["note"] = f"{len(names)} files{',dex' if has_dex else ''}"
    return result


def detect_live(body: bytes) -> bool:
    """判断是否是直播源（m3u / txt 频道表）。"""
    head = body[:4000]
    if b"#EXTM3U" in head or b"#EXTINF" in head:
        return True
    text = head.decode("utf-8", "ignore")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 3:
        hits = sum(1 for ln in lines if "," in ln and "http" in ln)
        if hits >= 2:
            return True
    return False


def analyze(url: str, *, primary_ua: str = UA_APP,
            fallback_ua: str = UA_BROWSER,
            timeout: int = TIMEOUT) -> dict[str, Any]:
    """完整分析一个接口地址。"""
    outcome: dict[str, Any] = {
        "ok": False, "status": 0, "ms": 0, "kind": "error", "error": "",
        "ua_used": "", "sites_total": 0, "sites_valid": 0, "sites_bad": 0,
        "types": {}, "jar_status": "none", "jar_url": "", "jar_note": "",
        "jar_md5_match": None, "jar_size": 0, "multi_count": 0, "is_live": False,
    }

    attempts = [primary_ua]
    if fallback_ua and fallback_ua != primary_ua:
        attempts.append(fallback_ua)

    last_error = ""
    for attempt_index, ua in enumerate(attempts):
        started = time_ms()
        ok, status_code, body, err = http_get(url, ua=ua, timeout=timeout)
        outcome["ms"] = time_ms() - started
        outcome["status"] = status_code
        outcome["ua_used"] = ua.split("/")[0]

        if not ok or not body:
            last_error = err or "empty body"
            if attempt_index + 1 < len(attempts):
                continue
            outcome["error"] = last_error
            return outcome

        obj, parse_error = parse_config(body)
        if obj is None:
            if detect_live(body):
                outcome.update({"ok": True, "kind": "live", "is_live": True})
                return outcome
            last_error = parse_error
            if attempt_index + 1 < len(attempts):
                continue
            outcome["error"] = parse_error
            outcome["kind"] = "html" if parse_error == "html" else "other"
            return outcome

        # 多仓
        urls = obj.get("urls")
        if isinstance(urls, list):
            outcome["multi_count"] = len(urls)

        stats = validate_sites(obj)
        outcome["sites_total"] = stats["total"]
        outcome["sites_valid"] = stats["valid"]
        outcome["sites_bad"] = stats["bad"]
        outcome["types"] = stats["types"]

        spider = obj.get("spider")
        spider = spider.strip() if isinstance(spider, str) else ""
        jar = validate_jar(spider, timeout=timeout) if spider else {
            "status": "none", "url": "", "note": "", "md5_match": None, "size": 0
        }
        outcome["jar_status"] = jar["status"]
        outcome["jar_url"] = jar["url"]
        outcome["jar_note"] = jar["note"]
        outcome["jar_md5_match"] = jar["md5_match"]
        outcome["jar_size"] = jar["size"]

        if stats["valid"] > 0:
            outcome["ok"] = True
            outcome["kind"] = "multi" if outcome["multi_count"] else "config"
            return outcome

        if outcome["multi_count"]:
            # 多仓配置本来就没有 sites，视为可用
            outcome["ok"] = True
            outcome["kind"] = "multi"
            return outcome

        last_error = stats["reason"] or "no-valid-site"
        if attempt_index + 1 < len(attempts):
            continue
        outcome["error"] = last_error
        outcome["kind"] = "config-empty"
        return outcome

    outcome["error"] = last_error
    return outcome


def time_ms() -> int:
    import time as _time
    return int(_time.time() * 1000)
