#!/usr/bin/env python3
"""小鹅通课程归档 —— 统一命令行入口。

    run.py init      --url <课程链接> --cookie <cookie> --out <目录>
    run.py catalog   --out <目录>
    run.py download  --out <目录> [--videos 4] [--seg 24]
    run.py content   --out <目录>
    run.py index     --out <目录>
    run.py verify    --out <目录>
    run.py status    --out <目录>

配置写在 <out>/config.json，首次 init 时生成，之后所有子命令自动读取。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xet
from xet import Session, log, sanitize, valid_mp4

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_ASSETS = os.path.join(HERE, "..", "assets", "web")


def cfg_path(out):    return os.path.join(out, "config.json")
def lessons_path(out): return os.path.join(out, "_work", "lessons.json")


def load_cfg(out):
    p = cfg_path(out)
    if not os.path.exists(p):
        sys.exit(f"找不到 {p}\n先运行:  run.py init --url <课程链接> --cookie <cookie> --out {out}")
    return json.load(open(p))


def save_cfg(out, cfg):
    os.makedirs(os.path.join(out, "_work"), exist_ok=True)
    json.dump(cfg, open(cfg_path(out), "w"), ensure_ascii=False, indent=1)


def session(cfg): return Session(cfg["shop_host"], cfg["cookie"])


# --------------------------------------------------------------------------- #
def cmd_init(a):
    m = re.search(r"https?://([^/]+)/", a.url)
    if not m:
        sys.exit(f"无法从 URL 解析店铺域名: {a.url}")
    host = m.group(1)
    # 课程 ID 是 course_ + 约 22 位字母数字。
    # 注意别被路径里的 "course_pc_detail" 骗了 —— 必须取最后一个匹配且长度够长的。
    cands = [c for c in re.findall(r"course_[A-Za-z0-9]{16,}", a.url)]
    if not cands:
        sys.exit(f"URL 里找不到课程 ID（形如 course_xxxxxxxxxxxxxxxxxxxxxx）: {a.url}")
    cid = cands[-1]

    cfg = {"url": a.url, "shop_host": host, "course_id": cid, "cookie": a.cookie}
    save_cfg(a.out, cfg)
    print(f"✓ 已保存配置 -> {cfg_path(a.out)}")
    print(f"  店铺: {host}\n  课程: {cfg['course_id']}")

    s = session(cfg)
    try:
        d = s.post(xet.CATALOG_API, resource_id=cfg["course_id"], course_id=cfg["course_id"],
                   page=1, page_size=1)
        if d.get("code") == 0:
            print("  登录态: ✓ 有效")
        else:
            print(f"  登录态: ✗ {d.get('code')} {d.get('msg')}")
            sys.exit(1)
    except Exception as e:
        print(f"  登录态: ✗ {e}")
        sys.exit(1)


def cmd_catalog(a):
    cfg = load_cfg(a.out)
    log("抓取目录…")
    lessons = xet.fetch_catalog(session(cfg), cfg["course_id"])
    os.makedirs(os.path.dirname(lessons_path(a.out)), exist_ok=True)
    json.dump(lessons, open(lessons_path(a.out), "w"), ensure_ascii=False, indent=1)
    vids = [l for l in lessons if l["type"] == 3]
    hrs = sum(l["length_sec"] or 0 for l in vids) / 3600
    chs = len({l["chapter"] for l in lessons})
    log(f"✓ {len(lessons)} 个小节 / {len(vids)} 个视频 / {chs} 章 / 共 {hrs:.1f} 小时")
    log(f"  -> {lessons_path(a.out)}")


def _videos(cfg, lessons):
    vids = [l for l in lessons if l["type"] == 3]
    for i, l in enumerate(vids, 1):
        l["no"] = i
        l["filename"] = f"{i:03d}_{sanitize(l['chapter'])}_{sanitize(l['title'])}"
    return vids


def cmd_download(a):
    cfg = load_cfg(a.out)
    lessons = json.load(open(lessons_path(a.out)))
    vids = _videos(cfg, lessons)
    if a.start or a.end:
        vids = vids[a.start:(a.end or len(vids))]
    vdir = os.path.join(a.out, "video")
    os.makedirs(vdir, exist_ok=True)

    log(f"下载 {len(vids)} 个视频  (并发 {a.videos} 视频 x {a.seg} 线程)")
    s = session(cfg)
    stats = {"ok": 0, "skip": 0, "fail": 0}
    t0 = time.time()

    def work(l):
        r = xet.download_one(s, cfg["course_id"], l, vdir, a.seg, a.force)
        stats[r["status"]] = stats.get(r["status"], 0) + 1
        return r

    with ThreadPoolExecutor(max_workers=a.videos) as ex:
        list(ex.map(work, vids))

    el = (time.time() - t0) / 60
    log(f"完成: 成功 {stats['ok']}  跳过 {stats['skip']}  失败 {stats['fail']}   用时 {el:.1f} 分钟")
    if stats["fail"]:
        log("重新运行同样命令即可只补失败的（已完成的会被跳过）")


def cmd_content(a):
    cfg = load_cfg(a.out)
    lessons = json.load(open(lessons_path(a.out)))
    s = session(cfg)

    adir = os.path.join(a.out, "article")
    tdir = os.path.join(a.out, "text")
    cdir = os.path.join(a.out, "cover")
    for d in (adir, tdir, cdir):
        os.makedirs(d, exist_ok=True)

    # 图文正文
    n = 0
    for l in lessons:
        if l["type"] == 3:
            continue
        body = xet.get_detail(s, l["resource_id"], cfg["course_id"])
        if not body:
            log(f"  ! {l['title']} 正文为空")
            continue
        slug = sanitize(l["title"])
        open(os.path.join(adir, slug + ".html"), "w").write(body)
        open(os.path.join(adir, slug + ".md"), "w").write(
            f"# {l['title']}\n\n> resource_id: `{l['resource_id']}`\n\n"
            f"{xet.html_to_text(body)}\n")
        for j, src in enumerate(re.findall(r'<img[^>]+src="([^"]+)"', body), 1):
            try:
                d = s.get(src)
                if len(d) > 2000:
                    open(os.path.join(adir, f"{slug}_fig{j}.img"), "wb").write(d)
            except Exception:
                pass
        n += 1
        log(f"  ✓ 图文 {l['title']}")

    # 课程信息
    d = s.post("xe.course.business_go.avoidlogin.e_course.course_detail.get/1.0.0",
               resource_id=cfg["course_id"], course_id=cfg["course_id"], from_type=1)
    json.dump(d.get("data"), open(os.path.join(tdir, "course_detail.json"), "w"),
              ensure_ascii=False, indent=1)

    # 互动模块统计（很多课全是 0，查一下省得以为抓漏了）
    d = s.post("xe.course.business_go.interaction.get/2.0.0",
               resource_id=cfg["course_id"], product_id=cfg["course_id"], page=1, page_size=20)
    json.dump(d.get("data"), open(os.path.join(tdir, "interaction.json"), "w"),
              ensure_ascii=False, indent=1)

    # 封面
    vids = _videos(cfg, lessons)
    def cover(l):
        if not l.get("img"):
            return 0
        p = os.path.join(cdir, f"{l['no']:03d}.jpg")
        if os.path.exists(p) and os.path.getsize(p) > 2000:
            return 1
        try:
            d = s.get(l["img"])
            if len(d) > 2000:
                open(p, "wb").write(d)
                return 1
        except Exception:
            pass
        return 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        cnt = sum(ex.map(cover, vids))

    log(f"✓ 图文 {n} 篇 · 封面 {cnt}/{len(vids)} 张 · 课程信息与互动统计已存 text/")


def cmd_index(a):
    """生成 web/course.json 并部署前端资源。"""
    import shutil
    cfg = load_cfg(a.out)
    lessons = json.load(open(lessons_path(a.out)))
    vids = _videos(cfg, lessons)

    chapters, order = [], []
    for l in lessons:
        if l["chapter"] not in order:
            order.append(l["chapter"])
            chapters.append({"title": l["chapter"], "lessons": []})
        if l["type"] != 3:
            slug = sanitize(l["title"])
            chapters[-1]["lessons"].append({
                "no": None, "kind": "article", "title": l["title"],
                "file": f"{slug}.html",
                "available": os.path.exists(os.path.join(a.out, "article", slug + ".html")),
            })
            continue
        chapters[-1]["lessons"].append({
            "no": l["no"], "kind": "video", "id": l["resource_id"], "title": l["title"],
            "file": l["filename"] + ".mp4",
            "catalog_duration": l.get("length_sec"),
        })

    present = [l for c in chapters for l in c["lessons"]
               if l["kind"] == "video"
               and os.path.exists(os.path.join(a.out, "video", l["file"]))]

    def enrich(l):
        info = xet.probe(os.path.join(a.out, "video", l["file"]))
        l.update(info)
        l["cover"] = (f"{l['no']:03d}.jpg"
                      if os.path.exists(os.path.join(a.out, "cover", f"{l['no']:03d}.jpg")) else None)
        l["available"] = True
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(enrich, present))

    web = os.path.join(a.out, "web")
    os.makedirs(web, exist_ok=True)
    for f in ("index.html", "app.js", "style.css"):
        src = os.path.join(WEB_ASSETS, f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(web, f))

    st = cfg.get("stats", {})
    out = {
        "title": cfg.get("title") or cfg["course_id"],
        "course_id": cfg["course_id"],
        "chapters": chapters,
        "stats": {
            "chapters": len(chapters), "lessons": len(vids), "available": len(present),
            "downloaded_hours": round(sum(l["duration"] for l in present) / 3600, 2),
            "total_hours": round(sum(l.get("length_sec") or 0 for l in vids) / 3600, 2),
            "size_gb": round(sum(l["size"] for l in present) / 1e9, 2),
        },
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    json.dump(out, open(os.path.join(web, "course.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))
    s = out["stats"]
    log(f"✓ course.json: {s['available']}/{s['lessons']} 视频就位，"
        f"{s['downloaded_hours']}h / {s['total_hours']}h，{s['size_gb']} GB")
    log(f"  启动: cd {a.out} && python3 <skill>/scripts/serve.py")


def cmd_verify(a):
    cfg = load_cfg(a.out)
    lessons = json.load(open(lessons_path(a.out)))
    vids = _videos(cfg, lessons)
    bad, done = [], 0
    for l in vids:
        p = os.path.join(a.out, "video", l["filename"] + ".mp4")
        if valid_mp4(p):
            done += 1
        else:
            bad.append(l["filename"])
    log(f"完整性: {done}/{len(vids)} 通过")
    if bad:
        log(f"异常 {len(bad)} 个（重跑 download 会自动补上）:")
        for b in bad[:20]:
            log(f"   - {b}")
        return 1
    log("全部完好 ✓")
    return 0


def cmd_status(a):
    cfg = load_cfg(a.out)
    lessons = json.load(open(lessons_path(a.out)))
    vids = _videos(cfg, lessons)
    have = [l for l in vids
            if os.path.exists(os.path.join(a.out, "video", l["filename"] + ".mp4"))]
    sz = sum(os.path.getsize(os.path.join(a.out, "video", l["filename"] + ".mp4")) for l in have)
    print(f"已下载 : {len(have)} / {len(vids)}   {sz/1e9:.2f} GB")
    print(f"剩余   : {len(vids)-len(have)} 个")
    miss = [l for l in vids if l not in have][:20]
    for l in miss:
        print(f"   - {l['no']:03d} {l['chapter']} / {l['title']}")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(prog="run.py", description="小鹅通课程归档")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init");    p.add_argument("--url", required=True); p.add_argument("--cookie", required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("catalog"); p.add_argument("--out", required=True)
    p = sub.add_parser("download"); p.add_argument("--out", required=True)
    p.add_argument("--videos", type=int, default=4); p.add_argument("--seg", type=int, default=24)
    p.add_argument("--start", type=int, default=0); p.add_argument("--end", type=int, default=0)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("content"); p.add_argument("--out", required=True)
    p = sub.add_parser("index");   p.add_argument("--out", required=True)
    p = sub.add_parser("verify");  p.add_argument("--out", required=True)
    p = sub.add_parser("status");  p.add_argument("--out", required=True)

    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    {"init": cmd_init, "catalog": cmd_catalog, "download": cmd_download,
     "content": cmd_content, "index": cmd_index, "verify": cmd_verify,
     "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
