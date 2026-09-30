# my-skills

个人技能仓库。每个技能是仓库根目录下的一个独立子目录，目录内含一个 `SKILL.md`，
可直接安装到 Claude Code / minimax Code 的技能目录。

私有仓库，不对外公开。

## 结构

```
my-skills/
├── README.md
└── <技能名>/
    ├── SKILL.md          必需：YAML frontmatter + 技能说明
    ├── scripts/          可选：可执行脚本
    ├── references/       可选：按需加载的参考文档
    └── assets/           可选：输出用模板/资源
```

## 安装某个技能

把技能目录软链到技能搜索路径即可（本机是 `~/.cc-switch/skills`，再由
`~/.claude/skills` 软链过去）：

```bash
ln -s "$PWD/dsh-linux-desktop" ~/.cc-switch/skills/dsh-linux-desktop
ln -s ~/.cc-switch/skills/dsh-linux-desktop ~/.claude/skills/dsh-linux-desktop
```

或直接复制：

```bash
cp -r dsh-linux-desktop ~/.claude/skills/
```

## 卸载

```bash
rm ~/.claude/skills/dsh-linux-desktop ~/.cc-switch/skills/dsh-linux-desktop
```

## 新增技能

1. 建 `<技能名>/SKILL.md`，frontmatter 至少含 `name` 和 `description`
2. `description` 决定触发准确率，写清「做什么」和「什么情况下用」
3. 提交推送：`git add . && git commit -m "..." && git push`

## 现有技能

| 技能 | 说明 |
|---|---|
| [dsh-linux-desktop](dsh-linux-desktop/) | 从官方源码构建 DeepSeek Harness 桌面端的 Linux x64 AppImage。官方不发布 Linux 包且构建流水线硬编码拒绝 Linux，需要打 11 处锚点补丁。 |
| [xiaoe-course-library](xiaoe-course-library/) | 把小鹅通付费课程完整归档到本地，下载全部视频并生成带章节树、断点续播、进度与笔记的本地学习网页库。 |

## 约定

- 技能里不要写死绝对路径，用 `~` 或相对自身目录的路径
- 脚本要可重复运行（幂等），失败时明确报错而非静默跳过
- 改动应用源码时，尽量把修改收敛在构建/配置层，并保持应用逻辑零改动
