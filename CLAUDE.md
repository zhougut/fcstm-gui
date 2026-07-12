# fcstm-gui Engineering Contract

This file is the durable operating guide for contributors and coding agents.
Update it whenever a build, packaging, GUI, or cross-platform failure teaches a
repeatable lesson. `AGENTS.md` is a symlink to this file so both entry points
always expose the same contract.

## Delivery Standard

- Treat `DESIGN.md`, `zhougut/fcstm-gui#1`, `HansBug/pyfcstm#360`, and
  `HansBug/pyfcstm#362` as the acceptance baseline.
- Do not report completion from source tests alone. A release candidate is done
  only after real GUI operation, self-checks, acceptance checks, packaging, and
  fresh-runner verification all pass.
- Preserve user changes and unrelated worktree changes. Keep commits scoped so
  an infrastructure fix does not accidentally publish unfinished features.
- Use test-driven changes for behavior. Add a focused regression test before or
  with each bug fix, then run the broader affected suite.

## Maintenance Discipline

- Keep `CLAUDE.md` as the single source of agent/contributor operating memory;
  `AGENTS.md` must remain a symlink to it, not a divergent copy.
- When a workflow, packaging, GUI, cross-platform, or evidence problem teaches a
  repeatable lesson, add the durable rule here in the same branch that fixes or
  plans the issue.
- Do not mark a requirement complete from intent, screenshots, source-only
  tests, or stale issue checkboxes. Completion needs fresh linked evidence:
  test/report/screenshot/artifact/CI job as applicable to that requirement.
- Keep issue state, evidence indexes, operation manuals, and CI contracts in
  sync. A checklist item that cannot be reproduced from clean settings remains
  pending even if lower-level services pass.
- Separate infrastructure commits from unfinished product work. Before pushing,
  inspect the diff and include only the files needed for the current coherent
  fix or evidence update.

## CLI And Self-Check Discipline

- `--self-check` must execute every bundled pyfcstm library and core path; an
  import or version query is not evidence that a native binding works.
- Exercise cross-platform-sensitive dependencies through real logic: parsing,
  model loading, rendering, filesystem paths, subprocesses, native libraries,
  and solver calls where applicable.
- Z3 coverage must include at least five actual solve/optimize scenarios with
  checked results, not only module import or version output.
- Give every core capability named in pyfcstm PR #362 and its upstream issue an
  independent, visible self-check item.
- `--acceptance-check` must exercise the user-visible acceptance workflows and
  fail nonzero when any item fails. Output must identify each item separately.

## GUI Verification Discipline

- Test actual widgets, signals, keyboard paths, dialogs, navigation, task
  cancellation/retry, and persisted settings. Calling service methods alone is
  not GUI acceptance evidence.
- Capture screenshots at relevant desktop sizes, including 1280x720, and review
  the pixels for clipping, overlap, unreadable text, disabled actions, stale
  state, and incorrect selection.
- Keep source text authoritative. Projections and forms must retain exact source
  references, revisions, fingerprints, and read-only provenance.
- Background results must be revision/dependency gated; stale results must not
  overwrite the current document.
- Never expose raw local paths by default. Full-path display, copy, persistence,
  and export require explicit opt-in.

## Build And CI Workflow

- Follow a two-stage matrix for Linux x86_64, Windows x86_64, and macOS x86_64.
- Stage 1 builds and smoke-tests both onedir and onefile artifacts on each target
  OS, then uploads both artifacts.
- Stage 2 uses fresh runners, installs no project Python or project dependencies,
  downloads the artifacts, and runs black-box self-check plus acceptance tests.
  Only unavoidable system runtime components such as a JRE may be installed.
- A fresh runner may use its preinstalled Python only for standard-library
  evidence collation and SHA/schema verification after the frozen products
  finish. It must not import project code, install packages, or make product
  execution depend on that interpreter.
- Watch every workflow job and inspect logs and produced artifacts. A green build
  job does not compensate for a skipped or failed fresh-runner verification job.
