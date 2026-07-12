import hashlib

from app import self_check
from app.acceptance_check import AcceptanceDriver
from scripts.verify_evidence_contract import (
    ACCEPTANCE_NAMES,
    SELF_CHECK_BEHAVIOR,
    SELF_CHECK_MODULE_CLOSURE,
    SELF_CHECK_NAMES_SHA256,
    SELF_CHECK_TOTAL,
)


def test_fresh_evidence_verifier_matches_production_acceptance_catalog(
    qtbot, tmp_path
):
    driver = AcceptanceDriver(str(tmp_path / "artifacts"), (1280, 720))
    names = []
    driver.run_item = lambda name, function, with_document=True: names.append(name)
    try:
        driver.run()
    finally:
        driver.close()

    assert tuple(names) == ACCEPTANCE_NAMES


def test_fresh_evidence_verifier_locks_complete_self_check_inventory():
    names = [name for name, _check in self_check._checks()]
    module_count = sum(name.startswith("import ") for name in names)

    assert len(names) == SELF_CHECK_TOTAL
    assert module_count == SELF_CHECK_MODULE_CLOSURE
    assert len(names) - module_count == SELF_CHECK_BEHAVIOR
    assert hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest() == (
        SELF_CHECK_NAMES_SHA256
    )
