# 操作手册独立盲审：第 1 轮

- reviewer: OMX verifier (`m4_dynamic_service`)
- date: 2026-07-12
- reviewed source: 当前 M7 工作树
- environment: Linux source checkout；文档测试使用 Qt offscreen
- scope: Issue #2 第 12 节全部显式 ID、手册第 0-9 节、workflow image manifest
- verdict: `C=2 / I=3 / M=1 / NOT READY`

## 已复核

- 手册 fixture、确定输入、操作步骤、oracle、失败恢复和记录模板基本可执行。
- `test/docs` 的 9 项测试通过，覆盖 loader、import、dynamic pass/mismatch 和自定义模板正反路径。
- 当前 32 张图片是 Linux xcb 源码参考图，manifest 正确标记 `fresh_release_evidence=false`。

## 阻断项

1. 尚未完成至少两轮独立盲操作和最终 fresh 复现。
2. 尚无 Linux、Windows、macOS 的 fresh onedir/onefile 完整截图、manifest 和 visual attestation。
3. dirty、CRUD、formula、stale、cancel、geometry/a11y 等扩展 family 仍缺逐项截图或最终报告。
4. 本轮发现手册审阅表的 10 列表头对应 11 列分隔符，已在本轮修正。

在扩展 acceptance、截图和 fresh CI 证据齐全前，本记录不得改写为 READY。
