# 操作手册独立盲审：第 3 轮

- reviewer: OMX verifier (`ux_prototype_review`)
- date: 2026-07-12
- scope: 当前候选的 140 项 acceptance 合同、完整操作手册、67 张 xcb 源码参考图
- source-ready verdict: `C=0 / I=0`
- release verdict: `NOT READY`，仅等待 push 后三平台 fresh 证据闭环

## 已复核

- 手册精确包含 140/140 稳定 acceptance ID。
- `graph.selection`、`W_DEADLOCK_LEAF` suggested-fix 和四个 packaged dynamic case 均有确定输入与独立 oracle。
- cancel/stale 提供发布包内置的确定性验收命令、状态和 artifact inventory 核对方法。
- onedir/onefile 的 POSIX 与 Windows PowerShell 启动路径可直接照抄。
- dynamic mutation/recover、自定义模板、任务清理、四类公式、dirty 三分支和 stale 图已直接嵌入正文。
- 67 张 PNG 的 SHA、尺寸、CJK 字体、主要布局、Smetana 图和路径脱敏合同通过。
- source manifest 明确 `fresh_release_evidence=false`，没有冒充最终发布证据。

## 最终外部门禁

三平台 onedir/onefile fresh acceptance、36 组 geometry/a11y、产物下载复算和 final visual attestation 必须由本候选 push 后的 GitHub Actions run 生成并人工复核。完成前不得关闭 Issue #2。
