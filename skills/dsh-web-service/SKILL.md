---
name: dsh-web-service
description: 把 DeepSeek Harness(dsh) 的 web 版注册成 systemd 用户服务开机自启，并解决它的 token 认证、端口冲突、启动 URL 丢失这三个原生痛点。只要用户提到 dsh web、dsh web 自启、DeepSeek Harness web 版、127.0.0.1:3080、dsh 打开后 401、dsh web authentication required、dsh 端口被占用 EADDRINUSE、dsh 每次重启地址/链接都会变、想让 dsh web 像本地服务一样稳定可用，就用本技能。也用于反过来拆掉这套自启、回归"手动跑 dsh web"的普通用法，以及判断"我并不天天用 dsh，到底该不该装这套"。
---

# dsh web 常驻服务

## 你要先知道的事

**dsh web 的地址不能想当然。** 直接开 `http://127.0.0.1:3080/` 永远返回
`401 dsh web authentication required`。这不是坏了，是它的认证是两步的：

1. 进程启动时，它在 stdout 打印**一次**带 token 的地址
2. 打开那个地址 → `303` 跳转 + 下发 `dsh-auth-*` cookie（30 天有效）
3. 之后裸地址才认你

所以"3080 打不开"有三种完全不同的原因，别混为一谈：服务没起、端口被别人占了、
或者只是没带 token。判断方法见下面的排障表。

**token 每次进程启动重新随机生成，而且没有官方手段固定。** 已逐项排除 CLI 参数、
webserver 插件配置、认证插件配置 schema、环境变量、磁盘持久化（详见
`references/auth-and-tokens.md`）。这带来一个决定性推论：

> **想让某个链接长期有效，唯一办法是别让进程重启。**

## 先问一句：真的需要常驻吗

这套方案解决的是"每天都要用 dsh"的场景。如果你并不天天用它——一天开一次、
每次都能自己跑 `dsh web`——那么**手动跑更清爽**：

```bash
dsh web
# 终端里直接打印带 token 的地址，打开就行
```

此时唯一真正需要额外工具的场景是：服务已停，想从 journal 里把上次那条
带 token 的地址捞回来：

```bash
journalctl --user-unit dsh-web -b | grep -ao 'http://127.0.0.1:3080/?token=[A-Za-z0-9_-]*'
```

**别为了"看起来更完备"就给用户装上开机自启。** 多一个常驻服务就多一处
token 轮换的烦恼（见下面的坑），用户没提出要常驻就手写一行命令更合适。

## 安装（用户明确要常驻时）

```bash
S=~/.cc-switch/skills/dsh-web-service/scripts

bash $S/install.sh
```

`install.sh` 会定位 dsh 与 node 的绝对路径、装两个脚本、写 unit、
`enable --now`，最后打印当前可用地址。可重复运行。

装完得到：

| 路径 | 作用 |
|---|---|
| `~/.config/systemd/user/dsh-web.service` | 服务定义 |
| `~/.local/bin/dsh-web-launcher` | 端口避让 + 抓 token URL |
| `~/.local/bin/dsh-web-url` | 取当前地址，支持 `--open` |
| `~/.local/state/dsh-web/url.txt` | 落盘的 token URL（权限 600） |

日常只需要一条命令：

```bash
dsh-web-url          # 打印当前带 token 的地址
dsh-web-url --open   # 直接开浏览器
```

## 为什么要一个 launcher，不能直接 `ExecStart=dsh web`

原生写法有两个洞，launcher 各补一个：

**端口。** dsh 自带 `--port 0`（让 OS 随便挑），但我们要的是"固定 3080，
被占了才往后找"——这样浏览器书签、端口转发规则才稳定。直接 `ExecStart=dsh web --port 3080`
在 3080 被占时会以 `EADDRINUSE` 崩掉；而 `Restart=always` 会让它陷入
每 3 秒崩一次的循环。

**URL。** unit 里 `StandardOutput=journal`，启动时那条带 token 的地址只存在
journal 里。launcher 用 `tee` 旁路一份并正则抓出来写进文件，用户随时能取，
不用去翻日志。

launcher 还必须**转发 SIGTERM**：unit 用 `KillMode=mixed`，SIGTERM 只发给
MainPID（也就是 launcher），不转发的话 systemd 等满 `TimeoutStopSec` 再
SIGKILL，会留下孤儿 node 进程占着端口。

## 排障表

