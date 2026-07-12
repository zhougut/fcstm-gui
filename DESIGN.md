# GUI 设计合同

## Source of truth

- 状态：Active
- 最后更新：2026-07-12
- 主要产品界面：主工作台、源码编辑、模型属性、状态图、结构化检查、普通仿真、动态验证、任务与结果、代码生成、统一导出。
- 权威需求：[zhougut/fcstm-gui#1](https://github.com/zhougut/fcstm-gui/issues/1)。
- 上游能力合同：[HansBug/pyfcstm#360](https://github.com/HansBug/pyfcstm/issues/360) 与 [PR #362](https://github.com/HansBug/pyfcstm/pull/362)。
- 已审阅本地证据：`app/ui/*.ui`、`app/widget/**`、`app/application/**`、`app/model/**`、`docs/使用说明.md`、`.github/workflows/build.yml`。
- 当前没有既有截图基线、品牌素材或设计 token；后续截图与交互留档统一放在 `docs/images/`，操作说明统一放在 `docs/`。

## Brand

- 个性：安静、精确、工程化、可信赖；强调模型事实、revision、诊断和任务结果。
- 信任信号：明确的当前文件、dirty 状态、source revision、验证状态、依赖状态、任务状态和产物校验结果。
- 避免：营销式大标题、装饰性卡片、渐变背景、单一蓝紫色调、隐藏关键状态、仅靠颜色表达错误、用弹窗替代持续可查看的结果。

## Product goals

- 目标：用户可以在同一桌面工作台完成模型加载、编辑、检查、图形、仿真、动态验证、生成和导出。
- 目标：所有模型相关操作都绑定当前 `source_revision` 与依赖指纹，不显示或执行过期结果。
- 目标：高频工作流尽量在主窗口内完成，长任务进入统一任务与结果面板。
- 目标：错误可定位、可恢复；取消不产生半事务状态或截断产物。
- 非目标：SMT/BMC/拓扑/SysDeSim GUI；动态验证不得宣传为形式化验证。
- 成功信号：issue #1 的九项 GUI E2E、三平台 build/fresh verify、固定视口/DPI 几何门禁和冻结产物 acceptance-check 全部通过。

## Personas and jobs

- 主要用户：编写和维护 FCSTM 状态机的工程师、模型审阅者、生成代码和交付验证人员。
- 用户任务：从现有 `.fcstm` 加载并定位问题；通过表单或源码做精确编辑；验证行为；生成代码和图；导出可复查产物。
- 使用环境：Windows、Ubuntu 和 macOS 桌面；可能无网络；可能通过远程桌面或 CI 虚拟显示器运行。
- 使用特点：长时间重复操作、需要快速扫描、经常比较 expected/actual、需要保留失败证据。

## Information architecture

- 顶部菜单：文件、编辑、模型、检查、仿真、生成、导出、视图。
- 顶部状态区：文档名、dirty 标记、source revision、验证状态、依赖状态。
- 左侧可调分栏：模型资源管理器，展示状态、事件、迁移和来源归属；imported/generated 项有只读标识。
- 中央工作区标签：属性、源码、状态图、检查、普通仿真、动态验证。
- 右侧可调分栏：当前对象属性检查器与公式编辑入口。
- 底部 dock：任务与结果，支持状态筛选、搜索、复制、导出、重试、取消和产物入口。
- 对话框：代码生成、统一导出、覆盖确认、TextEdit 预览；对话框不得承载长期结果浏览。

## Design principles

1. 源码事实优先：UI 是 `source_text` 的可重新派生投影，任何表单提交都显示来源并走 `TextEdit` 与整模重验。
2. 状态持续可见：revision、验证、任务和错误状态不得只用瞬时消息框表达。
3. 错误靠近操作：字段错误显示在字段附近，模型错误进入诊断页，任务错误进入结果面板。
4. 默认保守提交：过期、重叠、imported、依赖变化或整模失败一律拒绝写入。
5. 高频操作紧凑：避免多层弹窗；选择对象后，属性、来源、诊断和图形联动。
6. 动态验证与普通仿真分离：前者显示 expected/actual，后者只显示实际运行状态。
- 取舍：优先保证证据、可恢复性和跨平台一致性，其次才是动画和视觉装饰。

## Visual language

- 色彩：中性浅灰/白工作面；正文深灰；成功使用绿色，警告使用琥珀色，错误使用红色，运行中使用蓝色。每种状态同时带文本或图标。
- 深色主题：沿用 Qt/qtmodern 能力，但状态色语义与对比度保持一致；不得只为深色主题重新定义业务颜色。
- 字体：使用平台 UI 字体；源码、表达式、路径和 JSON 使用等宽字体。字号固定，不随窗口宽度缩放。
- 间距：4/8/12/16 px 节奏；工具栏紧凑，中心工作区保留扫描空间。
- 形状：控件圆角不超过 6 px；dock、分栏和页面不做浮动卡片；边框用于表达工作区边界。
- 图标：优先 QtAwesome 中的常见图标；保存、撤销、重做、刷新、缩放、适应、复制、清空、运行、暂停和停止使用图标按钮并提供 tooltip。
- 动效：仅使用短暂状态过渡和进度反馈；禁止影响尺寸的 hover 动画。

## Components

- 复用：`QMainWindow`、`QDockWidget`、`QSplitter`、`QTabWidget`、`QTreeWidget`、`QTableView/QTableWidget`、`QPlainTextEdit/QsciScintilla`、现有状态树和表单对话框。
- 新增或调整：文档状态栏、事件表、属性检查器、诊断面板、公式编辑器、普通仿真工作区、动态验证工作区、任务结果 dock、代码生成对话框、统一导出对话框。
- 状态变体：empty、loading、ready、dirty、pending、valid、valid-with-warnings、invalid-syntax、invalid-model、stale-dependency、disabled、cancel-requested、cancelled、failed。
- 只读对象：imported/generated 行显示来源图标和物理 URI；编辑控件禁用，但“打开来源”保持可用。
- 事件组件：随当前状态显示名称、展示名、来源和只读状态；根文件事件支持增改删，操作必须绑定 event `SourceRef`。
- 诊断行：severity、source kind、code、message、位置和来源；缺失字段显示为空，不伪造行列。
- 任务行：时间、kind、status、summary、revision、actions；进行中任务尺寸稳定，不因进度文字改变布局。
- ownership：`.ui` 管结构和控件命名；`widget/` 管交互；`application/` 管业务服务；业务 DTO 放 `model/`。

### 事件编辑合同

- 事件行必须显示 owner state path、event name、展示名、scope、物理来源和 editable 状态；稳定身份使用 event `SourceRef.stable_key`，不能只用显示名。
- 选择事件后可查看声明位置、引用计数和所有迁移引用；双击引用定位到对应迁移或源码范围。
- 根文件事件新增使用当前 owner 的 event insertion anchor；修改和删除使用 declaration `SourceRef`。
- rename 必须在一个候选事务中同时编辑事件声明和根文件内所有可编辑迁移引用；任一引用 imported/generated、过期或区间冲突时阻止表单 rename，并提供“在源码中打开”。
- delete 必须先展示引用列表；存在引用时默认阻止。用户明确选择“同时删除引用迁移”后，才能以多 `TextEdit` 原子事务删除声明和引用迁移。
- 所有事件事务必须预览 before/after、通过完整 loader + inspect、提交后保存重载一致；失败时 `DocumentSession` 完全不变。

### TaskCenter 与历史

- 任务状态机：`QUEUED -> RUNNING -> SUCCESS | FAILED | STALE`；排队取消为 `QUEUED -> CANCELLED`；运行中取消为 `RUNNING -> CANCEL_REQUESTED -> CANCELLED | STALE`。
- 每条 `TaskRecord` 至少包含 task id、kind、session id、source revision、dependency fingerprints、开始/结束时间、状态、摘要、结构化 messages、artifacts、retry descriptor 和可安全展示的异常链。
- 只有用户显式发起的打开、检查、图形、生成、仿真、动态验证和导出进入持久历史；字段防抖校验不持久化。
- 历史存储在 `QStandardPaths.AppDataLocation`，使用版本化 JSON schema；启动恢复时损坏文件移入隔离文件并生成可见 warning，不得阻止应用启动。
- 淘汰同时受 30 天、1000 条和 10 MiB 限制，任一达到即从最旧记录开始删除。
- 提供“清空当前筛选”和“清空全部持久历史”两个独立命令，均二次确认并有撤销范围说明。
- 内存任务可保存 raw path；默认 UI 复制、日志导出和持久历史将 home、temp、workspace 替换为 `<HOME>`、`<TEMP>`、`<WORKSPACE>`，异常链同样脱敏。
- 只有显式 opt-in 才持久化完整路径；恢复后只有脱敏路径的 artifact 禁用“打开文件/目录”，但保留查看、复制和导出日志。

### 仿真与动态验证隔离

- 普通仿真和动态验证使用独立 tab、view model、task kind、状态机和 `SimulationRuntime` 实例；不得共享可变 runtime/session/transcript。
- 二者只共享 application 层的生产 runtime adapter 和 cycle 语义；普通仿真输出 transcript，动态验证输出版本化 `ValidationReport`。
- 普通仿真生命周期：未初始化、ready、running、paused、cancel-requested、cancelled、ended、failed；单步和连续运行都只在完整 cycle 后发布状态。
- 动态验证生命周期：draft、schema-validating、initializing、running-step、passed、mismatch、expected-exception-passed、failed、cancel-requested、cancelled、report-ready。
- `ValidationReport` 必须记录模型 revision/依赖指纹、场景 hash、每步输入、expected/actual 状态/变量/ended/exception/cause、diff 和 rollback 证据。
- 取消只在 cycle/step 边界生效；已完成 transcript/report 保留，正在执行的 runtime 事务不得被半中断。普通仿真取消不能生成验证结论，动态验证取消不能标记 passed/failed。

## Accessibility

- 目标：键盘可完成九项核心工作流；颜色对比按 WCAG AA 作为机械检查目标。
- Tab 顺序遵循菜单/资源树/中心工作区/属性/结果面板；焦点必须可见。
- 图标按钮全部提供 accessible name 和 tooltip；表格列有明确标题。
- 错误不只靠颜色，必须包含图标、状态文本和详情。
- 诊断定位后将焦点移到源码范围；返回诊断列表时保持原选择。
- 快捷键使用平台常见约定：保存、撤销、重做、查找、运行/停止；菜单显示快捷键。
- 减少动画：不依赖动画理解状态；进度条之外不使用持续运动。

### 可执行键盘门禁

- acceptance-check 以 objectName 查找核心控件，不依赖屏幕坐标。
- 九项工作流各自至少执行一次纯键盘路径：打开、模型编辑、检查定位、图形刷新、普通仿真、动态验证、生成、统一导出、任务结果操作。
- 每个图标按钮断言 `accessibleName` 和 tooltip 非空；每个表格断言列标题非空。
- 诊断定位断言焦点进入源码编辑器并选中非空范围；关闭详情后焦点返回原诊断行。
- imported/generated 禁用编辑时，断言焦点仍可到达“打开来源”。

## Responsive behavior

- 支持桌面最小视口 1280x720，标准视口 1920x1080。
- 支持 100%、150%、200% DPI；控件使用布局和 minimum size，不使用依赖像素绝对位置的业务控件。
- 1280x720：左/右分栏可折叠，底部 dock 默认约占高度 28%，中心标签保持可操作。
- 1920x1080：左侧资源树、中央工作区、右侧属性检查器同时可见。
- 文本过长：路径和消息允许中间/尾部省略，tooltip 显示完整内容；按钮文字不得截断。
- 触摸不是主要目标；所有 hover 信息必须有键盘或点击等价入口。

### 几何与 DPI 验收矩阵

- viewport 尺寸统一指 Qt logical pixels；DPI scale 使用 `QT_SCALE_FACTOR` 或目标平台等价设置。
- 三个平台都执行 1280x720 与 1920x1080 两个 viewport，并分别执行 100%、150%、200%，共 6 个组合/平台。
- 每个组合至少检查主工作台、诊断、普通仿真、动态验证、生成和统一导出六个页面。
- 机械通过条件：可见控件矩形位于窗口可用区域；同一布局层级控件不相交；按钮文本不截断；表头和当前值可见；水平/垂直滚动仅出现在设计允许的容器；主要命令可通过键盘到达并触发。
- 截图与 JSON 几何报告成对保存；截图仅用于人工复核，JSON 断言决定 CI 通过与否。

## Interaction states

- Loading：中心显示阶段文本，相关编辑和模型消费者禁用；取消按钮明确对应当前逻辑 operation。
- Empty：提供打开/新建两个主要动作，不显示虚假的模型或诊断。
- Error：保留当前可恢复工作；加载 I/O/依赖失败不替换旧文档，语法/模型失败可作为候选源码进入编辑器。
- Success：结果进入任务面板并保留产物入口；不使用阻塞式“成功”弹窗作为唯一反馈。
- Disabled：显示原因，例如“当前 revision 尚未通过完整校验”或“对象来自 import”。
- Stale：结果仍可查看但不可应用；显示其 revision 与当前 revision。
- Cancelled：保留已完成步骤、transcript 或日志；不得显示为成功或失败。
- Offline：所有核心能力使用打包资源，不允许网络回退。

## Content voice

- 语气：简短、事实化、可执行；界面正文统一中文，保留 FCSTM、revision、PlantUML 等技术名词。
- 使用“检查”表示 inspect/诊断，“普通仿真”表示交互式 runtime，“动态验证”表示场景 expected/actual 对比。
- 禁止把动态验证称为形式化验证、模型检测、SMT 或 BMC。
- 错误文本格式：发生了什么、影响什么、下一步可做什么；详情区提供原始异常和 cause。
- 路径默认脱敏；只有用户明确选择时展示或持久化完整路径。

## Implementation constraints

- 框架：Python 3.7、PyQt5 5.15、QScintilla、QtAwesome、qtmodern。
- 后端固定：`pyfcstm@f142a656df43e0b80ed6b7ac63b0696345325646`。
- UI 线程：Qt 控件只在主线程更新；解析、检查、渲染、生成、仿真和导出通过 application service/TaskRunner。
- 数据合同：`source_text` 唯一可保存事实；模型消费者必须调用 `require_current_valid_snapshot()`。
- 编辑合同：表单只能提交带当前 revision 和 root-owned `SourceRef`/anchor 的 `TextEdit`。
- 取消合同：Python 调用协作取消；子进程按进程组终止；生成/导出使用临时目录和原子发布。
- 兼容性：Windows x86_64、Ubuntu 22.04 x86_64、macOS Intel；Windows 名称不得写 `win7` 或声称 Windows 7 实机通过。
- 自检：源码态、build runner 的 onedir/onefile、三个 fresh runner 均执行完整 self-check 与 acceptance-check。
- 截图：保存 1280x720、1920x1080 和 100/150/200% DPI 关键页面；截图不是唯一门禁，必须配套几何、可见性、可达性和文本未截断断言。
- 留档：每个完整流程在 `docs/` 有逐步操作、预期状态、失败恢复和产物说明；对应图片放 `docs/images/`。
- token 所有权：首轮不新增独立 design-token 框架；颜色、间距和控件公共样式集中在 `app/widget/style.py`，`.ui` 只保留结构和必要 minimum size。
- 性能预算：主线程单次同步工作目标不超过 50 ms；超过 100 ms 的生产调用必须进入后台任务；用户操作后 100 ms 内显示 loading/running 反馈；连续仿真每个 cycle 完成后最多合并一次 UI 刷新。

## Open questions

- [ ] 深色主题强制范围 / owner: M6 视觉验收 / impact: 截图矩阵翻倍 / 默认决策：首轮只要求浅色主题，深色运行 smoke 不做完整截图矩阵。
- [ ] macOS 快捷键文案 / owner: M2 工作台 / impact: 菜单本地化 / 默认决策：使用 Qt 平台映射，不维护单独文案表。
- [ ] imported“打开来源”载体 / owner: M2 模型资源管理器 / impact: 导航 E2E / 默认决策：在中央源码 tab 打开只读文档，并显示物理 URI。
- [ ] 完整路径 opt-in 位置 / owner: M2 TaskCenter / impact: 设置 IA / 默认决策：放在结果 dock 的菜单中，默认关闭。
