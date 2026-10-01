# 升级 dsh CLI

dsh 是 nvm 下的**静态全局 npm 包**。`npm i -g` 装完之后，没有任何机制会再去更新它——
systemd（如果启用了）只是启动已装的包，npm 自己也不会升级全局包。所以升级必须手动做。

> 背景：本文件记录的是旧 `dsh-update` 脚本里的经验。该脚本已随 dsh-web 服务一起拆除
> （它绑定在重启服务和就绪探测上，服务没了之后必然失败）。下面只保留**与常驻服务无关、
> 对手动用法仍然成立**的部分。

## 必须显式走官方源，不要用 npmmirror

```
REGISTRY="https://registry.npmjs.org"
```

**npmmirror 会静默漏掉平台二进制包。** 表现是装的时候一切正常，npm 退出码 0，
`UNMET OPTIONAL DEPENDENCY` 只是警告，然后**跑起来才炸**。dsh 的依赖树里正好有一堆
这类平台相关的包（sandbox FFI、landlock、原生模块等），踩中概率不低。

用 `npm i -g --registry=https://registry.npmjs.org` 显式指定，别依赖全局 `.npmrc`。

## 显式带代理

```
--proxy=http://127.0.0.1:7897 --https-proxy=http://127.0.0.1:7897
```

本机直连 npm 时好时坏，而且 Clash 的 TUN 模式有「开机变关」的历史坑。
升级前先确认代理端口在听（`ss -ltn 'sport = :7897'`），否则 npm 会卡到超时。

## `uv_cwd ENOENT` 陷阱

`npm i -g` 会把旧的包目录**整个删掉重建**。如果调用者的 cwd 正好在那个目录里
（比如刚 `cd` 进去翻了翻代码），目录一消失，后面每次 `node` / `npm` 调用都会以
`uv_cwd ENOENT` 失败。

这个报错很有迷惑性：它看起来像「装完体检不通过」，于是人会以为是包坏了，
实际上根因只有一个——cwd 不存在了。**升级前先 `cd /tmp`**，一步就能规避。

## 升级后要验的是平台二进制包，不是退出码

npm 退出 0 只说明"没报错"，不说明平台相关的 optional dependency 真的装上了
（见上面 npmmirror 那条）。升级后应当确认平台特定的原生包确实存在于
`node_modules/@deepseek-ai/dsh/node_modules/` 下，而不是只看到一条 warning。

## 就绪信号是日志行，不是端口

`dsh web` 启动时会打印一行带 token 的 URL：

```
dsh web: http://127.0.0.1:3080/?token=...
```

**这行才是就绪信号**——dsh 的 web-app 文档明确说明它只在 Loader tree 稳定、
认证可用之后才打印。

不要用 `curl http://127.0.0.1:3080/` 来判断"起来了没有"：端口在真正就绪之前
就可能已经在监听了，这时 curl 拿到的是 401（认证还没配好），会被误判成启动失败。

正确做法是等那行日志，或者直接用上面打印出来的完整 URL 访问。

## 如果重新启用 systemd 服务

有个额外的坑：脚本和服务必须用**同一个 node**。nvm 是按版本分别安装的，
服务侧若通过 `nvm-exec` 固定到某个版本，而升级脚本用的是 `nvm default`，
就会出现「脚本升了 A 版本、服务跑的是 B 版本」——排查起来非常费时间。
本技能的 `install.sh` 已经把两者写成同一个绝对路径来避免这个问题。

## 手动升级的最短路径

```bash
cd /tmp   # 规避 uv_cwd 陷阱
npm i -g --registry=https://registry.npmjs.org @deepseek-ai/dsh
dsh --version
```

需要指定通道时加 `--tag next`。升完直接 `dsh web`，地址会打印在终端里。