| 现象 | 真实原因 | 处理 |
|---|---|---|
| 401 `authentication required` | 没带 token，**正常** | `dsh-web-url --open` |
| 401 但刚开过 token 地址 | 服务重启过，token 换了 | `systemctl --user restart dsh-web` 后重新取 |
| `EADDRINUSE 127.0.0.1:3080` | 已有实例占着 | 用 `systemctl --user restart dsh-web`，**别再手敲 `dsh web`** |
| 手动 `dsh web` 报端口占用 | 同上 | 先 `systemctl --user stop dsh-web` |
| 开了 token 地址仍 401 | 用了 `localhost` 而 token 绑 `127.0.0.1`，或反代加了 `Secure` | 见 `references/auth-and-tokens.md` 的 cookie 一节 |
| `env: node: No such file` | unit 的 PATH 缺 nvm 路径 | `install.sh` 会算好；手改 unit 时注意 `Environment=PATH` |
| 服务起不来，看 journal | 真实原因都在里面 | `journalctl --user-unit dsh-web -b -n 50` |

## 别踩的坑

- **先验证、再把链接交给用户。** 这个坑我踩过：给用户发完带 token 的链接，
  随后为测试端口避让把服务重启了 4 次，用户手上的链接当场作废。顺序反了就是在
  给用户制造假故障。如果之后必须重启，主动说明"刚才那条已失效，新的在这里"。

- **`pkill -f` / `pgrep -f` 会匹配到自己的命令行。** 用字符类：
  `pgrep -f "[d]sh web"` 而不是 `pgrep -f "dsh web"`。否则 shell 会把自己杀掉。

- **`set -o pipefail` 下别用 `cmd | grep -q`。** `grep -q` 命中即退出，上游进程
  收到 SIGPIPE（141），`pipefail` 把整条管道判为失败，条件随机为假。实测同一段
  `systemctl --user list-unit-files | grep -q "^foo.service"` 连跑六次得到
  `FTFFTF`。这个坑在本技能里造成过真实故障：unit 存在性判断随机漏检 → 服务没停
  就把 unit 删了 → 留下占着 3080 的孤儿进程，下次手动 `dsh web` 直接撞
  EADDRINUSE。写判断请用 `grep -c`（读完整个输入，无竞态），或干脆不用管道、
  直接看命令退出码。

- **别用 `gh` 的 token 做 GitHub 操作。** 它常处于失效状态；这台机器上
  `gh auth status` 报 token invalid，但 SSH 推送是通的，直接用 `git push`。

- **`dsh-web-url` 打印的文件头若是 `# STOPPED`，别拿它去访问。** 说明服务已停，
  token 失效，重启后重取。

## 已知限制

- **token 无法固定**，这是 dsh 的设计而非本方案的缺陷。`Restart=always` 下
  崩溃即轮换，用户下次访问裸地址会 401 且无提示。若要根治，只能加一层常驻
  代理把裸地址 302 到当前 token 地址，代价是多一个进程和一层转发。
  思路写在 `references/auth-and-tokens.md`，本技能不内置。
- **窗口/UI 未做可视化验证。** 认证链路已用 curl 和真实浏览器端到端验证过
  （token 地址 → 303 → cookie → 裸地址 200 → 页面正常渲染），但"页面看起来
  对不对"仍需用户自己确认，别替他断言。
- 未在非 GNOME 环境验证。本方案依赖 `systemctl --user` 与
  `XDG_RUNTIME_DIR`，其他桌面环境应先确认 `systemctl --user` 可用。

## 拆掉，回归手动用法

```bash
bash ~/.cc-switch/skills/dsh-web-service/scripts/uninstall.sh
```

会停用并 `disable` 服务、把 unit 移走（备份到 `~/.local/state/dsh-web/`）、
删掉两个脚本，并自检确认没有残留自启。想保留脚本（比如还想用 `dsh-web-url`
捞 URL）就加 `--keep-scripts`。脚本可重复运行，已经拆干净时不会报错。

## 参考

- `scripts/install.sh` —— 装服务（幂等，含路径探测与 unit 生成）
- `scripts/uninstall.sh` —— 拆服务（幂等，含残留自检）
- `scripts/dsh-web-launcher` —— 端口避让 + token URL 落盘 + 信号转发
- `scripts/dsh-web-url` —— 取当前地址
- `references/auth-and-tokens.md` —— 认证机制实测细节、cookie 结构、
  token 为何无法固定、代理方案思路、与密钥环无关的排除过程
