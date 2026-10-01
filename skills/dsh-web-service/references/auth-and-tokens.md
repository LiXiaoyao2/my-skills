# dsh web 的认证与 token 机制

在 `dsh@0.2.0-rc.2` 上实测得出。认证逻辑不在 `@deepseek-ai/dsh-host-webserver` 里，
而在 `@deepseek-ai/dsh-client-connection` 里——排查时从后者开始找。

## 目录

- [裸地址为什么永远 401](#裸地址为什么永远-401)
- [两步认证的完整流程](#两步认证的完整流程)
- [cookie 里存了什么](#cookie-里存了什么)
- [token 无法固定](#token-无法固定)
- [token 轮换的连带影响](#token-轮换的连带影响)
- [怎么把当前 token 取回来](#怎么把当前-token-取回来)
- [可选出路：常驻代理](#可选出路常驻代理)
- [与系统密钥环无关](#与系统密钥环无关)

## 裸地址为什么永远 401

`http://127.0.0.1:3080/` 不带任何凭证时返回：

```
HTTP/1.1 401 Unauthorized
dsh web authentication required; reopen the URL printed by dsh web.
```

这是**设计行为，不是故障**。dsh web 只在进程启动时打印一次带 token 的地址，
之后所有请求都必须携带由该 token 换来的 cookie。不要看到 401 就去查防火墙、
重装依赖、清缓存——那些都不会有用。

## 两步认证的完整流程

第一步，访问带 token 的地址：

```
GET /?token=<43位base64url>
→ 303 See Other
   location: ./
   set-cookie: dsh-auth-<实例secret>=v1.<base64url载荷>.<base64url签名>;
               Max-Age=2592000; Path=/; HttpOnly; SameSite=Strict
```

第二步，之后访问裸地址并带上该 cookie → `200`。

几个实测细节：

- `Max-Age=2592000` = 30 天。首访一次后裸地址管用一个月。
- **没有 `Secure` 标记**，所以 `http://` 下能正常下发，浏览器不会拒收。
  如果哪天看到"token 明明对了却还是 401"，先确认中间没有 HTTPS 反代把 `Secure` 加上。
- `SameSite=Strict` + 顶层导航，cookie 正常写入，实测浏览器可存。
- cookie 名里嵌了实例 secret（`dsh-auth-VPhEEcLKeqRDBoBalzN2Nm7CnfxKhLE00pKIDWxt1sw`），
  **实例一重启 cookie 名就变**，旧 cookie 对新实例无效。

## cookie 里存了什么

载荷是 base64url 的 JSON，解开是这样：

```json
{"version":1,"authority":"127.0.0.1:3080","issuedAt":1790818720401,"expiresAt":1793410720401}
```

`authority` 绑定了 host:port。所以同一个浏览器标签里 `localhost:3080` 和
`127.0.0.1:3080` 是两份独立会话，token 也不能在两者间互换——排查"明明同一个
地址却不认"时，这是常见原因之一。载荷尾部是 HMAC 签名，客户端无法伪造。

## token 无法固定

结论：**dsh 没有提供任何固定 token 的官方手段**。已逐项排除：

| 怀疑的开关 | 实测结果 |
|---|---|
| `dsh web` CLI 参数 | 只有 `--host` / `--port` / `--no-open` / `--trusted-host`，无 token/secret 相关 |
| `dsh-host-webserver` 配置 | 该包内 `auth`/`secret`/`token` 相关配置键数为 0 |
| `dsh-client-connection` 配置 | 配置 schema 只有一个字段：`message: String(...)` |
| 环境变量 | 两包内仅有 `DSH_BOOT_READY__` / `DSH_CONNECTION_RECOVERY__` / `DSH_TRANSPORT__`，均与认证无关 |
| 磁盘持久化 | `~/.dsh/.credentials.yaml` 顶层键为 `version`/`refs`/`records`，不含 web token |

因此 token 只能由进程启动时随机生成。想让某个链接长期有效，唯一办法是
**别让进程重启**。

## token 轮换的连带影响

`dsh-web.service` 里 `Restart=always` 意味着：服务崩溃 → 3 秒后重启 →
token 换了 → 用户下次打开裸地址 401，且界面上没有任何提示说明发生过重启。

**这条坑我自己踩过**：给用户发完带 token 的链接之后，为测试端口避让把服务
重启了 4 次，用户手上的链接当场作废。顺序应该是：**先把要做的事做完并验证，
再把链接交给用户**；如果之后必须重启，要主动说明"刚才那个链接已失效，
新的在这里"。

同理，不要为了"顺手验证一下"就重启正在服务的进程。

## 怎么把当前 token 取回来

按可靠性从高到低：

1. `dsh-web-url` —— 读 wrapper 启动时抓下来的文件（`~/.local/state/dsh-web/url.txt`，权限 600）
2. `journalctl --user-unit dsh-web -b | grep -ao 'http://127.0.0.1:3080/?token=[A-Za-z0-9_-]*'`
   —— unit 里 `StandardOutput=journal`，启动打印的 URL 只在这里
3. 直接看 token URL 打印出来的那个终端窗口（如果是从交互终端起的）

文件里若第一行是 `# STOPPED at ...`，说明服务已停、token 已失效，重启后再取。

## 可选出路：常驻代理

若希望裸地址永久可用（包括服务崩溃重启之后），唯一办法是在 dsh 前面加一层
反向代理：代理占住 3080，检测到请求没带有效 cookie 就 302 到
`/?token=<当前 token>`，dsh 本身挪到内网端口。

代价是**多一个常驻进程和一层转发**，且代理必须和 dsh 一起被守护。
本技能没有内置这个方案——多数场景 `dsh-web-url --open` 一条命令就够了，
不值得为它引入新的故障面。真要做时，注意代理不能缓存带 cookie 的响应。

## 与系统密钥环无关

网上有把 dsh web 认证和 gnome-keyring / Secret Service 联系起来的猜测。
实测排除：

- `dsh` 的 `lib/bin.js` 中 `keytar`、`libsecret`、`org.freedesktop.secrets`、
  `gnome-keyring` 命中数**全为 0**
- `~/.dsh/.credentials.yaml` 不含 keyring 相关字样
- 停掉 gnome-keyring 后 dsh 行为完全不变

dsh 的 token 是自己进程内生成的，跟桌面会话的任何 secret 服务没有关系。