- After each CI fix, push the smallest coherent commit and watch the replacement
  run through all six matrix jobs. Iterate until all are green.

## Cross-Platform Lessons

- Qt text positions are UTF-16 positions. `QPlainTextEdit` also normalizes CRLF
  to one paragraph separator, so source offset conversion must account for both
  surrogate pairs and CRLF contraction.
- Canonical file URI casing differs on Windows. Compare against the application's
  canonical `SourceDocument` URI rather than `Path.resolve().as_uri()`.
- Redacted persisted paths use `/` after `<WORKSPACE>`, `<TEMP>`, and `<HOME>` on
  every OS so history and diagnostics remain portable.
- JSON escapes Windows backslashes. Parse JSON and compare fields instead of
  searching serialized text for an unescaped native path.
- `QUrl.toLocalFile()` may return `/` separators on Windows. Compare resolved
  `Path` values, not raw strings.
- Font-dependent Qt elision may not render a literal Unicode ellipsis. Verify
  that text is shortened and distinct while checking the full value via tooltip.
- Do not assume checkout line endings. Assertions about unchanged text should use
  the loaded pre-operation source as their baseline.
- PyQt signal-slot exceptions can abort or wedge the test process instead of
  becoming ordinary pytest failures. Exercise slots with production-shaped DTOs;
  recursively convert read-only mappings before JSON serialization.
- Preserve diagnostic source kind at the validation boundary. Validation state
  alone cannot distinguish loader/model failures from error-severity inspect
  findings, and navigation must gate both revision and dependency fingerprint.
- Field-level action checks must use the current document's real variable
  declarations. Do not invent declarations for every identifier merely to make
  a minimal wrapper load; full-document save validation remains authoritative.
- Treat artifact-service timeouts as infrastructure failures only after the log
  proves tests and local packaging passed. Re-run and still inspect the complete
  replacement matrix rather than weakening artifact upload checks.
- Validate dynamic-validation payload type before treating it as a filesystem
  path. A direct JSON array/scalar must become a structured scenario error, not
  a platform-dependent `Path` `TypeError`.
- A cancelled `TaskRunner` result may still carry cycles or steps completed
  before the cooperative boundary. Render and persist those partial results
  before publishing the cancelled state; cancellation must not erase evidence.
- Versioned validation reports must carry the scenario SHA-256, model content
  fingerprint, and source revision alongside expected/actual data. Keep these
  provenance fields in exported reports and frozen-resource acceptance checks.
- Do not add a schema-validation dependency only for CI. When the repository
  does not already depend on one, keep runtime validation strict and provide a
  standard-library frozen-artifact checker for the supported schema subset.
- Byte-pinned fixture and provenance resources must have explicit Git EOL
  attributes. Windows checkout conversion is a real byte mutation; never make
  SHA-256 checks line-ending-insensitive to hide it.
- Keep stable Qt combo identifiers as scalar strings. PyQt5 `findData()` does
  not reliably match compound Python tuple values across QVariant boundaries.
- Loading/progress controls must keep a stable layout footprint. Switch a
  progress bar between determinate and indeterminate ranges instead of hiding
  and showing it around tasks.
- Size compact toolbars against the workspace width after docks and splitters,
  not the top-level window width. If child minimum sizes exceed the nested
  layout allocation, Qt can place focusable siblings on top of each other;
  keep stable control widths and fail geometry acceptance on every real
  overlap instead of adding platform-specific overlap exemptions.
- Run cross-platform GUI checks with the target platform plugin (`xcb`,
  `windows`, or `cocoa`) in both package and fresh stages. Windows Qt can
  access-violate when a real modal message box is driven through the offscreen
  plugin; an offscreen pass is not evidence for the native Windows path.
- Source-mode Linux xcb needs the complete Qt host library set on the build
  runner. Keep that installation confined to Stage 1; Stage 2 must continue to
  install only the display host/JRE so the frozen artifact, not apt, supplies
  its bundled xcb/GL/font dependencies.
