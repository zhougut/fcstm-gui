# 操作手册独立盲审：第 2 轮

- reviewer: OMX verifier (`m4_dynamic_service`)
- date: 2026-07-12
- reviewed source: 当前 M7 工作树
- environment: Linux source checkout；Qt offscreen 文档测试；本地 PNG 像素抽检
- scope: 最新手册、README、67 张 workflow images、manifest 和第 1 轮记录
- verdict: `C=2 / I=3 / M=1 / NOT READY`

## 已关闭

- 第 1 轮审阅表列数错误已修正。
- 图片从 32 张/20 ID 扩展到 67 张/53 ID。
- 67 张图片的 SHA-256、size、PNG magic、width/height 全部复算通过。
- 公式、图形导出、仿真停止/重置、动态 mutation/recover、自定义模板、九类统一导出、任务清理和 dirty/stale 代表图已补充。
- README 已把完整操作验收手册作为主入口，并明确发布包不要求 Python、Graphviz 或编译器。

## 仍阻断

1. 完整 GUI §12 矩阵尚未全部进入独立 acceptance 和截图。
2. Linux、Windows、macOS fresh onedir/onefile 尚未完成最终人工审图和 attestation。
3. 36 组 geometry/a11y 报告尚待最终 CI 产出。
4. 当前 manifest 来源为 dirty worktree，只能作为 source-reference。

用户主动选择的场景、模板或输出路径允许在对应输入框显示；任务历史、复制、持久化和日志默认仍必须脱敏。最终 fresh 证据前继续检查该边界。
