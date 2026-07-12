"""Atomic code generation through packaged or custom pyfcstm templates."""

from __future__ import unicode_literals

import hashlib
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

from pyfcstm.render import StateMachineCodeRenderer
from pyfcstm.template import extract_template, get_template_info, list_templates


@dataclass(frozen=True)
class TemplateDescriptor:
    name: str
    title: str
    language: str
    description: str
    experimental: bool


@dataclass(frozen=True)
class GeneratedFile:
    relative_path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class GenerationResult:
    template_name: str
    language: str
    output_dir: str
    files: Tuple[GeneratedFile, ...]


class GenerationService(object):
    """Enumerate templates and atomically publish generated directories."""

    def list_templates(self):
        descriptors = []
        for name in list_templates():
            info = get_template_info(name)
            descriptors.append(
                TemplateDescriptor(
                    name=name,
                    title=str(info.get("title") or name),
                    language=str(info.get("language") or ""),
                    description=str(info.get("description") or ""),
                    experimental=bool(info.get("experimental", False)),
                )
            )
        return tuple(descriptors)

    def generate(
        self,
        model: Any,
        output_dir: str,
        template_name: Optional[str] = None,
        custom_template_dir: Optional[str] = None,
        overwrite: bool = False,
        cancel_token: Optional[Any] = None,
    ) -> GenerationResult:
        if bool(template_name) == bool(custom_template_dir):
            raise ValueError("choose exactly one built-in or custom template")
        target = Path(output_dir).resolve()
        if target.exists() and not overwrite:
            raise FileExistsError("output directory already exists: " + str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        stage_root = Path(
            tempfile.mkdtemp(prefix=".fcstm-generate-", dir=str(target.parent))
        )
        generated = stage_root / "output"
        template_stage = stage_root / "template"
        descriptor = None
        backup = None
        try:
            _raise_if_cancelled(cancel_token)
            if template_name:
                descriptor = next(
                    (
                        item
                        for item in self.list_templates()
                        if item.name == template_name
                    ),
                    None,
                )
                if descriptor is None:
                    raise LookupError("unknown built-in template: " + template_name)
                template_dir = extract_template(template_name, str(template_stage))
            else:
                template_dir = str(Path(custom_template_dir).resolve())
                if not Path(template_dir).is_dir():
                    raise FileNotFoundError("custom template directory not found")
            renderer = StateMachineCodeRenderer(template_dir=template_dir)
            renderer.render(model, output_dir=str(generated), clear_previous_directory=True)
            files = _inventory(generated)
            if not files:
                raise ValueError("template generated no files")
            _raise_if_cancelled(cancel_token)
            if target.exists():
                backup = target.with_name(
                    ".{}.backup-{}".format(target.name, uuid.uuid4().hex)
                )
                os.replace(str(target), str(backup))
            try:
                os.replace(str(generated), str(target))
            except BaseException:
                if backup is not None and backup.exists() and not target.exists():
                    os.replace(str(backup), str(target))
                raise
            if backup is not None:
                shutil.rmtree(str(backup))
            language = descriptor.language if descriptor is not None else "custom"
            name = descriptor.name if descriptor is not None else "custom"
            return GenerationResult(
                template_name=name,
                language=language,
                output_dir=str(target),
                files=files,
            )
        finally:
            shutil.rmtree(str(stage_root), ignore_errors=True)


def _inventory(root):
    files = []
    if not root.is_dir():
        return ()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        data = path.read_bytes()
        if not data:
            raise ValueError("generated file is empty: " + str(path.relative_to(root)))
        files.append(
            GeneratedFile(
                relative_path=path.relative_to(root).as_posix(),
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    return tuple(files)


def _raise_if_cancelled(cancel_token):
    if cancel_token is None:
        return
    raiser = getattr(cancel_token, "raise_if_cancelled", None)
    if callable(raiser):
        raiser()
        return
    checker = getattr(cancel_token, "is_cancelled", None)
    cancelled = checker() if callable(checker) else getattr(cancel_token, "cancelled", False)
    if callable(cancelled):
        cancelled = cancelled()
    if cancelled:
        raise RuntimeError("generation cancelled")