- Size pytest timeouts for the complete parameterized acceptance duration.
  A per-test timeout shorter than the known 140-item run produces a false
  infrastructure failure even when all preceding items pass; keep the inner
  operation timeouts strict and give the outer suite a separate broad bound.
- Resolve bundled resources from `_MEIPASS` when frozen and from the module's
  repository/package root in source mode. Never assume the process cwd is the
  project root.
- A Qt completion signal can belong to a superseded attempt on the same
  channel. Acceptance drivers must filter by session id and source revision;
  merely waiting for the next signal can race a later product task.
- Programmatic projection clearing must stop pending form timers and suppress
  form `textChanged` handlers. Otherwise a delayed form commit can create a
  content-identical revision and correctly trip every artifact publication
  guard.
- Treat report JSON, logs, screenshots, and exports as first-class CI
  evidence. Produce them separately for source, onedir, onefile, and fresh
  verification instead of relying on console success text.
- Fresh verification must independently recompute product and evidence sizes,
  SHA-256 digests, schemas, and stable item sets. Reusing a build-stage manifest
  without download-side comparison does not prove artifact transport integrity.
- Evidence verification must walk reports, runtime artifacts, screenshots, and
  product manifests. Valid report JSON does not compensate for a missing or
  altered top-level file.
- A generated file inventory is not runtime evidence. Execute the Python
  runtime and compile, link, and run C, C poll, C++, and C++ poll outputs on
  every native build runner.
- Exercise GUI acceptance across the cross product of 1280x720 and 1920x1080
  with Qt scale factors 1, 1.5, and 2. Inspect representative pixels in
  addition to checking widget geometry numerically.
- Numeric geometry cannot detect missing glyphs. Fresh Linux and Windows
  runners may lack a usable CJK fallback even when every widget fits; keep the
  OFL-licensed bundled font loaded as the application family, assert that
  family and a fixed point size in reports, and inspect fresh-runner
  screenshots before release.
- A non-empty graph scene is not proof of a rendered state machine. PlantUML
  can render a diagnostic image such as "Cannot find Graphviz" and still leave
  the scene non-empty. Acceptance must assert semantic graph content, reject
  renderer diagnostic text, and inspect Linux, Windows, and macOS screenshots.
- Fresh verification must not install Graphviz to hide an incomplete artifact.
  Use the PlantUML Smetana engine and test with `GRAPHVIZ_DOT` pointing to a
  missing executable. Bind PNG/PDF evidence to a semantically validated SVG
  from the same normalized source hash and engine.
- PlantUML pipe execution must request UTF-8 explicitly on every OS. For
  cancellable external rendering, retain the `Popen` handle, poll the task token,
  and terminate/kill the child; checks only before and after a blocking call do
  not provide a usable cancel boundary.
- Do not reject every successful renderer invocation merely because stderr is
  non-empty. macOS Java may emit the exact software-GL warning while producing
  valid Smetana output; allow only an explicit reviewed warning line, preserve
  it in execution metadata, and keep every unknown stderr line fail-closed.
- Cairo PDF object layout varies by platform; macOS may compress the page
  dictionary so `/MediaBox` is not visible as raw bytes. Bind PDF to the
  semantically validated source SVG, require PDF magic/startxref/EOF and a
  meaningful size, and validate dimensions when MediaBox is directly present.
- Qt rectangle intersection semantics include a shared one-pixel edge on some
  styles. Treat width or height <= 1 as boundary contact, not control overlap,
  while keeping every larger intersection fail-closed.
- Native Qt platforms ignore synthetic mouse clicks on hidden widgets more
  consistently than offscreen. Widget tests must show and process the target
  before clicking; a hidden-widget click is not a user-path test.
- GitHub-hosted Windows GUI sessions may start at roughly 1024x768 and clamp a
  requested 1280x720 window. Set and log a 1920x1080 native display resolution
  before source and fresh acceptance; otherwise the geometry result describes
  the runner clamp rather than the requested viewport.
