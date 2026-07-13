# 【M7 最终产品化】九项 GUI 验收现状回读、交互补强、全流程截图手册与跨平台证据闭环

> **历史规划归档（superseded）**：本文件保留早期 M7 施工决策和失败复盘，文中
> `5c13c32`、`179/179`、`11/11`、旧 CI run 与 `[ ]` 清单不是当前完成状态。
> 当前可执行合同以 `docs/验收矩阵.md`、`docs/验收证据索引.md`、
> `docs/完整操作验收手册.md`、`CLAUDE.md` 和 `.github/workflows/` 为准；稳定
> 目录是 `182` self-check 与 `140` GUI acceptance。不要照着本归档中的旧命令
> 或旧数量重新验收。

## 1. 背景与最终结论

本 Issue 是 [fcstm-gui #1](https://github.com/zhougut/fcstm-gui/issues/1) 的现状回读与最终收口，不复制已经过时的 M0-M6 初始差距描述。权威上游为 [pyfcstm #360](https://github.com/HansBug/pyfcstm/issues/360) 与永久 Draft 验收分支 [pyfcstm PR #362](https://github.com/HansBug/pyfcstm/pull/362)。

截至 `main@5c13c32`，底层架构、179 项产品自检、两阶段三平台构建与当前 11 项 GUI acceptance 已经建立，但产品仍然 **NOT READY**。关键原因不是 job 是否绿色，而是现有验收存在覆盖空洞和一个已证实的跨平台假阳性：Linux、macOS fresh onefile 的图形截图实际显示 PlantUML `Cannot find Graphviz`，当前 acceptance 只断言 `QGraphicsScene` 非空，因而错误报告通过。

本 Issue 关闭前必须同时满足：

1. 九项 GUI 用户路径均有控件级真实执行；
2. self-check 与 acceptance 分项覆盖上游核心能力，且不是只 import binding；
3. Linux、Windows、macOS 各自构建，fresh runner 只配置不可避免的系统运行时后做黑盒实测；
4. 完整中文操作手册和经人工复核的三平台截图进入 `docs/images/`；
5. 每一验收项均能追溯到测试、JSON、截图、产物 SHA 和 CI job；
6. 独立审阅达到 `C=0`、`I=0`、`READY`。

## 2. 权威范围与术语

### 2.1 权威来源

| 来源 | 本 Issue 使用方式 |
| --- | --- |
| `DESIGN.md` | GUI 信息架构、用户路径、状态与证据合同 |
| fcstm-gui #1 | 67 项历史验收清单及 M0-M6 设计依据 |
| pyfcstm #360 | 四类成品、核心功能、净化和验收边界 |
| pyfcstm PR #362 | 已冻结后端入口、五模板、PlantUML、仿真、动态验证与交付证据 |
| `CLAUDE.md` | 本仓库持续加厚的工程与跨平台维护纪律 |

### 2.2 术语边界

- **普通仿真**：围绕同一 `SimulationRuntime` 会话执行初始化、单步、连续、暂停、继续和重置。
- **动态验证**：使用独立 runtime 按场景执行并比较 expected/actual；它不是 SMT、BMC、模型检测或形式化验证。
- **self-check**：冻结成品内部对 pyfcstm 库闭包、原生依赖和主干功能的真实逻辑检查。
- **acceptance**：从 GUI 命令、控件、对话框和键盘路径出发的黑盒用户流程，不能由 service-only 测试替代。
- **fresh verify**：新 runner 不安装项目 Python、项目依赖、编译器或 Graphviz，也不调用 runner 预装编译器。运行时 allowlist 固定为 JRE 与 GUI 显示宿主；禁止 `apt`/`brew`/`choco install graphviz`。图形必须使用不依赖 Graphviz 的内置布局引擎。

## 3. 当前事实基线

| 基线 | 当前证据 | 判定 |
| --- | --- | --- |
| 主分支 | `main@5c13c32`，与 `origin/main` 一致 | 已冻结 |
| 产品测试 | 本地 `406 passed` | 已通过，但需在 M7 改动后重跑 |
| self-check | 114 module closure + 65 behavior = `179/179` | 已通过 |
| acceptance | 每份当前 `11/11` | 通过但粒度不足 |
| CI | [run 29186387692](https://github.com/zhougut/fcstm-gui/actions/runs/29186387692)，3 Package + 3 fresh Verify | job 全绿但图形验收存在假阳性 |
| artifacts | 3 个 onedir + 3 个 onefile + 6 个 evidence，均记录 digest | 已产出 |
| 报告 | 15 份 self-check JSON + 90 份 acceptance JSON | 已审计 |
| manifest | 1170 个条目的 size/SHA 已校验 | 已通过 |
| fresh 截图 | Linux/macOS/Windows onefile 200% 已人工查看 | 字体正常；Linux/macOS 图形失败 |
| 维护入口 | `CLAUDE.md`；`AGENTS.md -> CLAUDE.md` | 已建立并持续加厚 |

当前 CI 的绿色只能证明 workflow 正常执行了现有检查，不能证明现有检查足够。

## 4. Issue #1 的 67 项重新审计

记号：`D` = 当前证据直接证明；`P` = 只证明部分路径；`M` = 缺失或证据不足。审计采取保守口径，不把 application/service 测试外推为 GUI E2E。

| 原清单分节 | 逐项状态 | 小计 |
| --- | --- | --- |
| 11.1 模型与编辑 #1-18 | `1D 2D 3D 4D 5D 6D 7P 8P 9D 10D 11D 12D 13D 14D 15D 16D 17D 18P` | 15D / 3P |
| 11.2 图形与检查 #19-25 | `19P 20P 21D 22D 23D 24P 25D` | 4D / 3P |
| 11.3 公式编辑 #26-31 | `26D 27P 28D 29D 30D 31D` | 5D / 1P |
| 11.4 仿真与动态验证 #32-40 | `32P 33D 34D 35D 36D 37D 38D 39P 40P` | 6D / 3P |
| 11.5 生成、日志与导出 #41-52 | `41D 42P 43D 44P 45P 46P 47P 48D 49D 50D 51P 52D` | 6D / 6P |
| 11.6 质量和交付 #53-67 | `53D 54P 55D 56D 57D 58D 59D 60D 61P 62D 63D 64P 65P 66P 67M` | 9D / 5P / 1M |
| 合计 | 67 项 | **45D / 21P / 1M** |

### 4.1 部分或缺失项的实际差距

| 原编号 | 差距 | M7 关闭证据 |
| --- | --- | --- |
| #7、#8、#18 | 未冻结证明状态、变量、事件、迁移、guard、effect、lifecycle 的完整 GUI 编辑和 fresh reload；复合状态重命名明确不支持 | 组件级 GUI E2E + 保存重载事实对比 |
| #24 | warning 已有测试，但冲突迁移仍缺具体 GUI fixture | 诊断来源/等级/冲突 fixture 截图与 JSON |
| #32 | “停止”是取消，不是真正暂停后继续同一 runtime | `running -> pause-requested -> paused -> running` 验收 |
| #39 | 六类显式任务没有冻结 GUI 取消矩阵 | 每类边界、部分证据、临时文件和旧目标检查 |
| #40 | 文档有术语边界，UI 内无可见说明 | 动态验证页固定说明与截图 |
| #42、#44、#45 | service/self-check 覆盖五模板和自定义模板，GUI 只生成 Python | 五个内置模板 + 一个自定义模板路径的 GUI 生成、覆盖确认、取消和恢复 |
| #46 | 原子发布 service 有测试，GUI 取消后目标保持未共同证明 | 图形/生成/导出 GUI 黑盒 manifest 对比 |
| #47 | 任务中心已接入多个任务，但无显式/瞬时任务枚举证明 | 任务注册矩阵测试 |
| #51 | 九类导出 service 可用，GUI acceptance 只导出 inspect JSON | 九类逐项对话框实测、magic/schema |
| #54、#61 | 当前 11 项 acceptance 太粗，多个步骤只是 service 或最小控件动作 | 本 Issue 第 12 节扩展矩阵 |
| #65 | 有几何与字体机械检查，没有持久化逐截图复核结论；图形假阳性已证明 | 三平台视觉审计报告 |
| #66 | `docs/使用说明.md` 只是摘要，且引用不存在图片 | 完整手册 + 八个核心目录及全部用户流程的分步/失败恢复图片 |
| #67 | 没有 67 项逐项证据索引 | Markdown + schema 化 JSON 证据索引 |

### 4.2 逐项可复核证据映射

下表给出当前判定的首要证据入口；`D` 仍需在 M7 后由最终 run 复验，`P/M` 保持开放。稳定测试 ID 与最终 run artifact 链接将在 `docs/验收证据索引.md` 展开。

| # | 判定 | 当前首要证据/未证事实 |
| ---: | :---: | --- |
| 1 | D | `.github/workflows/build.yml` 固定 pyfcstm 来源与报告 provenance |
| 2 | D | workflow/artifact label 使用 `windows-x86_64`，无 win7 实机声称 |
| 3 | D | `app/application/document.py` + `test/application/test_document.py` |
| 4 | D | `app/source/index.py` 使用生产 loader 构建 index/model |
| 5 | D | document load encoding/cancel/failure tests |
| 6 | D | failed-load preservation tests 与 `document_load_finished` |
| 7 | P | 局部表单存在；缺七类 GUI 完整 CRUD/fresh reload |
| 8 | P | SourceRef/index 单测存在；缺复合状态 name-token 编辑 |
| 9 | D | imported/read-only/source navigation tests |
| 10 | D | `TextEdit` base revision/ref overlap 门禁测试 |
| 11 | D | source preservation/CRLF/Unicode tests |
| 12 | D | undo/redo/dirty replacement tests |
| 13 | D | complete loader + inspect/save validation tests |
| 14 | D | valid snapshot action enablement tests |
| 15 | D | validation state/severity tests |
| 16 | D | `require_current_valid_snapshot` task publication tests |
| 17 | D | canonical URI + dependency SHA/fingerprint tests |
| 18 | P | 简单编辑/保存事实有证据；缺完整模型 GUI fresh reload |
| 19 | P | 图形控件路径存在；Linux/macOS fresh 实际为 Graphviz 错误图 |
| 20 | P | 四类 service 导出通过；三平台真实图与 GUI 导出未共同证明 |
| 21 | D | diagnostics DTO/source_kind/provenance tests |
| 22 | D | syntax/model/inspect 字段映射 tests |
| 23 | D | diagnostics filter/search/detail/navigation tests |
| 24 | P | warning 测试存在；缺冲突迁移 GUI fixture |
| 25 | D | suggested-fix preview/confirm/revalidate tests |
| 26 | D | guard logical editor tests |
| 27 | P | numeric service/widget 能力存在，但没有接入实际 GUI 数值字段 |
| 28 | D | effect/lifecycle production-fragment tests |
| 29 | D | debounce revision stale tests |
| 30 | D | formula position/reason tests |
| 31 | D | full-model save gate tests |
| 32 | P | init/step/run/reset/cancel 已有；缺 pause/continue 同一 runtime |
| 33 | D | `app/application/simulation.py` 与 dynamic service 均用 production runtime |
| 34 | D | versioned scenario loader tests |
| 35 | D | expected/actual/exception/cause report tests |
| 36 | D | rollback runtime fixture/tests |
| 37 | D | 四个 packaged scenario self-check items |
| 38 | D | mutation mismatch + restored rerun self-check items |
| 39 | P | service boundary 测试；缺六类控件级取消矩阵 |
| 40 | P | 文档有术语边界；UI 无可见声明 |
| 41 | D | generation dialog/service language filtering tests |
| 42 | P | 五模板 self-check/build 通过；GUI acceptance 仅 Python |
| 43 | D | build runner 实际运行 Python、编译运行四套 C/C++ |
| 44 | P | custom template service 可用；GUI 路径未冻结 |
| 45 | P | overwrite/cancel/recovery 局部测试；缺完整 GUI 路径 |
| 46 | P | service 原子发布 tests；缺 graph/generation/export GUI 取消共同证明 |
| 47 | P | 多类 TaskRecord 已接入；缺显式/瞬时任务完整枚举 |
| 48 | D | task dock filter/copy/export/clear/retry/artifact widget tests |
| 49 | D | task history schema/retention/quarantine tests |
| 50 | D | redaction/full-path opt-in tests |
| 51 | P | 九类 export service 通过；GUI acceptance 仅 inspect JSON |
| 52 | D | export magic/schema validation tests |
| 53 | D | 基线本地 `406 passed`；M7 后须全量重跑 |
| 54 | P | 当前 acceptance `11/11`，不足以覆盖九项完整 GUI 用户流 |
| 55 | D | self-check 114 module closure 与 behavior 分开报告 |
| 56 | D | runtime 多 cycle behavior item |
| 57 | D | dynamic 四正例/mutation/restore/SHA 独立 items |
| 58 | D | Z3 integer/unsat/real/bitvector/optimize 五项真实断言 |
| 59 | D | self-check `BaseException` 隔离与最终非零 tests |
| 60 | D | self-check/acceptance versioned JSON schema |
| 61 | P | acceptance 驱动部分控件，但存在 setter/slot 替代用户路径 |
| 62 | D | run 29186387692 三平台 Package 全绿 |
| 63 | D | run 29186387692 三平台 fresh Verify 全绿；M7 必须修正 oracle 后重跑 |
| 64 | P | 六个二进制均运行当前 11 项 acceptance，但当前集合并不完整 |
| 65 | P | geometry/font/screenshots 存在；隐藏/遮挡和 Graphviz 错误图未被拒绝 |
| 66 | P | `docs/使用说明.md` 只有摘要，缺逐步图文档案 |
| 67 | M | 无逐项 test/report/screenshot/artifact/CI 索引 |

## 5. 九项 GUI 当前状态

| 能力 | 当前实现 | 剩余产品工作 | 当前判定 |
| --- | --- | --- | --- |
| 1. 建模与解析 | 文档会话、源码权威、revision/fingerprint、加载失败保持旧文档 | 完整表单 CRUD、最近文件入口、复合状态重命名、fresh reload | 部分完成 |
| 2. 模型检查与诊断 | 三来源 DTO、筛选、详情、定位、suggested fix 门禁 | warning/冲突/三来源完整 GUI E2E | 部分完成 |
| 3. 代码生成 | 五模板 service/self-check，Python GUI acceptance | 五内置 + 自定义模板全 GUI 路径 | 部分完成 |
| 4. Python/C/C++ 模板 | build 已编译运行全部生成物 | GUI 选择、覆盖、取消、打开结果与失败恢复 | 部分完成 |
| 5. PlantUML/图片 | PlantUML、PNG/SVG/PDF service 与导出 | 修复 Linux/macOS Graphviz；语义断言，拒绝诊断图 | **阻断** |
| 6. 仿真/动态验证 | 初始化、单步、连续、停止；四正例、mutation service | 真暂停/继续、GUI mutation、UI 术语提示 | 部分完成 |
| 7. 语法高亮 | 编辑器与相关自检已覆盖 | 纳入完整源码编辑 acceptance | 基本完成 |
| 8. 编辑器集成 | 源码/模型/图形/检查/仿真工作区已接入 | 菜单 IA、最近文件、任务全路径和文档 | 部分完成 |
| 9. 公式编辑 | guard/effect/lifecycle 已接 UI，numeric 仅有 service/widget 能力 | numeric 实际入口及四类合法/非法/防抖/整模拒绝 GUI E2E | 部分完成 |

## 6. 剩余缺口与根因

### C0：跨平台图形验收假阳性

- fresh Linux/macOS `03-graph` 是 PlantUML `Cannot find Graphviz` 诊断图，Windows 才是真实状态图。
- `app/acceptance_check.py` 只断言 scene 非空，无法区分模型图和错误图。
- Stage 2 只安装 JRE，没有证明 Graphviz 可用，也没有确认 PlantUML/JAR/Graphviz 的具体运行边界。
- 已选技术决策：所有模型 PlantUML 源统一注入 `!pragma layout smetana`，使用 PlantUML JAR 内置 Smetana，不携带也不安装 Graphviz。本地已在 `GRAPHVIZ_DOT=/definitely/missing` 下真实生成 `Idle -> Running : Start` 状态图；M7 测试必须固化该条件。
- 固定机械 oracle：规范化 PlantUML source/AST 断言预期节点与边语义；同一 source SHA 生成 SVG 并以 XML/text 解析断言 `Root/Idle/Running/Start/Stop` 标签真实出现，拒绝 `Graphviz`、`dot executable`、`cannot find`、`error` 诊断词；PNG/PDF 与同一 source SHA、engine=`smetana`、已通过的 SVG 绑定，并校验 magic、尺寸、非单色和 renderer exit/stdout/stderr。不得从不稳定 SVG path 几何反推边，OCR 和人工看图只作附加证据。

### C1：键盘与几何 acceptance 不能证明真实可用

- 当前 acceptance 大量直接调用 `setCurrentWidget()`、`setText()`、`action.trigger()`，这只能证明 slot 可调用，不能证明菜单可发现、焦点连续或对话框能仅靠键盘完成。
- 当前几何门禁允许隐藏页控件通过，主要检查矩形与窗口相交，没有证明控件在当前页可见、完全包含、无遮挡、表头/当前值可读。
- 每个工作区必须先通过真实用户导航激活，再检查 `isVisibleTo(window)`、有效可见区域、sibling overlap、滚动条、焦点顺序和文本完整性。
- 九类核心能力展开为固定 keyboard item 集合；每项从稳定焦点开始，只用快捷键、Tab、方向键、Enter/Space 和文本输入完成。除 fixture 初始装载外，不得用直接 setter/slot 调用替代用户操作。

### C2：信息架构与可见入口不完整

- 当前菜单是“文件 / 工具 / 编辑 / 视图”，目标是“文件 / 编辑 / 模型 / 检查 / 仿真 / 生成 / 导出 / 视图”。
- 最近文件已有数据维护和测试，没有“文件 -> 最近文件”用户入口。
- 打开最近文件必须复用 dirty replacement 三分支确认，不能旁路文档会话。

### C3：普通仿真状态语义不完整

- 当前只有初始化、单步、连续、重置、停止。
- 取消可保留已完成 cycle，但不能声称是暂停/恢复。
- 需要 cycle 边界协作暂停，同一 session/runtime 接续，且任务记录显示“用户暂停”而不是失败。

### C4：源文本精确编辑缺口

- 复合状态整段 `SourceRef` 与内部引用重叠，当前实现拒绝重命名。
- 必须定位 name token 的精确 range 或扩展 `SourceIndex`；不得用整段替换破坏注释、空白、子状态和迁移文本。

### C5：验收粒度与证据留档不足

- 当前源码编辑只输入末尾换行并 undo/redo；普通仿真只初始化和单步；动态验证没有 mutation；生成只测 Python；导出只测 inspect JSON；没有点击停止/取消。
- `docs/images/` 不存在，没有可逐步照做的完整中文操作档案。
- 没有把 67 项清单映射到测试、报告、截图、artifact 和 CI 的版本化索引。

## 7. 目标与非目标

### 7.1 目标

- 修复图形跨平台真实运行与语义验收。
- 补齐菜单 IA、最近文件、复合状态重命名、仿真暂停/继续。
- 把 acceptance 从 11 个宽泛项目扩展成独立、可诊断的用户工作流项目。
- 建立完整中文手册、真实步骤截图、证据 schema 和逐项索引。
- 在三平台 onedir/onefile 及 fresh runner 中执行完整 self-check 和 acceptance，并人工审阅截图。

### 7.2 非目标

- 不修改 pyfcstm PR #362 的永久 Draft/禁止合并定位。
- 不新增第二套 parser、simulation runtime 或动态验证 DSL。
- 不把动态验证改称形式化验证。
- 不声称 Windows 7 实机验证。
- 不以安装项目 Python/依赖的方式让 fresh verify 失去自包含证明能力。
- 不把“所有 job 绿色”作为独立的完成结论。

## 8. GUI 静态原型

### 8.1 主工作台

```text
┌ 文件 ─ 编辑 ─ 模型 ─ 检查 ─ 仿真 ─ 生成 ─ 导出 ─ 视图 ┐
│ 文档名 | revision | dirty | validation | dependency       │
├────────模型资源────────┬────────中央工作区────────┬────属性────┤
│ 状态/事件/迁移/来源     │ 模型 源码 图形 检查      │ 当前对象    │
│ 最近文件/只读来源       │ 普通仿真 动态验证        │ 来源/公式   │
├────────────────────────┴──────────────────────────┴──────────┤
│ 任务结果：状态 / kind / revision / 摘要 / 操作 / 产物       │
└──────────────────────────────────────────────────────────────┘
```

任务 dock 默认收起；运行中只在稳定底栏显示状态。成功后提供产物入口但不强制展开，只有失败、需要用户决策或用户主动点击时才展开。任务 kind/status 必须转换成用户可理解的中文，不直接把 `graph-render`、`ordinary-*` 和原始 JSON 当作主信息。

### 8.2 最近文件

```text
文件
├─ 打开...
├─ 最近文件
│  ├─ 1. model-a.fcstm       tooltip=默认脱敏路径
│  ├─ 2. model-b.fcstm
│  ├─ ───────────────
│  └─ 清空最近文件
├─ 保存
└─ 统一导出
```

最近文件不存在时显示禁用占位；打开失败时移除失效记录并保留当前文档；tooltip 默认仍脱敏，只有用户开启全局完整路径 opt-in 后才显示完整路径。

### 8.3 普通仿真

```text
状态: uninitialized / ready / running / pause-requested / paused / ended / failed
revision + dependency fingerprint
初始状态 | 初始变量 JSON | 事件 | cycle 上限
[初始化] [单步] [连续运行/继续] [暂停] [重置] [停止]
当前快照
cycle transcript
```

用户可见映射固定为：`uninitialized=未初始化`、`ready=就绪`、`running=运行中`、`pause-requested=正在暂停`、`paused=已暂停`、`ended=已结束`、`failed=失败`、`stale=已失效`、`cancelled=已取消`；报告仍保留稳定英文枚举。

### 8.4 动态验证

```text
动态验证（场景执行与 expected/actual 对比，不是形式化验证）
场景来源 | SHA-256 | model fingerprint | revision
[运行全部] [停止] [导出报告]
case | step | expected | actual | diff | rollback | result
```

### 8.5 其余关键页面原型

```text
模型与公式
┌ 资源类型 ┬ 对象列表 ───────────────┬ 属性/来源 ───────────────┐
│ 状态     │ Root.Idle               │ 名称 [Idle            ] │
│ 变量     │ Root.Running            │ guard [count < 10     ] │
│ 事件     │                         │ 来源 根文件  line 4     │
│ 迁移     │                         │ [定位源码] [校验] [保存] │
└──────────┴─────────────────────────┴────────────────────────┘
empty=选择对象；readonly=原因/打开来源；invalid=字段定位；stale=拒绝提交

检查
┌ 等级[全部] 来源[全部] 搜索[________] [运行检查] ───────────┐
│ code/severity/source/位置/摘要                              │
├──────────────────────────────┬─────────────────────────────┤
│ 诊断列表                      │ 发生了什么 / 影响 / provenance│
│ 当前项高亮                    │ [定位源码] [预览修复]         │
└──────────────────────────────┴─────────────────────────────┘
loading 保留筛选；empty=无诊断；stale=旧 revision；error=恢复动作

图形 ready                         图形 error/stale
┌ engine=smetana r5 [刷新][适应][+][-][重置] ┐  ┌ 当前 r6 渲染失败 ──────┐
│ Root -> Idle -> Running                    │  │ 原因/renderer stderr   │
│                                            │  │ [重试当前版本]         │
└────────────────────────────────────────────┘  │ 上一次有效图 r5 保留   │
                                                └───────────────────────┘

代码生成
┌ 语言[Python▼] 模板[python▼] 自定义路径[________] ─────────┐
│ 输出目录[________________] 覆盖策略[拒绝▼] [生成] [停止]   │
├ 文件 / size / SHA-256 / 入口文件 / revision / fingerprint ┤
│ GUI 不声称本机编译；编译运行证据只来自 Stage 1 build runner │
└────────────────────────────────────────────────────────────┘

统一导出（一次一种格式）
┌ 类型[SVG▼] r5 / provenance 8c21…91fa ─────────────────────┐
│ 目标[____________________] 覆盖[否] [导出] [停止]          │
├ 结果：文件 / size / SHA-256 / schema|magic [打开] [目录]   ┤
└────────────────────────────────────────────────────────────┘

任务底栏/展开态
collapsed:  ✓ 图形完成 r5                         [任务 1]
manual-open/auto-open-failure:
┌ badge=2 过滤[失败▼] 任务列表 ─────┬ 发生了什么/影响/下一步 ┐
│ 失败项（不抢焦点）                │ [重试] [取消] [产物]    │
└───────────────────────────────────┴────────────────────────┘
```

所有工作区均定义 `empty -> loading -> ready -> error/stale/cancelled` 视图；禁用动作旁显示原因。内部英文枚举映射为中文用户状态，完整 SHA/路径默认脱敏，仅显式复制/完整路径 opt-in 后可见。

### 8.6 1280x720 尺寸合同

| 区域 | 默认/最小 logical px | 行为 |
| --- | --- | --- |
| 左资源区 | 默认 220，最小 176，可折叠 | splitter stretch 0 |
| 中央工作区 | 最小 640x360 | splitter stretch 1，始终优先保留 |
| 右属性区 | 默认 240，最小 192，可折叠 | 无选择时收起或展示紧凑空态 |
| 稳定底栏 | 28-36 高 | 不抢焦点，不改变中央布局 |
| 任务 dock 展开 | 160-220 高，且不超过窗口 28% | 默认收起；失败/需决策可展开 |

### 8.7 菜单动作合同

| 菜单 objectName | action objectName / 文案 | 快捷键 | enabled predicate / target widget |
| --- | --- | --- | --- |
| `menu_file` | `action_import_state_machine` / 打开 | `QKeySequence.Open` | always / file dialog |
| `menu_file` | `menu_recent_files` / 最近文件；`action_clear_recent_files` / 清空 | none | entries>0 / document loader |
| `menu_file` | `action_save_state_machine` / 保存 | `QKeySequence.Save` | document && dirty / current document |
| `menu_edit` | `action_undo`、`action_redo`、`action_find` | platform standard | document/editor state / source editor |
| `menu_model` | `action_add_state`、`action_add_lifecycle`、`action_add_transition`、`action_edit_numeric_formula`、`action_locate_source` | none | editable root/current selection / model workspace |
| `menu_inspect` | `action_validate_state_machine` / 运行检查 | `F5` | loadable source / `diagnostics_workspace` |
| `menu_simulation` | `action_show_simulation`、`action_show_dynamic_validation`、`action_stop_task` | `Ctrl/Cmd+5`、`Ctrl/Cmd+6`、`Shift+F5` | valid snapshot or active task / 对应页 |
| `menu_generation` | `action_code_gen` / 代码生成 | `Ctrl/Cmd+Shift+G` | valid snapshot / generation dialog |
| `menu_export` | `action_unified_export` / 统一导出 | `Ctrl/Cmd+Shift+X` | valid snapshot / export dialog |
| `menu_view` | `action_show_model`、`action_show_source`、`action_show_graph`、`action_show_diagnostics` | `Ctrl/Cmd+1..4` | page available / 对应 workspace objectName |
| `menu_view` | `action_graph_gen` / 刷新图形 | none | valid snapshot / graph page；`Ctrl/Cmd+3` 仅供导航 QAction |
| `menu_view` | `action_toggle_task_results`、`action_toggle_model_explorer`、`action_toggle_property_inspector` | 各自唯一 shortcut | widget exists / 对应 dock |

原生文件对话框在生产保持平台体验；acceptance 使用 Qt 非原生 dialog 测试模式并发送真实键盘事件，不直接调用目标 slot。

## 9. 交互状态机原型

### 9.1 文档与最近文件

```text
empty/clean --打开或最近文件--> loading
dirty --打开或最近文件--> replacement-confirm
replacement-confirm
  --Save--> save-current --成功--> loading
  --Discard--> loading
  --Cancel--> 原状态
loading
  --成功--> clean + record-recent
  --失败/取消--> 原 session/dirty/selection/undo/workspace 全部保持
  --再次打开--> supersede-confirm/拒绝，旧 completion 按 session id 丢弃
save-current --失败--> replacement-confirm + 可见错误
recent target missing --> 当前文档保持 + 移除 canonical 去重后的失效项
```

### 9.2 普通仿真

```text
uninitialized --初始化--> ready
ready --单步--> running --cycle boundary--> ready/ended/failed
ready/paused --连续/继续--> running
running --暂停--> pause-requested --cycle boundary--> paused
paused --继续--> running
ready/paused/ended --重置--> ready
running --停止--> cancelling --boundary--> cancelled
任意状态 --revision/fingerprint 变化--> stale
```

暂停保留同一 runtime 和 transcript；停止结束当前显式任务但仍保留边界前已完成 cycle。两者在 UI 文案、TaskRecord status 和 JSON 中必须可区分。

唯一实现合同：一次连续运行是一个终端 TaskRecord segment。用户请求暂停后，worker 在下一个 cycle 边界返回 `TaskStatus.SUCCESS`，结构化 outcome=`paused`，历史摘要为“普通仿真已暂停”；`MainWindow` 继续持有同一 `_simulation_session`，没有线程或 task handle 跨暂停存活。继续操作创建新的显式 TaskRecord segment 并复用该 runtime。应用重启只恢复终端历史，不恢复内存 runtime，仿真页回到“未初始化”。停止则返回 `CANCELLED`，与 paused 明确不同。

运行中 revision/fingerprint 变化时设置 stale token；worker 在下一个 cycle 边界以 `TaskStatus.STALE` 结束 segment，保留已完成 transcript。该结果不得映射成 paused、success 或 cancelled。

### 9.3 原子产物发布

```text
requested -> staging -> validating
staging/validating --cancel--> cancelled + cleanup
staging/validating --failure--> failed + cleanup
validating --stamp invalid--> TaskStatus.STALE + cleanup
validating --stamp valid--> publish-commit-point -> completed

commit point 前：取消、失败或 stale 均清理临时目录，旧目标 manifest 不变。
commit point 后：不再接受取消；UI 必须报告 completed，不能显示已取消。
```

### 9.4 任务 dock 状态机

```text
collapsed --用户打开--> manual-open --用户关闭--> collapsed
collapsed --失败或 requires_user_action=true--> auto-open-failure
auto-open-failure --用户关闭--> collapsed + badge 保留
任意状态 --新成功--> 状态不变，不抢焦点
任意状态 --连续失败--> badge 累加，保留用户当前筛选与选中项
```

## 10. 目标架构与文件边界

| 文件/目录 | 责任 |
| --- | --- |
| `app/widget/main_window.py` | 菜单 IA、最近文件入口、工作区路由、dirty replacement |
| `app/widget/simulation_workspace.py` | 暂停/继续控件与可见状态，不承载 runtime 业务逻辑 |
| `app/widget/dialog_numeric_formula.py`（新增） | 选中变量初值/数值字段的 `FormulaKind.NUMERIC` 实际编辑入口 |
| `app/application/simulation.py` | cycle 边界暂停/取消合同和 session 生命周期 |
| `app/application/graph_render.py`（新增） | Smetana source 规范化、renderer 结果、SVG 语义和 raster/PDF oracle |
| `app/application/tasks.py`、`task_runner.py` | TaskRecord 终态、暂停 segment metadata、历史 schema |
| `app/source/index.py` | 复合状态 name-token 精确来源映射 |
| `app/widget/task_result_dock.py` | dock 状态机、中文状态、badge、过滤与用户动作 |
| `app/widget/graph_workspace.py` | ready/error/stale 展示，错误结果不覆盖上一有效图 |
| `app/acceptance_check.py` | 控件级验收驱动、分项报告、截图和 artifact inventory |
| `app/self_check.py` | pyfcstm 模块闭包、行为项、原生依赖真实逻辑 |
| `scripts/capture_workflow_docs.py` | 从确定 fixture 重放流程并生成文档截图 |
| `docs/完整操作验收手册.md` | 可逐步照做的中文工作流 |
| `docs/images/workflows/` | 版本化的真实 UI 步骤截图 |
| `docs/images/workflows/manifest.json` | 仓库参考图来源与 SHA 清单 |
| `docs/workflow-images.schema.json` | 仓库参考图 manifest schema |
| `docs/验收证据索引.md` | 人可读 67 项证据矩阵 |
| `docs/acceptance-evidence.schema.json` | 机器可读索引 schema |
| `docs/visual-review.schema.json` | 最终 Issue comment 内嵌 visual attestation JSON schema |
| `app/resources/self_check/*.schema.json` | self-check/acceptance report schema |
| `scripts/build_acceptance_evidence.py`（新增） | 每次运行的证据 JSON 与视觉审阅 manifest 生成 |
| `.github/workflows/build.yml` | 三平台两阶段构建与 fresh 黑盒验证 |

任何新抽象必须消除实际重复或匹配现有分层；优先复用 `DocumentSession`、`TaskRunner`、`TaskCenter`、`SimulationService`、原子发布和现有 report schema。

## 11. TDD 实施阶段

### M7.0：冻结失败证据和验收 oracle

- [ ] 保存 Linux/macOS Graphviz 诊断截图作为审计负例，不把它作为跨平台像素基线。
- [ ] 先添加会在当前实现失败的图形语义 acceptance 测试：必须出现预期状态/迁移，拒绝 `Cannot find Graphviz` 等 renderer diagnostics。
- [ ] 添加菜单 IA、最近文件、复合状态重命名、暂停/继续的失败测试。
- [ ] 为每项定义成功 JSON 字段和失败退出码。

### M7.1：修复 PlantUML/Graphviz 跨平台闭包

- [ ] 所有图形渲染统一使用 `!pragma layout smetana`，`GRAPHVIZ_DOT` 指向不存在路径时仍通过真实状态图测试。
- [ ] fresh runner 明确禁止安装 Graphviz、项目 Python、requirements 或编译器，且不调用预装 compiler；只允许 JRE 和显示宿主。
- [ ] PNG/SVG/PDF 均验证 magic、非空、预期状态/迁移语义和无诊断文本。
- [ ] Linux、Windows、macOS source/onedir/onefile 均真实渲染。

### M7.2：菜单 IA 与最近文件

- [ ] 改为“文件 / 编辑 / 模型 / 检查 / 仿真 / 生成 / 导出 / 视图”。
- [ ] 将现有 QAction 归入正确菜单，保留稳定 objectName 和快捷键。
- [ ] 建立“最近文件”动态子菜单、去重、上限、失效项处理和清空。
- [ ] 最近文件重开走 dirty Save/Discard/Cancel 与 `_start_document_load()`。
- [ ] 任务 dock 默认收起，成功任务不抢占工作区；失败/需决策时按对应筛选展开。
- [ ] 统一状态文案、禁用原因、空状态和错误恢复动作。

### M7.3：精确编辑与复合状态重命名

- [ ] 先以嵌套状态、注释、CRLF、Unicode、内部迁移建立 regression fixture。
- [ ] 生成只覆盖 name token 的 `TextEdit`，校验 base revision、URI 与非重叠范围。
- [ ] undo/redo、保存和 fresh reload 后模型事实一致，未修改文本逐字不变。
- [ ] TDD 新增 numeric 数值表达式对话框，从变量初值/数值属性入口打开，接入生产 `FormulaKind.NUMERIC`、防抖和整模提交门禁。

### M7.4：普通仿真暂停与继续

- [ ] 增加 pause signal/button 和显式状态。
- [ ] `SimulationService.run` 在 cycle 边界观察 pause/cancel，暂停返回可继续 session。
- [ ] paused -> continue 使用同一 runtime/cycle/transcript。
- [ ] revision/fingerprint 变化使会话 stale；重置和停止语义独立。
- [ ] 运行中 stamp 变化在下一 cycle 边界以 `STALE` 结束 segment 并保留 transcript。

### M7.5：扩展 acceptance

- [ ] 按第 12 节逐项驱动真实控件、对话框和快捷键。
- [ ] 每项有独立 ID、耗时、status、revision/fingerprint、artifacts 和错误链。
- [ ] 任一项失败仍继续执行可隔离的剩余项，最终非零退出。
- [ ] 每个 case 使用新窗口/新进程，或使用有自检证明的 reset fixture；前项失败不得污染后项。
- [ ] 九类核心能力展开为固定 keyboard item 集合，从稳定焦点开始只以真实按键事件完成；图形拖动等鼠标专属能力另设 item，不得用 setter 或直接 slot 调用冒充用户路径。
- [ ] 每个工作区激活后验证真实可见、完整包含、无遮挡、滚动策略、表头/当前值和焦点顺序。
- [ ] empty/loading/error/stale/cancelled 状态分别有断言和截图。

### M7.6：完整操作文档与截图

- [ ] 新增 `docs/完整操作验收手册.md`。
- [ ] 新增 `scripts/capture_workflow_docs.py` 和 `docs/images/workflows/`。
- [ ] 为第 12 节每个用户可见 acceptance family 建立可照做流程；八个核心目录只是最低层级，必须继续覆盖最近文件、dirty 三分支、七类模型 CRUD、四种公式、imported 来源、取消和 stale。
- [ ] 每个流程目录按适用分支保留 `00-before/01-action/02-running/03-result/04-failure-recovery`，不是每类只留一张结果图。
- [ ] 每个流程包含前置条件、精确操作、预期状态、产物/schema、失败恢复和自动化证据。
- [ ] 手册维护“GUI acceptance ID -> 文档章节 -> 步骤图片 -> 自动化证据”覆盖矩阵，任何用户可见 item 缺章节即失败。
- [ ] 至少两轮独立盲操作复现：审阅者只看手册、使用干净设置完成流程，记录卡点、歧义、错误截图和修订结果，直至 `C=0/I=0/READY`。

### M7.7：证据索引与 CI 收口

- [ ] 生成 `docs/验收证据索引.md` 和 schema 化 JSON。
- [ ] 两阶段三平台 workflow 上传全部报告、截图、logs、manifest 和索引。
- [ ] 下载所有 artifact，逐项核对 JSON schema、文件 size/SHA、图形语义和截图。
- [ ] 人工检查 fresh Linux/Windows/macOS 代表截图并写持久化审计结论。

## 12. acceptance 扩展矩阵

下表是 item family。实现时每个逗号分隔 case 都必须展开为稳定参数化 ID，例如 `model.state.add`、`generation.c-poll`、`export.svg`、`cancel.graph`；每个 ID 单独报告、截图和 inventory，任一 ID 失败后继续执行其他隔离 ID。

| 组 | 独立项目 | 必须真实执行的逻辑 |
| --- | --- | --- |
| 文档 | `document.open`、`document.recent-reopen`、`document.cancel-load`、`document.failed-load-preserves-session` | QAction/QMenu、对话框、异步完成、文档事实 |
| dirty | close/open 时 Save、Discard、Cancel | 三分支均走 GUI，校验文件和当前 session |
| 源码 | 编辑、undo、redo、保存、fresh reload | 键盘输入与 QAction，不是直接改 model |
| 模型表单 | `model.{state,variable,event,transition,guard,effect,lifecycle}.{add,edit,delete}` | 表单控件、校验、SourceRef、保存重载 |
| imported | 只读和打开来源 | 控件禁用、canonical URI、来源导航 |
| 重命名 | 简单状态、复合状态、Unicode/CRLF | name-token 精确编辑和未改文本保持 |
| 诊断 | syntax、assembly、inspect，含 warning/冲突 | 筛选、搜索、详情、定位、suggested fix |
| 公式 | `formula.{guard,numeric,effect,lifecycle}.{valid,invalid}` + `formula.stale` | debounce、精确位置、stale 丢弃、整模重验 |
| 图形 | 刷新、缩放、拖动、适应、重置、选择联动 | 真实状态图，拒绝 renderer error 图 |
| 图形导出 | `graph.export.{plantuml,png,svg,pdf}` | source SHA、Smetana engine、magic、语义、原子发布 |
| 普通仿真 | 初始化、单步、连续、暂停、继续、重置、停止 | 同一 runtime、cycle 边界、transcript |
| 动态验证 | 四正例、mutation 反例、恢复复跑 | expected/actual、rollback、fixture SHA |
| 术语 | 动态验证非形式化验证 | UI 可见文案与文档 |
| 生成 | `generation.{python,c,c-poll,cpp,cpp-poll,custom}` | GUI 选择、非空清单、覆盖确认、取消、恢复 |
| 导出 | `export.{dsl,word,excel,plantuml,png,svg,pdf,inspect-json,dynamic-json}` | 九类逐项 magic/schema 和原子发布 |
| 任务中心 | 过滤、复制、导出、清空已完成、清空全部、重试、取消、产物入口 | 真实 TaskRecord 和持久化恢复 |
| 任务注册 | `tasks.registry.{load,inspect,graph,simulation,dynamic,generation,export}`、`tasks.transient.{document-validation,formula-validation}` | 前者逐类进入历史；后者不污染历史 |
| stale | 图形、仿真、动态验证、生成、导出 | revision/fingerprint 变化后拒绝旧发布 |
| 取消 | `cancel.{load,simulation,dynamic,graph,generation,export}` | 边界、部分证据、临时目录和旧目标 |
| 键盘旅程 | `keyboard.{model,inspect,generation,templates,graph,simulation,syntax,workspace}` + `keyboard.formula.{guard,effect,lifecycle,numeric}` | 报告起始/逐步/最终 focus objectName、跨平台标准键序列和最终事实；鼠标拖动画布另列 |
| 几何 | 当前激活工作区 | `isVisibleTo`、完整包含、sibling overlap、滚动条、表头和当前值 |
| 可达性 | 字体 family/point size、accessible name、焦点顺序、固定视口/DPI | 1280x720 与 1920x1080，scale 1/1.5/2 |
| 视觉 | 三平台代表截图 | 人工检查文字、布局、图形内容和错误图 |

### 12.1 九类能力、十二个稳定 keyboard item 的机械合同

平台标准 modifier 使用 `QKeySequence` 解析：Windows/Linux 为 Ctrl，macOS 为 Command。菜单 mnemonic 不作为跨平台门禁；一级工作区入口使用稳定 QAction shortcut。每一步报告 `key_sequence`、`focus_before`、`focus_after` 和最终业务事实。

| ID | 起始焦点 | 关键序列 | 最终事实 |
| --- | --- | --- | --- |
| `keyboard.model` | `AppMainWindow` | 模型页 shortcut -> Tab/方向键选对象 -> Enter 编辑 -> Tab -> Enter 提交 | source revision 增加且选中对象事实改变 |
| `keyboard.inspect` | `AppMainWindow` | F5 -> 检查页 shortcut -> Tab 到筛选/列表 -> 方向键 -> Enter 定位 | 当前诊断详情和 source cursor 匹配 |
| `keyboard.generation` | `AppMainWindow` | 生成 shortcut -> Tab/方向键选 Python -> 输入目标 -> Enter | 生成任务和非空入口文件出现 |
| `keyboard.templates` | 生成对话框语言框 | 方向键依次选择五内置模板 -> Space/Enter | 五个稳定 template ID 均可达 |
| `keyboard.graph` | `AppMainWindow` | 图形页 shortcut -> Tab 到刷新 -> Space -> Tab 到适应/缩放/重置 | Smetana 真实图 ready，按钮均可达 |
| `keyboard.simulation` | `AppMainWindow` | 仿真页 shortcut -> Tab 输入变量/事件 -> 初始化 -> 单步 -> 连续 -> 暂停 -> 继续 | 同一 runtime cycle 连续且 paused segment 可见 |
| `keyboard.syntax` | source editor | 源码页 shortcut -> 输入 -> Undo -> Redo -> Save | 源码、revision、dirty 和磁盘事实一致 |
| `keyboard.workspace` | `AppMainWindow` | 六个 workspace QAction shortcut（`Ctrl/Cmd+1..6`）逐一执行 | 每页成为 current、可见且焦点落在首要控件 |
| `keyboard.formula.guard` | 迁移对话框 guard field | 输入合法/非法 logical 表达式 -> debounce -> Enter | logical 反馈与提交门禁匹配 |
| `keyboard.formula.effect` | 迁移对话框 effect field | 输入合法/非法 assignment -> debounce -> Enter | effect 反馈与整模门禁匹配 |
| `keyboard.formula.lifecycle` | 生命周期对话框 action field | 输入合法/非法 assignment -> debounce -> Enter | lifecycle 反馈与整模门禁匹配 |
| `keyboard.formula.numeric` | 数值表达式对话框 numeric field | 输入合法/非法 numeric 表达式 -> debounce -> Enter | numeric 反馈与提交门禁匹配 |

文件选择使用 Qt 非原生 dialog 测试模式，从 filename edit 起步键入路径并按 Enter；不 monkeypatch 返回值、不直接调用 load slot。鼠标专属 `graph.drag` 通过真实 press/move/release 验证 transform/scroll 事实。

### 12.2 几何门禁算法与豁免

- 只检查 `widget.isVisibleTo(window)` 且属于当前激活 tab/workspace 的控件。
- 将控件有效 rect 统一 `mapTo(window, ...)`，要求窗口 content rect `contains()`，不能只用 `intersects()`。
- 对同一可见父层级的交互控件做交集面积检查；文本/按钮可见内容使用 font metrics 和 viewport rect 检查。
- 合法豁免仅限：splitter handle、dock title bar、tab bar 与 page frame、scroll area viewport/scrollbar、combo popup、tooltip、modal overlay；豁免以 object/class 白名单记录在报告中。
- 每页记录滚动条 policy/visible 状态、表头 rect、当前值 rect、焦点链 objectName；未知重叠不自动忽略。

### 12.3 self-check 的不可弱化项

- pyfcstm 全部打包模块闭包单独计数。
- 每个上游核心功能单独命名并执行生产逻辑。
- Z3 至少五条真实场景：整数 SAT/model、UNSAT、实数、位向量、Optimize，并断言求解结果。
- PlantUML 必须真实调用 Java/JAR 并验证输出语义，不能只验证版本或文件存在。
- Python 生成物必须真实运行；C、C poll、C++、C++ poll 必须配置、编译、运行。
- `SimulationRuntime` 必须执行多个 cycle；动态验证必须四正例、mutation 反例、恢复复跑和 fixture SHA。
- 单项抛出 `BaseException` 后继续其他隔离项，最终报告完整且退出非零。

## 13. 文档与 `docs/images` 留档合同

仓库内参考图目录固定为（每个流程实际包含分步图片）：

```text
docs/
├─ 完整操作验收手册.md
├─ 验收证据索引.md
├─ acceptance-evidence.schema.json
├─ workflow-images.schema.json
├─ visual-review.schema.json
└─ images/
   └─ workflows/
      ├─ manifest.json
      ├─ 01-open-document/
      ├─ 02-diagnostics-navigation/
      ├─ 03-real-state-graph/
      ├─ 04-ordinary-simulation/
      ├─ 05-dynamic-validation/
      ├─ 06-five-template-generation/
      ├─ 07-unified-export/
      └─ 08-task-results/
```

每张仓库参考图由 `docs/images/workflows/manifest.json` 记录来源代码 tree SHA、平台、viewport、scale、应用字体、acceptance item 和 SHA-256，并通过 `docs/workflow-images.schema.json`。它用于操作文档，不冒充 final fresh onefile 证据。

证据分为三层：

1. `docs/验收证据索引.md`：版本库中的 67 项规范映射和稳定 test/item ID；
2. `acceptance-evidence.json`：每次 CI 由脚本生成，记录 run commit、job、artifact、报告与截图 SHA；
3. 最终 Issue comment 内嵌 visual attestation JSON/Markdown：下载 final run evidence 后生成，JSON 通过 `docs/visual-review.schema.json`，字段固定为 reviewer、日期、commit、run id、平台、artifact、viewport、scale、截图 SHA、逐张 verdict、findings 和最终 READY。该 comment 是人工审阅的唯一权威载体，CI artifact 不声称包含事后审阅结果。

发布协议用于消除 commit/run 循环：候选代码 run 生成参考截图；审阅后提交 `docs/images`、其来源代码 tree SHA 和文档；最终 docs commit 再跑完整 CI。最终 Issue comment 内嵌完整 attestation（run/commit、12 artifact digest、报告计数、逐平台 visual verdict 与最终 READY），artifact 链接仅作补充，不能让会过期链接成为唯一证据。最终 run 是关闭依据，仓库图片是操作文档依据，两者不混称。

### 13.1 使用指引迭代门禁

使用指引本身是验收产品，不是实现完成后的附属说明。每轮按以下闭环执行并把结果写入手册末尾的审阅记录：

```text
从 GUI acceptance 稳定 ID 生成覆盖矩阵
  -> 用干净设置仅按文档逐步操作
  -> 对照真实界面/产物/schema/失败恢复
  -> 打开并检查每张步骤截图
  -> 记录无法执行、歧义、过期图片和缺失分支
  -> 修订文档或产品
  -> 重新盲操作，直至 C=0 / I=0 / READY
```

审阅记录至少包含 reviewer、日期、commit、环境、覆盖 item、失败步骤、修改位置和 verdict。禁止作者仅凭熟悉实现自行判定“可无脑照办”。

## 14. 两阶段三平台 CI 合同

### Stage 1：各目标系统原生构建

- Linux x86_64、Windows x86_64、macOS x86_64 各自构建 onedir 与 onefile。
- 在 build runner 运行完整 self-check、完整 acceptance 和生成物 runtime/compile/run。
- 生成 artifact manifest，记录顶层产物与内部文件的 size/SHA-256。
- 分别上传二进制和 evidence；`if-no-files-found: error`。

### Stage 2：fresh runner 黑盒验证

- 新 runner 不 checkout 项目源码，不 setup 项目 Python，不安装 requirements、编译器或 Graphviz；不调用任何预装 compiler，fresh success 不依赖 compiler executable。
- runtime allowlist 仅为 JRE 与显示宿主。Linux 至少一轮 `xvfb-run` + xcb；Windows 使用默认 platform；macOS 使用 cocoa。offscreen 只可作为附加门禁，文档/视觉审阅截图不得来自 offscreen。
- 下载 Stage 1 产物后执行 `--self-check` 与 `--acceptance-check`。
- onedir/onefile 都执行；固定 viewport 与 scale cross product。
- 上传 JSON、日志、截图、导出结果、manifest 和证据索引。

### 必须人工盯住的产物

- 六个 matrix job 全部到终态，不能只看 workflow summary。
- self-check item 数与名称集合一致；acceptance item 数与名称集合一致。
- 每份报告 schema/version、revision/fingerprint、fixture SHA 完整。
- 所有 manifest 条目 size/SHA 复算一致。
- Linux/Windows/macOS fresh onefile 的图形、仿真、生成、导出代表截图逐张打开检查。
- 任何 skipped、renderer diagnostic、missing artifact 或 stale publication 都判失败。
- 校验 ELF/PE/Mach-O magic、x86_64 架构和 Windows CPython 3.7 x64 基线；记录 runner 预装工具 inventory，但编译验证只发生在 Stage 1。
- 修改 application service 的分支覆盖率不低于 90%；禁止 broad skip/xfail 隐藏失败。

## 15. 风险与回滚

| 风险 | 缓解/回滚 |
| --- | --- |
| Smetana 对复杂状态图支持差异 | 固定代表性嵌套/迁移 fixture；SVG 语义 oracle；失败则阻断而非回退外部 Graphviz |
| 菜单重排破坏 objectName/快捷键 | QAction 身份不变，仅移动归属；键盘 E2E 锁定 |
| name-token 映射破坏源文本 | 先做 CRLF/Unicode/嵌套 regression；TextEdit 仅覆盖 token |
| 暂停引入线程竞争 | 仅在 cycle 边界协作；session id/revision/fingerprint 门禁 |
| acceptance 运行时间膨胀 | 分项复用启动会话但隔离 fixture；报告仍逐项；不得删减强证据 |
| 截图在平台字体差异下漂移 | 固定内置字体和 point size；几何断言与人工检查并用 |
| 文档截图过期 | 脚本化重放；证据索引记录 commit/SHA；CI 检测缺图和孤儿引用 |

## 16. 最终关闭清单

### 已由当前基线直接证明

- [x] `AGENTS.md -> CLAUDE.md`，维护纪律集中且可持续加厚。
- [x] source text 权威、revision/dependency fingerprint 和 stale publication 门禁已建立。
- [x] 114 module closure + 65 behavior = 179 项 self-check。
- [x] Z3 至少五条真实 solve/optimize 场景已分项执行。
- [x] 四个动态验证正例、mutation 反例、恢复复跑和 fixture SHA 已进入产品自检。
- [x] Python 生成物运行及四套 C/C++ 生成物编译运行已进入 build runner。
- [x] 三平台 onedir/onefile 构建与 fresh runner workflow 已建立。
- [x] 当前 12 个 artifacts 均有 SHA-256，1170 个内部 manifest 条目已复算。
- [x] 内置 Noto CJK 字体与固定 metrics 已在 fresh 截图验证。

### M7 必须完成

- [ ] 图形 acceptance 不再以 scene 非空为 oracle，Linux/macOS/Windows 都显示真实状态图。
- [ ] fresh runtime allowlist 仅含 JRE/显示宿主，明确不安装 Graphviz、项目 Python、requirements、编译器且不调用预装 compiler。
- [ ] 菜单 IA 与 `DESIGN.md` 一致，最近文件成为可见、可操作入口。
- [ ] 九类能力的十二个稳定 keyboard item 可从规定焦点仅通过真实键盘输入完成。
- [ ] 几何门禁只检查当前激活工作区并拒绝隐藏、裁切、遮挡和不可读内容。
- [ ] 任务 dock 不再在每个显式任务开始时强制展开，成功结果不打断主工作区。
- [ ] 用户可见状态统一，禁用控件有原因，关键页具备 empty/loading/error/stale/cancelled 状态。
- [ ] 复合状态可精确重命名，CRLF/Unicode/嵌套文本保持合同通过。
- [ ] 普通仿真支持真实暂停和继续同一 runtime。
- [ ] UI 明确动态验证不是形式化验证。
- [ ] 完整模型 CRUD、公式、诊断、仿真、动态验证、生成、导出、任务中心均有独立 GUI acceptance item。
- [ ] 六类任务取消及 stale publication 有控件级黑盒证据。
- [ ] 五内置模板和自定义模板均从 GUI 生成并验证。
- [ ] 九类统一导出均从 GUI 执行并校验 magic/schema。
- [ ] `docs/完整操作验收手册.md` 覆盖每个用户可见 acceptance family，至少八个核心目录含全部适用步骤和失败分支图片。
- [ ] 使用指引 coverage matrix 无缺项，至少两轮独立盲操作复现达到 `C=0/I=0/READY`。
- [ ] `docs/验收证据索引.md` 与机器可读 schema/JSON 完成。
- [ ] 本地 focused、全量 pytest、compileall、pip check、XML/YAML、diff check 通过；不可用工具明确记录。
- [ ] 三平台 Package + fresh Verify 全绿，全部 evidence 已下载复算。
- [ ] fresh Linux/Windows/macOS 代表截图已人工检查并持久化结论。
- [ ] 最终 Issue comment 内嵌 visual attestation JSON 通过 schema，逐图 verdict 与最终 READY 完整。
- [ ] 独立架构审阅和验收审阅达到 `C=0`、`I=0`、`READY`。
- [ ] 本 Issue 每一开放项回填强证据后勾选并关闭。

## 17. READY 判定

只有同时满足以下条件才允许将本 Issue 标记完成：

```text
READY =
  implementation_complete
  AND local_tests_green
  AND self_check_complete
  AND gui_acceptance_complete
  AND package_matrix_green
  AND fresh_verify_matrix_green
  AND all_reports_schema_valid
  AND all_artifact_sha_verified
  AND fresh_cross_platform_screenshots_reviewed
  AND fresh_runtime_allowlist_verified
  AND visual_review_manifest_valid
  AND docs_and_evidence_index_complete
  AND documentation_acceptance_coverage_complete
  AND documentation_blind_walkthrough_ready
  AND reviewer_critical_count == 0
  AND reviewer_important_count == 0
```

在此之前，即使 workflow 显示绿色，也只能报告当前阶段结果，不能宣称产品已验收完成。
