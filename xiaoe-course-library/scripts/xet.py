"""小鹅通(xiaoe-tech)课程库核心库。

被 run.py 调用，也可单独 import 使用。
所有配置通过 env 或参数传入，不硬编码任何店铺/课程 ID。
"""
from __future__ import annotations

import html as ihtml
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/154.0.0.0 Safari/537.36")

# 三条 CDN 线路，重试时轮换（单台边缘节点会偶发握手失败）
LINES = ["zj", "hw", "tx"]

_lock = threading.Lock()


def log(msg):
    with _lock:
        print(msg, flush=True)


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
class Session:
    """封装小鹅通 API 的 POST 调用，带重试。"""

    def __init__(self, shop_host: str, cookie: str):
        # shop_host 形如 appezrn4igg1968.pc.xiaoe-tech.com
        self.base = f"https://{shop_host}"
        self.app_id = shop_host.split(".")[0]
        self.shop_host = shop_host
        self.s = requests.Session()
        self.s.headers.update({
            "Cookie": cookie,
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.base}/",
            "Origin": self.base,
        })

    def post(self, path: str, *, retries: int = 4, timeout: int = 45, **params):
        url = f"{self.base}/{path}"
        params.setdefault("app_id", self.app_id)
        last = None
        for i in range(retries):
            try:
                r = self.s.post(url, data=params, timeout=timeout,
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
                return r.json()
            except Exception as e:
                last = e
                time.sleep(1.5 * (i + 1))
        raise RuntimeError(f"{path} 失败: {type(last).__name__}: {last}")

    def get(self, url: str, *, retries: int = 4, timeout: int = 45, referer=None):
        h = {"User-Agent": UA, "Referer": referer or f"{self.base}/"}
        last = None
        for i in range(retries):
            try:
                r = requests.get(url, headers=h, timeout=timeout)
                if r.status_code == 200:
                    return r.content
                last = f"HTTP {r.status_code}"
            except Exception as e:
                last = f"{type(e).__name__}"
            time.sleep(1.0 * (i + 1))
        raise RuntimeError(f"GET 失败 ({last}): {url[:110]}")


# --------------------------------------------------------------------------- #
# 目录
# --------------------------------------------------------------------------- #
CATALOG_API = "xe.course.business_go.avoidlogin.e_course.resource_catalog_list.get/1.0.0"


def fetch_catalog(sess: Session, course_id: str):
    """抓取完整目录 -> lessons.json

    两个必须同时传对的参数（踩过三次坑）：
      * p_id 要用 chapter_id，而不是列表里的 p_id（顶层章节的 p_id 是字符串 "0"，
        传错会静默返回全部章节，看起来"成功"了其实是错的）
      * sub_course_id 必须传，否则同样返回全部章节而不是本章小节
    """
    root = sess.post(CATALOG_API, resource_id=course_id, course_id=course_id,
                     order="asc", page=1, page_size=100)["data"]["list"]

    lessons = []
    for ch in root:
        # 顶层记录的 chapter_id / resource_id 才是章节 ID；p_id 此时是 "0"
        cid = ch.get("chapter_id") or ch.get("resource_id")
        sub = ch.get("sub_course_id")
        if ch.get("chapter_type") != 1:
            lessons.append(_row(ch, ch))
            continue
        page = 1
        while True:
            d = sess.post(CATALOG_API, resource_id=course_id, course_id=course_id,
                          p_id=cid, sub_course_id=sub, is_display_auth_sections=0,
                          order="asc", page=page, page_size=50)
            lst = (d.get("data") or {}).get("list") or []
            for it in lst:
                lessons.append(_row(it, ch))
            if len(lst) < 50 or page > 40:
                break
            page += 1
    return lessons


def _row(it, ch):
    return {
        "chapter": ch.get("chapter_title") or ch.get("resource_title"),
        "title": it.get("resource_title"),
        "resource_id": it.get("resource_id"),
        "type": it.get("resource_type"),      # 3=视频 1=图文
        "length_sec": it.get("video_length"),
        "img": it.get("img_url"),
    }


# --------------------------------------------------------------------------- #
# 播放地址
# --------------------------------------------------------------------------- #
MUTLI_API = "xe.course.business.video.mutli_line/1.0.0"


def get_m3u8_url(sess: Session, course_id: str, resource_id: str, prefer: int = 0):
    """拿明文 m3u8。

    关键：`xe.course.business.video.detail_info.get` 返回的 video_urls 字段是
    混淆过的 base64（~8% 字符被替换成 #$%@_ 这类符号），逆向成本很高。
    但 mutli_line 直接给出三条 CDN 线路的明文 encrypt_url，完全不需要解密。
    """
    order = LINES[prefer % len(LINES):] + LINES[:prefer % len(LINES)]
    d = sess.post(MUTLI_API, resource_id=resource_id, product_id=course_id,
                  opr_sys="Linux x86_64", line=1)
    cd = ((d.get("data") or {}).get("cloud_data") or {})
    for ln in order:
        u = (cd.get(ln) or {}).get("encrypt_url")
        if u:
            return u.replace("\\u0026", "&"), ln
    raise RuntimeError(f"没有可用线路，返回了 {list(cd)}")


KEY_RE = re.compile(r'URI="([^"]+)"')
IV_RE = re.compile(r"IV=0x([0-9a-fA-F]+)")


def parse_m3u8(text: str, base_url: str):
    """返回 (key_uri, iv, [segment_url, ...])"""
    key_uri, iv, segs = None, b"\x00" * 16, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-KEY"):
            m = KEY_RE.search(line)
            if m:
                key_uri = m.group(1)
            m = IV_RE.search(line)
            if m:
                iv = bytes.fromhex(m.group(1).zfill(32))
        elif line.startswith("#"):
            continue
        else:
            segs.append(urljoin(base_url, line))
    return key_uri, iv, segs


# --------------------------------------------------------------------------- #
# 下载
# --------------------------------------------------------------------------- #
def _unpad(b: bytes) -> bytes:
    n = b[-1] if b else 0
    return b[:-n] if 0 < n <= 16 and len(b) % 16 == 0 else b


def download_one(sess: Session, course_id: str, ls: dict, out_dir: str,
                 seg_threads: int = 24, force: bool = False) -> dict:
    """下载单个视频：并发拉切片 -> AES-128-CBC 逐段解密 -> 顺序写 .ts -> ffmpeg 转封装 MP4

    用 ffmpeg -c copy 转封装而非重编码，画质无损且快得多。
    """
    name = ls["filename"]
    out_mp4 = os.path.join(out_dir, name + ".mp4")
    tmp_ts = os.path.join(out_dir, "_tmp", name + ".ts")
    os.makedirs(os.path.dirname(tmp_ts), exist_ok=True)

    if not force and valid_mp4(out_mp4):
        return {"status": "skip", "name": name}

    t0 = time.time()
    for attempt in range(1, 4):
        try:
            m3u8, line = get_m3u8_url(sess, course_id, ls["resource_id"], prefer=attempt - 1)
            manifest = sess.get(m3u8, timeout=60).decode("utf-8", "replace")
            key_uri, iv, segs = parse_m3u8(manifest, m3u8)
            if not segs:
                raise RuntimeError("m3u8 里没有切片")
            key = sess.get(key_uri) if key_uri else b"\x00" * 16
            if len(key) != 16:
                raise RuntimeError(f"密钥长度异常 {len(key)}")

            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

            buf, lock = {}, threading.Lock()
            state = {"nxt": 0}

            with open(tmp_ts, "wb") as fh:
                def run_one(i):
                    data = sess.get(segs[i], timeout=60)
                    if len(data) % 16:
                        raise RuntimeError(f"切片 {i} 未按块对齐 ({len(data)} 字节)")
                    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
                    plain = _unpad(d.update(data) + d.finalize())
                    # 按序落盘：完成的先缓存，等前序齐了再写，
                    # 避免把整个视频读进内存（长视频能有几百 MB）
                    with lock:
                        buf[i] = plain
                        while state["nxt"] in buf:
                            fh.write(buf.pop(state["nxt"]))
                            state["nxt"] += 1

                with ThreadPoolExecutor(max_workers=seg_threads) as ex:
                    for f in as_completed([ex.submit(run_one, i) for i in range(len(segs))]):
                        f.result()
                if state["nxt"] != len(segs):
                    raise RuntimeError(f"只完成 {state['nxt']}/{len(segs)} 个切片")

            pr = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_ts,
                 "-c", "copy", "-bsf:a", "aac_adtstoasc", out_mp4],
                capture_output=True, text=True, timeout=3600)
            if pr.returncode != 0:
                raise RuntimeError(f"ffmpeg: {pr.stderr[-300:]}")
            os.remove(tmp_ts)
            sz = os.path.getsize(out_mp4)
            log(f"  ✓ {name}  {sz/1e6:.1f}MB  {time.time()-t0:.0f}s  line={line}")
            return {"status": "ok", "name": name, "size": sz}

        except Exception as e:
            log(f"  ↻ 重试{attempt} {name}: {type(e).__name__}: {e}")
            time.sleep(3 * attempt)
            if os.path.exists(tmp_ts):
                os.remove(tmp_ts)

    return {"status": "fail", "name": name}


