# 小鹅通接口与故障排查笔记

写给以后遇到同类问题时快速定位用。按"现象 → 原因"的顺序组织。

## 目录

- [认证与登录态](#认证与登录态)
- [目录接口的两个静默失败](#目录接口的两个静默失败)
- [video_urls 混淆分析（结论：别逆向）](#video_urls-混淆分析结论别逆向)
- [mutli_line：明文播放地址](#mutli_line明文播放地址)
- [HLS 切片与 AES-128](#hls-切片与-aes-128)
- [图文正文](#图文正文)
- [常见"空"内容](#常见空内容)
- [故障速查表](#故障速查表)

---

## 认证与登录态

必需的 cookie：

| 名称 | 作用 |
|------|------|
| `XIAOEID` | 主标识 |
| `pc_user_key` | 用户密钥 |
| `anonymous_user_key` | 匿名设备标识 |
| `cookie_session_id` | 会话 |

全部请求需要 `app_id`（= 域名第一段）、`Referer`、`Origin` 三件套，缺了会 404 或参数错误。

**症状：接口返回 `code: 8 缺失参数`**
多半是缺 `app_id`。注意 `sub.course.list` 这类接口还要求额外参数（如 `p_id`），不是所有接口的参数集都一样。

**症状：cookie 过期**
表现为接口返回空 data 或跳登录。重新登录取一次即可，已下载文件不受影响。实测 22 小时后仍有效，但别指望过夜跨天。

---

## 目录接口的两个静默失败

`xe.course.business_go.avoidlogin.e_course.resource_catalog_list.get/1.0.0`

这是最容易浪费时间的接口，因为它**传错参数不报错**。

### 坑 1：`p_id` 传错

顶层章节列表里，每条记录有两个容易混淆的字段：

```json
{
  "p_id": "0",                                  // ← 顶层章节这里是字符串 "0"
  "chapter_id": "chap_2htqrCt68nGPCu2BGZ2qtaD5SRf",   // ← 这个才是章节 ID
  "resource_id": "chap_2htqrCt68nGPCu2BGZ2qtaD5SRf",
  "sub_course_id": "subcourse_2hrsJ2rSc3xoRKWwVHClXrECQr9"
}
```

传 `p_id="0"` 或传章节标题，会**返回全部章节而不是本章小节**。HTTP 200、`code: 0`、数据"看起来正常"——实际上每个章节都会拿到同样的 25 条。

### 坑 2：漏传 `sub_course_id`

训练营/合辑类课程（`camp_pro`）必须传 `sub_course_id`，否则同样返回全部章节。

### 怎么确认没踩坑

抓回来的小节总数，应该和课程页面上显示的"小节数"一致。

```
页面显示：章节数：23  小节数：291
抓到：    25 章 / 291 小节   ← 一致，没错
```

如果每个章节的小节数都一样（25、25、25…），基本可以确定踩坑了。

---

## video_urls 混淆分析（结论：别逆向）

`xe.course.business.video.detail_info.get/2.0.0` 返回：

```json
"video_urls": "W$siZGVmaW5pdGlvbl9uYW@lIjoiXHU5YWQ%XHU#ZTA@IiwiZGVm..."
```

分析过程（供参考，别重走）：

- 整体是 base64，但用标准字母表 base64 解出来是**乱码夹杂少量正确 ASCII**
- 约 8% 的字符被替换成 `#` `$` `%` `@` `_` 五个符号之一
- 这五个符号 ASCII 值连续（35/36/37）和离散（64/95）各一组，像是查表替换而非简单偏移
- 解码后能稳定看到 `7025237`、`e545fd5e46a39e` 这类正确片段，说明**部分分组未被破坏**
- 位置分布不规律（间隔 21、13、4、4、56…），不是简单插入

结论：逆向这个字段投入产出比很低。**用 `mutli_line` 直接拿明文**。

---

## mutli_line：明文播放地址

```
POST xe.course.business.video.mutli_line/1.0.0
resource_id=<小节ID>&product_id=<课程ID>&opr_sys=Linux%20x86_64&line=1
```

返回三条 CDN 线路：

```json
{"data": {"cloud_data": {
  "hw": {"encrypt_url": "https://htv-tos.xet.tech/.../v.f421220.m3u8?sign=...&t=...&us=...", ...},
  "tx": {"encrypt_url": "https://ttv-tos.xet.tech/..."},
  "zj": {"encrypt_url": "https://v-tos-k.xiaoeknow.com/..."}
}}}
```

注意 `\u0026` 是 JSON 里的转义 `&`，拼 URL 前要还原。

**线路会各自解析到不同的边缘节点**（比如 zj 的分片可能落在 `btt-vod.xiaoeknow.com`）。某台节点会偶发 SSL 握手失败，**重试时轮换线路**比在同一条线路上死磕有效得多。

实测：`zj` → `hw` → `tx` 轮换后，之前连续失败的视频立刻成功。

---

## HLS 切片与 AES-128

m3u8 结构：

```
#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="https://app.xiaoe-tech.com/.../kds/api/v1/keys?ak=...",IV=0x000...0
#EXTINF:2.000,
v.f421220_0.ts?type=mpegts&start=0&end=362095&sign=...&t=...&us=...&whref=...
```

要点：

- **切片是同一个 TS 文件的字节区间**，不是独立文件。`start`/`end` 是闭区间
- **每段独立加密、独立 PKCS#7 填充**。所以必须**逐段**解密再拼接，不能把整个响应体当一个 CBC 流解密
- IV 是全 0（从 `IV=0x00...` 读；不写就用全 0）
- 密钥接口直接返回 16 字节二进制，无需登录
- 2 秒一段，几分钟的小节几十段，一小时的课两千多段
- `sign`/`t`/`us` 是短时效签名，**每次下载前重新取 m3u8**，不要缓存

URL 里的 `*` 是字面星号（`whref=*.xiaoe-tech.com`），不要 URL-encode。

### 解密

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
plain = d.update(data) + d.finalize()
plain = plain[:-plain[-1]]        # 去 PKCS#7 填充
```

依赖 `cryptography` 包。没有的话 `pip install cryptography`，或退回用 ffmpeg 直接拉 m3u8（它能自己解密，但没法并发、没法精细控制重试）。

### 转封装

```bash
ffmpeg -i out.ts -c copy -bsf:a aac_adtstoasc out.mp4
```

`-c copy` 不重编码。`aac_adtstoasc` 把 AAC 从 ADTS 转成 MP4 需要的 ASC，否则部分播放器会没有声音。

---

## 图文正文

正文在 `xe.course.business.get.detail/2.0.0` 的 **`data.org_content`** 字段，是完整的富文本 HTML。

**参数**：传**小节自己的 resource_id**。传课程 ID 会返回空 `org_content`——看起来像"接口没数据"，其实是参数错了。

**正文不在页面 HTML 里**。小鹅通 PC 站是纯 Vue SPA，`curl` 拿到的 HTML 壳子（30 KB 左右）不含任何正文。正文是 XHR 拿到后渲染的。

顺带说明：`core.info.get` 只返回元信息（标题、封面、观看数），**没有正文**，别浪费时间。

---

## 常见"空"内容

这些返回空**不代表抓取失败**，是课程本身没有。查了再下结论：

| 接口 | 空的表现 | 含义 |
|------|----------|------|
| `api/xe.goods.comments.get` | `comments: [], restrict: 1` | 课程评论被关闭/为空 |
| `xe.course.business.video.ai.captions.get` | `code:1, msg:"暂未开启字幕"` | 讲师没开字幕 |
| `xe.course.business_go.interaction.get` | 每项 `count: 0` | 没配置练习/考试/表单 |
| `course_detail.get` | `course_details` 为空串 | 讲师没填富文本简介，简介就是标题 |

注意评论接口的正确路径是 `/api/xe.goods.comments.get/1.0.0`。直接 POST 到 `/api/xe.goods.comments.get`（不带版本号）会返回纯文本 `Hello Xiaoe~`，不是 JSON。

---

## 故障速查表

| 现象 | 原因 | 处理 |
|------|------|------|
| 进度条拖不动 | 用了 `python3 -m http.server`，不支持 Range | 换 `serve.py`（见下） |
| 每个章节小节数都一样 | `p_id` 传了 `"0"` 或漏传 `sub_course_id` | 用 `chapter_id` + `sub_course_id` |
| m3u8 拉到了但切片全 403 | 签名过期 | 重新取 m3u8，别缓存 |
| 切片下载频繁 SSL 错误 | 该 CDN 边缘节点故障 | 重试时轮换线路 |
| 解密后 ffmpeg 报损坏 | 切片未按块对齐（长度非 16 倍数） | 检查是否有切片下载不完整 |
| 视频没声音 | 缺 `aac_adtstoasc` | 转封装时加上 |
| 续传跳过了残缺文件 | 只用文件大小判断完成 | 改用 `ffprobe` 探测时长 |
| 长视频吃满内存 | 切片全部缓存后才拼接 | 按序落盘（前序齐了再写） |

### Range 支持

Python 内置 `http.server` 的 `SimpleHTTPRequestHandler` **完全忽略 `Range` 请求头**：

```bash
curl -r 0-1000 http://host/video.mp4 -D -
# HTTP/1.0 200 OK
# Content-Length: 14170501        ← 整个文件，且没有 Accept-Ranges
```

正常应该返回：

```
HTTP/1.1 206 Partial Content
Content-Range: bytes 1000-1999/14170501
Accept-Ranges: bytes
```

所以本地播放器必须用自己实现了 RFC 7233 的服务器，脚本见 `scripts/serve.py`。

---

## 脚本使用注意

`pkill -f "http.server"` 会**匹配到执行这条命令的 shell 自身**（因为命令行字符串里就含这个模式），把自己杀掉。按端口找 PID 更安全：

```bash
OLD=$(ss -lptn 'sport = :8765' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$OLD" ] && kill "$OLD"
```
