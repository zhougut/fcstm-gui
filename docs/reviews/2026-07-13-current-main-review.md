# Current Main Review: Fast Gate And Documentation

- reviewed commit: `3c54c25`
- reviewer: Codex root (implementation and GUI evidence review)
- scope: existing Issue #2/#3, current `main`, GUI acceptance contract, workflow
  topology, Chinese operation manual, source-reference screenshots, and the
  Fast Verify run `29228970285` and previously completed Full Release baseline
  `29216171779`

## Findings

### Blocking

None found in the implemented Windows/Linux user paths. Fast Verify run
`29228970285` passed both build/source legs and both fresh onefile self-check legs:
each source leg reported `182/182` self-check and `140/140` GUI acceptance; each
fresh leg reported `182/182` without project Python dependencies. The historical
Full Release baseline also ran all six Package/fresh legs successfully and its
downloaded evidence was re-verified for JSON status, 182 self-check items, 140
acceptance items, artifact size/SHA, screenshots, and executable magic/architecture.

### Non-blocking

The macOS Cocoa native toolbar has two pre-approved boundary-contact families:
`ordinary_simulation_panel` and `dynamic_validation_panel`. The 54-sample visual
review recorded all seven functional verdicts as true; no text, hit target, focus,
accessibility, business, or artifact fact was impaired.

## GUI evidence inspected

The representative fresh screenshots were opened as six 3x3 contact sheets and
full-resolution samples. They show:

- model/source/graph/diagnostics/simulation/dynamic workspaces fully contained;
- a real Smetana state graph with `Root`, `Idle`, `Running`, `Start`, and `Stop`;
- a real simulation initialization transcript and cycle state;
- dynamic case rows with expected/actual inputs and provenance JSON;
- readable CJK labels and redacted `<WORKSPACE>`/`<TEMP>` paths.

The source-reference workflow images remain in `docs/images/workflows/` and are
explicitly marked `fresh_release_evidence=false`; they are documentation visuals,
not a substitute for downloaded release evidence.

The historical Full Release evidence and 54-sample visual review were re-run through
the current verifier using a symlinked extracted root. The strict attestation is
persisted at [`2026-07-13-visual-attestation.json`](2026-07-13-visual-attestation.json).
See [`2026-07-13-lineage-reverification.md`](2026-07-13-lineage-reverification.md)
for the exact command and the explicit old-commit identity boundary.

## Current gates

- Default push/PR: `.github/workflows/fast-verify.yml`, Windows/Linux only,
  two stages with `timeout-minutes: 10` per job: Stage 1 real `182/182`
  self-check plus `140/140` acceptance and a lightweight onefile build; Stage 2
  fresh onefile `182/182` self-check without project Python dependencies.
- Release evidence: `.github/workflows/build.yml`, manual or `v*` tag only,
  three-platform onedir/onefile and fresh black-box matrix.
- Documentation index: `docs/验收矩阵.md` and `docs/验收证据索引.md`.
- Full operating procedure: `docs/完整操作验收手册.md`.

## Residual delivery action

Fast Verify is complete for `main` at `29228970285`, and its status plus the
persisted visual attestation have been recorded in Issue #2/#3. The historical
baseline remains an explicit product-lineage evidence boundary; do not create
another issue. A new Full Release run is only needed when publishing new binaries,
when the core product tree changes, or when a serious cross-platform failure is
discovered.