def valid_mp4(path: str) -> bool:
    """用 ffprobe 判断是否真的完整。

    只看文件大小是不够的：封装到一半被中断的 MP4 往往也有几百 KB，
    续传时会被误判成"已完成"而永久跳过。
    """
    if not os.path.exists(path) or os.path.getsize(path) < 100_000:
        return False
    try:
        pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
        return float((pr.stdout or "").strip()) > 1.0
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# 非视频内容
# --------------------------------------------------------------------------- #
def get_detail(sess: Session, resource_id: str, course_id: str = "") -> str:
    """图文正文在这里：data.org_content。

    两个容易踩的点：
      * 传的是**小节自己的 resource_id**，传课程 ID 会拿到空正文，
        看起来像"接口没数据"其实参数错了
      * 页面是纯 SPA，正文不在 HTML 里，curl 抓页面是抓不到的
    """
    params = {"resource_id": resource_id}
    if course_id:
        params["product_id"] = course_id
    d = sess.post("xe.course.business.get.detail/2.0.0", **params)
    return (d.get("data") or {}).get("org_content") or ""


def html_to_text(h: str) -> str:
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>", "\n", h, flags=re.I)
    h = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", "", h)
    h = ihtml.unescape(h)
    h = re.sub(r"[ \t\xa0]+", " ", h)
    return re.sub(r"\n{3,}", "\n\n", h).strip()


def sanitize(name: str, limit: int = 80) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', "_", str(name)).strip().strip(".")
    return name[:limit] or "untitled"


def probe(path: str) -> dict:
    try:
        pr = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration,size",
             "-of", "json", path], capture_output=True, text=True, timeout=60)
        d = json.loads(pr.stdout or "{}")
        f = d.get("format") or {}
        v = (d.get("streams") or [{}])[0]
        return {"duration": round(float(f.get("duration", 0) or 0), 2),
                "size": int(f.get("size", 0) or os.path.getsize(path)),
                "resolution": f"{v['width']}x{v['height']}" if v.get("width") else None}
    except Exception:
        return {"duration": 0, "size": os.path.getsize(path), "resolution": None}
