import hashlib
import json
import re
import struct
from pathlib import Path

from scripts.verify_evidence_contract import ACCEPTANCE_NAMES


ROOT = Path(__file__).resolve().parents[2]
GALLERY = ROOT / "docs" / "images" / "acceptance-140"


def test_checked_in_acceptance_gallery_is_complete_and_reproducible():
    manifest = json.loads((GALLERY / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "fcstm-gui.acceptance-gallery"
    assert manifest["version"] == 1
    assert manifest["evidence_kind"] == "source-acceptance"
    assert manifest["fresh_release_evidence"] is False
    assert re.match(r"^[0-9a-f]{40}$", manifest["source"]["commit"])
    assert manifest["report"]["status"] == "passed"
    assert manifest["report"]["counts"] == {
        "failed": 0,
        "passed": 140,
        "total": 140,
    }
    items = manifest["items"]
    assert len(items) == len(ACCEPTANCE_NAMES) == 140
    assert tuple(item["acceptance_id"] for item in items) == ACCEPTANCE_NAMES
    assert [item["order"] for item in items] == list(range(1, 141))
    for item in items:
        assert item["status"] == "passed"
        image = GALLERY / item["image"]
        data = image.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(data) == item["image_size"]
        assert hashlib.sha256(data).hexdigest() == item["image_sha256"]
        assert struct.unpack(">II", data[16:24]) == (1280, 720)
    actual = {
        path.name
        for path in GALLERY.glob("*.png")
    }
    assert actual == {item["image"] for item in items}


def test_acceptance_gallery_markdown_links_every_stable_item():
    markdown = (GALLERY / "README.md").read_text(encoding="utf-8")
    for item_id in ACCEPTANCE_NAMES:
        assert "`{}`".format(item_id) in markdown
    links = re.findall(r"\]\(([^)]+\.png)\)", markdown)
    assert len(links) == 140
    assert all((GALLERY / link).is_file() for link in links)
