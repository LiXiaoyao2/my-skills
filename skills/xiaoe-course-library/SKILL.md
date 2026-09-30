---
name: xiaoe-course-library
description: 把小鹅通（xiaoe-tech / xe.xiaoe-tech.com）付费课程完整归档到本地，下载全部视频并搭一个带章节树、断点续播、进度与笔记的本地学习网页库。凡是用户给出小鹅通课程链接（fe.duyiedu.com、*.pc.xiaoe-tech.com、shop.115.com 等店铺域名下的 course_xxx 链接）、或提到"把这门课下载下来/保存到本地/做个课程库/整理一下小鹅通课程/课程归档/抓课程视频"，都应该使用这个技能。即使用户只是贴一个课程链接说"帮我抓一下"，也要主动使用。视频虽然带 is_drm 标记，实际只是 HLS + AES-128 加密而非硬件 DRM，可以完整下载。
---

# 小鹅通课程归档与本地学习库

把一门小鹅通课程变成一个**能长期使用的本地学习库**：全部视频下载成标准 MP4，加上章节树、断点续播、进度追踪和笔记的网页界面。

## 这个技能为什么值得存在

小鹅通的视频标记着 `is_drm: 1`，前端拿到的播放地址是混淆过的 base64，看起来像是 DRM 拿不到。**实际上它只是 HLS + AES-128**，密钥就明文写在 m3u8 里。搞清楚这一点，剩下的都是工程问题。

更省事的是根本不用碰那串混淆数据——有一个接口直接给明文地址（见下方"关键接口"）。

## 工作流程

整个流程是 `init → catalog → download → content → index`，每个子命令都读同一个 `<out>/config.json`，可以随时中断重跑。

```bash
S=<此技能目录>/scripts          # 下面用 $S 指代
OUT=~/课程名                      # 输出目录，随便起

python3 $S/run.py init    --url "<课程链接>" --cookie "<cookie>" --out $OUT
python3 $S/run.py catalog --out $OUT
python3 $S/run.py download --out $OUT --videos 4 --seg 24   # 可反复重跑，自动续传
python3 $S/run.py content --out $OUT
python3 $S/run.py index   --out $OUT
python3 $S/run.py verify  --out $OUT

cd $OUT && python3 $S/serve.py 8765     # 打开 http://127.0.0.1:8765/web/
```

### 1. init —— 先确认登录态

用户必须自己在浏览器里登录小鹅通店铺（微信扫码/手机号），你拿不到验证码。

**拿 cookie 的方法**（这是最容易卡住的一步）：

1. 用 chrome-devtools MCP 打开任意一个小鹅通课程页，确认已登录
2. 用 `list_network_requests` 找一个 `POST` 请求（比如目录接口）
3. 用 `get_network_request` 复制完整的 `Cookie:` 请求头

至少要包含 `XIAOEID`、`pc_user_key`、`anonymous_user_key`、`cookie_session_id` 四个。

`init` 会立刻校验登录态并打印结果。**如果这里失败，让用户重新登录再取一次 cookie**，不要往下走——后面每一步都会失败在同一个地方。

### 2. catalog —— 抓目录

返回 25 章 289 节这种量级，几秒钟就够。

这里有个**必须同时传对两个参数**的坑，传错不会报错，只会静默返回全部章节，看起来"成功"了其实数据是错的：

- `p_id` 要传 `chapter_id`，**不是**返回列表里的 `p_id`（顶层章节的 `p_id` 是字符串 `"0"`）
- `sub_course_id` 必须传

`run.py` 已经处理好了，但如果你要手写请求，务必核对：抓到的小节总数应该和网页上显示的"小节数"一致。**对不上就是参数错了**，不要将就。

### 3. download —— 下载视频（耗时最长）

- 24 线程拉切片 → 逐段 AES-128-CBC 解密（IV 全 0，去掉 PKCS#7 填充）→ 顺序拼成 `.ts` → `ffmpeg -c copy` 转封装 MP4
- **转封装而不是重编码**：画质无损，几十倍快
- 实测参考：3 分钟视频 4 秒完成；4 视频并发约 20–50 倍实时；百 GB 课程 1–3 小时

**断点续传**：重跑同一条命令即可，已完成的会被跳过。

判断"已完成"用的是 `ffprobe` 探测时长，而不是看文件大小。**这一点很重要**——封装到一半被打断的 MP4 也有几百 KB，只看大小会把残缺文件当成完成品永久跳过。

**失败重试会自动轮换 CDN 线路**（zj→hw→tx）。单台边缘节点会偶发 SSL 握手失败，死磕同一条线路会白重试；换一条线路往往立刻就好了。

进度大的话直接放后台跑，配一个监控：

