# Historical Full Release Lineage Reverification

## Scope

This audit re-runs the current repository evidence verifier against the cached
artifacts from Full Release run `29216171779` (`b6bb7e2162132e68cb3e3a1ce17ceb89fc6a0e55`).
It is deliberately separate from the source-only 140-item GUI gallery and does not
claim that the old artifact was built at the current documentation SHA.

## Evidence

The six extracted evidence directories were checked with:

```bash
root=/tmp/fcstm-gui-final-29216171779
for d in "$root"/*-evidence; do
  [ -f "$d/acceptance-evidence.json" ] || continue
  venv/bin/python scripts/verify_evidence_contract.py \
    --evidence "$d/acceptance-evidence.json" \
    --reports "$d/manifest-input/reports" \
    --artifact-root "$d"
done
venv/bin/python scripts/verify_evidence_contract.py \
  --visual-review /tmp/fcstm-gui-visual-root/visual-review.json \
  --visual-root /tmp/fcstm-visual-lineage-root
```

Observed result: all six evidence contracts passed, and the visual review passed
all `54/54` samples with `blocking_findings=[]`. The visual review has two recorded
non-blocking Cocoa boundary-contact findings; every required functional verdict is
true. The temporary visual root uses symlinks into the extracted run and does not
copy or alter the products.

## Product Lineage

The following command returned exit code `0` at `main@ec4311d` and remains true for
the docs-only descendants through `e1e068f`:

```bash
git diff --quiet b6bb7e2..HEAD -- \
  app main.py main.spec requirements-build.txt requirements-test.txt \
  requirements.txt Makefile
```

Therefore the historical products remain a valid behavioral reference for the
unchanged core product tree. Workflow, evidence scripts, manuals and screenshots
changed after that run; those changes are not silently represented as product
freshness. A new Full Release is required if any path in the command above changes,
or if a serious cross-platform product failure is found.

## Remaining Boundary

This audit closes the historical artifact and visual-review integrity check. It does
not change the evidence identity from `b6bb7e2` to the current docs-only SHA, so the
Issue remains conservative about strict current-SHA READY wording. Fast Verify is
the current Windows/Linux product gate; docs-only commits are excluded by its path
filters.
