#!/usr/bin/env python3
"""支持 HTTP Range 的静态服务器。

Python 内置的 http.server 会忽略 Range 请求头（永远返回 200 + 整个文件），
浏览器因此无法拖动进度条定位。这里实现标准 RFC 7233 单区间解析，返回 206。

相比内置版本还多了：HTTP/1.1 keep-alive、多线程、HEAD 支持。
"""
import argparse, os, posixpath, re, socket, sys, threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class RangeHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # keep-alive，比内置的 1.0 快很多
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".mp4": "video/mp4", ".m4v": "video/mp4", ".mkv": "video/x-matroska",
                      ".js": "text/javascript", ".m4a": "audio/mp4"}

    def send_head(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()

        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        size = os.fstat(f.fileno()).st_size
        ctype = self.guess_type(path)

        m = RANGE_RE.match(rng.strip())
        if not m:
            f.close()
            self.send_response(416, "Requested Range Not Satisfiable")
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        start_s, end_s = m.group(1), m.group(2)
        if start_s == "":                       # bytes=-N  → 末尾 N 字节
            if end_s == "":
                f.close()
                self.send_error(400, "Bad Range")
                return None
            n = int(end_s)
            start, end = max(0, size - n), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)

        if start > end or start >= size:        # 越界
            f.close()
            self.send_response(416, "Requested Range Not Satisfiable")
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        f.seek(start)
        self.send_response(206, "Partial Content")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", self.date_time_string(os.fstat(f.fileno()).st_mtime))
        self.end_headers()
        return _Bounded(f, end - start + 1)

    def end_headers(self):
        # 所有响应统一声明支持字节区间，浏览器据此决定能否拖动进度条
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def log_message(self, fmt, *a):
        msg = fmt % a
        # 只把 4xx/5xx 打到 stderr，避免刷屏
        code = msg.split()[1] if len(msg.split()) > 1 else ""
        if code.startswith(("4", "5")):
            sys.stderr.write("%s %s\n" % (self.address_string(), msg))


class _Bounded:
    """把文件对象包装成只读前 n 字节的流。"""
    def __init__(self, f, n):
        self.f, self.remain = f, n

    def read(self, size=-1):
        if self.remain <= 0:
            return b""
        if size is None or size < 0 or size > self.remain:
            size = self.remain
        data = self.f.read(size)
        self.remain -= len(data)
        return data

    def close(self):
        self.f.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int, nargs="?", default=8765)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--dir", default=os.getcwd(), help="课程库根目录（默认当前目录）")
    a = ap.parse_args()

    os.chdir(os.path.abspath(a.dir))
    handler = lambda *x, **kw: RangeHandler(*x, directory=os.getcwd(), **kw)
    httpd = ThreadingHTTPServer((a.bind, a.port), handler)
    httpd.daemon_threads = True
    print(f"课程库: http://{a.bind}:{a.port}/web/")
    print(f"根目录: {os.getcwd()}")
    print("已启用 Range 支持（可拖动进度条）  ·  Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