```bash
nohup python3 $S/run.py download --out $OUT --videos 4 --seg 24 > $OUT/_work/dl.log 2>&1 &
```

下载期间可以并行做 content 和 index。

### 4. content —— 抓非视频内容

- **图文正文**：在 `get.detail` 接口的 `org_content` 字段。注意传的是**小节自己的 resource_id**，传课程 ID 会返回空正文，像是"没数据"其实是参数错了。页面是纯 SPA，正文不在 HTML 里，curl 抓页面没用。
- **封面**：从目录里的 `img_url` 批量下
- **课程信息 / 互动模块统计**

有几类内容经常是空的，**要查了再下结论**，别默认自己抓失败了：

| 内容 | 接口 | 常见情况 |
|------|------|----------|
| 课程评论 | `api/xe.goods.comments.get` | 接口通但列表为空（`restrict: 1`） |
| 视频字幕 | `xe.course.business.video.ai.captions.get` | 返回"暂未开启字幕" |
| 互动/练习 | `interaction.get` | 各项 `count` 全是 0 |
| 富文本简介 | `course_detail.get` | 讲师没填，简介就是标题 |

抽样验两三节字幕就够了，不用全量试。

### 5. index + serve —— 本地学习库

`index` 生成 `web/course.json`（带章节树的单一数据源）并部署前端。

**必须用 `scripts/serve.py`，不能用 `python3 -m http.server`。** 内置服务器不支持 HTTP Range 请求：

```
Range: bytes=1000-1999  →  200 OK, Content-Length: 14170501   ← 整个文件！
```

浏览器拿不到字节区间，进度条就拖不动，而且连 `Accept-Ranges` 头都没有。`serve.py` 实现了标准 206 分区响应，顺带升级到 HTTP/1.1 keep-alive 和多线程。

功能：章节树、**断点续播**（每 5 秒记录，打开自动跳回）、进度追踪、标题搜索、0.75×–2× 倍速、每课笔记（可导出 Markdown）、未下载小节自动置灰跳过。快捷键 `空格`/`←→`/`j l`/`n p`/`c`/`f`/`m`/`[` `]`/`/`。

进度和笔记存在浏览器 localStorage，不是服务端。换浏览器或清缓存会丢，如果用户在意，可以加一个导出按钮（已有「导出进度」）。

## 关键接口速查

| 用途 | 接口 |
|------|------|
| 目录 | `xe.course.business_go.avoidlogin.e_course.resource_catalog_list.get/1.0.0` |
| **播放地址（明文）** | `xe.course.business.video.mutli_line/1.0.0` |
| 图文正文 | `xe.course.business.get.detail/2.0.0` → `data.org_content` |
| 课程信息 | `xe.course.business_go.avoidlogin.e_course.course_detail.get/1.0.0` |
| 互动统计 | `xe.course.business_go.interaction.get/2.0.0` |
| 评论 | `api/xe.goods.comments.get/1.0.0` |
| 字幕 | `xe.course.business.video.ai.captions.get/1.0.0` |

**`mutli_line` 是整件事的关键。** `video.detail_info.get` 返回的 `video_urls` 是混淆 base64（约 8% 字符被替换成 `#$%@_`，逆向成本很高）。`mutli_line` 直接给三条 CDN 线路的明文 m3u8，完全绕开混淆。**不要去逆向那个字段。**

m3u8 里 `#EXT-X-KEY` 的 `URI` 就是 AES-128 密钥接口，返回 16 字节。切片是同一个 TS 文件的字节区间（`?type=mpegts&start=&end=`），每段独立加密、独立填充。

更详细的接口字段、混淆分析、失败模式见 `references/api-notes.md`。

## 输出结构

```
<out>/
├── config.json          # 店铺域名 / 课程 ID / cookie
├── video/               # 001_章节_小节.mp4
├── cover/               # 001.jpg
├── article/             # 图文正文 .md + .html + 内嵌配图
├── text/                # 课程信息、互动统计
├── web/                 # course.json + 前端（课程库）
└── _work/
    ├── lessons.json     # 原始目录
    └── dl.log
```

## 需要注意的事

- **只用用户自己已购买、已登录的课程。** 技能不处理登录，也不应该被用来访问未授权内容。
- **cookie 有效期以小时到天计**（实测 22 小时后仍有效）。中途过期就重新跑 `init` 换 cookie，已下好的文件不受影响。
- **磁盘空间**：先估算——`总时长(小时) × 700MB` 上下，百小时课程约 70 GB。用 `df -h` 确认。
- **下载大文件时留意 CDN 限速**，并发调太高反而更慢；`--videos 4 --seg 24` 是实测比较稳的组合。
