from __future__ import unicode_literals

from pathlib import Path

import pytest
from pyfcstm.model import load_state_machine_from_text

from app.application.generation import GenerationService, _inventory, _raise_if_cancelled


SOURCE = """
def int count = 0;
state Root {
    state Idle;
    state Running;
    [*] -> Idle;
    Idle -> Running :: Start effect { count = count + 1; }
    Running -> [*] :: Stop;
}
"""


def test_five_packaged_templates_are_enumerated_and_render_nonempty_files(tmp_path):
    service = GenerationService()
    templates = service.list_templates()
    assert [item.name for item in templates] == ["c", "c_poll", "cpp", "cpp_poll", "python"]
    assert {item.language for item in templates} == {"c", "cpp", "python"}
    assert all(item.title and item.description for item in templates)
    model = load_state_machine_from_text(SOURCE)

    results = []
    for descriptor in templates:
        result = service.generate(
            model,
            str(tmp_path / descriptor.name),
            template_name=descriptor.name,
        )
        results.append(result)
        assert result.template_name == descriptor.name
        assert result.language == descriptor.language
        assert result.files
        assert all(item.size > 0 and len(item.sha256) == 64 for item in result.files)
        assert all((Path(result.output_dir) / item.relative_path).is_file() for item in result.files)
    assert len(results) == 5


def test_generation_refuses_existing_target_and_replace_is_atomic(tmp_path):
    service = GenerationService()
    model = load_state_machine_from_text(SOURCE)
    target = tmp_path / "generated"
    target.mkdir()
    (target / "keep.txt").write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError):
        service.generate(model, str(target), template_name="python")

    result = service.generate(
        model, str(target), template_name="python", overwrite=True
    )
    assert result.files
    assert not (target / "keep.txt").exists()
    assert not list(tmp_path.glob(".generated.backup-*"))


class CancelOnPublish(object):
    def __init__(self):
        self.calls = 0

    def raise_if_cancelled(self):
        self.calls += 1
        if self.calls >= 2:
            raise RuntimeError("cancelled at publish boundary")


def test_generation_cancel_before_publish_preserves_existing_directory(tmp_path):
    service = GenerationService()
    model = load_state_machine_from_text(SOURCE)
    target = tmp_path / "generated"
    target.mkdir()
    (target / "keep.txt").write_text("old", encoding="utf-8")

    with pytest.raises(RuntimeError, match="publish boundary"):
        service.generate(
            model,
            str(target),
            template_name="python",
            overwrite=True,
            cancel_token=CancelOnPublish(),
        )

    assert (target / "keep.txt").read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".fcstm-generate-*"))


def test_custom_template_and_invalid_selection_paths(tmp_path):
    service = GenerationService()
    model = load_state_machine_from_text(SOURCE)
    template = tmp_path / "template"
    template.mkdir()
    (template / "config.yaml").write_text("{}\n", encoding="utf-8")
    (template / "machine.txt.j2").write_text("{{ model.root_state.name }}", encoding="utf-8")

    result = service.generate(
        model,
        str(tmp_path / "custom-output"),
        custom_template_dir=str(template),
    )
    assert result.template_name == "custom"
    assert result.files[0].relative_path == "machine.txt"

    with pytest.raises(ValueError, match="exactly one"):
        service.generate(model, str(tmp_path / "none"))
    with pytest.raises(ValueError, match="exactly one"):
        service.generate(
            model,
            str(tmp_path / "both"),
            template_name="python",
            custom_template_dir=str(template),
        )
    with pytest.raises(LookupError):
        service.generate(model, str(tmp_path / "unknown"), template_name="unknown")
    with pytest.raises(FileNotFoundError):
        service.generate(
            model,
            str(tmp_path / "missing-output"),
            custom_template_dir=str(tmp_path / "missing-template"),
        )

    empty = tmp_path / "empty-template"
    empty.mkdir()
    (empty / "config.yaml").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no files"):
        service.generate(
            model,
            str(tmp_path / "empty-output"),
            custom_template_dir=str(empty),
        )


def test_inventory_and_cancel_token_fallbacks(tmp_path):
    assert _inventory(tmp_path / "missing") == ()
    empty_file = tmp_path / "empty"
    empty_file.mkdir()
    (empty_file / "zero.txt").write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        _inventory(empty_file)

    with pytest.raises(RuntimeError, match="cancelled"):
        _raise_if_cancelled(type("Token", (), {"is_cancelled": lambda self: True})())
    with pytest.raises(RuntimeError, match="cancelled"):
        _raise_if_cancelled(type("Token", (), {"cancelled": lambda self: True})())


def test_atomic_publish_failure_restores_previous_target(monkeypatch, tmp_path):
    import app.application.generation as generation

    service = GenerationService()
    model = load_state_machine_from_text(SOURCE)
    target = tmp_path / "generated"
    target.mkdir()
    (target / "keep.txt").write_text("old", encoding="utf-8")
    real_replace = generation.os.replace
    calls = []

    def fail_publish(source, destination):
        calls.append((source, destination))
        if len(calls) == 2:
            raise OSError("publish failed")
        return real_replace(source, destination)

    monkeypatch.setattr(generation.os, "replace", fail_publish)
    with pytest.raises(OSError, match="publish failed"):
        service.generate(
            model,
            str(target),
            template_name="python",
            overwrite=True,
        )
    assert (target / "keep.txt").read_text(encoding="utf-8") == "old"
