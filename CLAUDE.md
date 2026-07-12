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
- Resolve bundled resources from `_MEIPASS` when frozen and from the module's
  repository/package root in source mode. Never assume the process cwd is the
  project root.

## Required Local Evidence

Before pushing a behavior change, run the smallest focused tests and then:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest test -q --timeout=30
.venv/bin/python -m compileall -q app test main.py
.venv/bin/python -m pip check
xmllint --noout app/ui/main_window.ui
git diff --check
```

Record any unavailable check explicitly. Keep Chinese operational documentation
under `docs/` and its reviewed screenshots under `docs/images/`.