- File URI and newline facts are platform-normalized by the application source
  layer. Cross-platform acceptance must compare `SourceDocument.uri` and the
  active session's loaded text baseline, not reconstruct URIs with `Path.as_uri`
  or compare a reopened document to a hard-coded LF literal.
- A temporary directory can be nested under the user home on Windows. Redaction
  assertions accept either `<TEMP>` or `<HOME>` as safe output while still
  rejecting the raw path.
- macOS owns the application menu bar globally, so synthetic clicks against a
  window-local `QMenuBar.actionGeometry()` do not prove or reliably open the
  native menu. For non-keyboard acceptance, resolve the real recent-file
  `QAction` from its product `QMenu`, trigger that action, and still gate on the
  asynchronous load signal plus the new session/path/text facts. Never replace
  this with a direct document-service or load-slot call.
- Give every acceptance case a stable parameterized id and isolated fixture or
  proven reset. One failed GUI path must not poison later cases or collapse
  multiple unexecuted capabilities into one broad passing item.
- Keep internal status ids such as `failed`, `cancelled`, and `stale` in JSON or
  tooltips. User-visible labels and recovery text must use consistent Chinese
  wording across workspaces and dialogs.
- Task-history cleanup commands must state distinct data boundaries. "Clear
  completed" removes successful terminal records, while "clear all history"
  removes all removable terminal records and never discards live tasks.
- Keep repository documentation images separate from final-run evidence. Store
  reproducible workflow images and their source tree hash in the repository;
  publish the final run, artifact digests, and visual verdict as an issue
  attestation so updating evidence does not create an endless commit/run loop.
- Treat the illustrated operation manual as a tested product. Map every GUI
  acceptance id to numbered steps, screenshots, expected state, artifacts, and
  recovery guidance; then have an independent reviewer reproduce the workflow
  from clean settings using only the manual. Iterate until no critical or
  important documentation gaps remain.
- Keep productization issues synchronized with current evidence. Mark an item
  complete only when its linked test, report, screenshot, artifact, and CI job
  prove the exact user path; do not inherit stale checkboxes from an older
  implementation plan or extrapolate service coverage into GUI coverage.
- Every newly discovered repeatable failure mode must be added here in the same
  change that fixes or plans it. This file is cumulative operating memory, not
  a one-time project description.
- An empty clipboard paste does not delete a selected Qt field on every
  platform. Acceptance drivers that clear text must send Select All, Backspace,
  then paste the replacement so empty-value paths are genuinely exercised.
- Do not type an absolute path into a non-native `QFileDialog` filename field
  and assume Enter accepts it. Navigate the dialog to the parent directory,
  type only the basename, wait for the AcceptRole button to enable, and click
  that real Open/Save button.
- A closed test window is not an isolated test window until Qt processes its
  deferred deletion. Fresh-window acceptance must call `deleteLater`, flush
  `DeferredDelete`, process events, and reject any visible top-level survivor.
- Invalid syntax is a valid editable document-load result with diagnostics, not
  an I/O load failure. Test failed-load session preservation with a real read
  failure after file-dialog acceptance, and assert the original session,
  manager, source, revision, and workspace remain installed.
- Layout membership does not prove non-overlap. Inspect mapped widget rectangles
  at runtime; in particular, Qt5 combo size-adjust policies can exceed a nested
  layout allocation under offscreen rendering unless width policy and spacing
  are explicit.

## Required Local Evidence

Before pushing a behavior change, run the smallest focused tests and then:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest test -q --timeout=30
.venv/bin/python -m compileall -q app test scripts main.py
.venv/bin/python -m pip check
xmllint --noout app/ui/main_window.ui
python -c "import yaml; yaml.safe_load(open('.github/workflows/build.yml'))"
git diff --check
```

Record any unavailable check explicitly. Keep Chinese operational documentation
under `docs/` and its reviewed screenshots under `docs/images/`.
