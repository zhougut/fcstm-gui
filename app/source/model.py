import codecs
import hashlib
import os
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Union

import chardet


PathLike = Union[str, os.PathLike]


class SourceEncodingAmbiguityError(UnicodeError):
    pass


def canonical_path(path: PathLike) -> Path:
    return Path(os.path.abspath(os.fspath(path))).resolve(strict=False)


def _decode_source(raw: bytes, encoding: Optional[str] = None) -> Tuple[str, str]:
    if encoding is not None:
        text = raw.decode(encoding)
        if text.encode(encoding) != raw:
            raise UnicodeError("source bytes do not round-trip with {}".format(encoding))
        return text, encoding
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    if raw.startswith(codecs.BOM_UTF32_LE) or raw.startswith(codecs.BOM_UTF32_BE):
        return raw.decode("utf-32"), "utf-32"
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return raw.decode("utf-16"), "utf-16"

    try:
        utf8_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        utf8_text = None

    detected = chardet.detect(raw)
    detected_encoding = detected.get("encoding")
    confidence = detected.get("confidence") or 0.0
    if detected_encoding and confidence >= 0.8:
        normalized = detected_encoding.lower().replace("_", "-")
        aliases = {
            "gb2312": "gb18030",
            "gbk": "gb18030",
            "cp936": "gb18030",
            "big5": "big5",
            "cp950": "big5",
        }
        selected = aliases.get(normalized)
        if selected is not None:
            text = raw.decode(selected)
            if text.encode(selected) == raw:
                return text, selected

        if normalized in {"utf-8", "utf8", "ascii"} and utf8_text is not None:
            return utf8_text, "utf-8"

    if utf8_text is not None:
        try:
            gb18030_text = raw.decode("gb18030")
        except UnicodeDecodeError:
            gb18030_text = None
        if gb18030_text is not None and gb18030_text != utf8_text:
            raise SourceEncodingAmbiguityError(
                "source bytes are valid as both UTF-8 and GB18030; "
                "an explicit encoding is required"
            )
        return utf8_text, "utf-8"

    candidates = (
        "gb18030",
        "gbk",
        "gb2312",
        "cp936",
        "big5",
        "cp950",
    )
    last_error = None
    for encoding in candidates:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as error:
            last_error = error
            continue
        if text.encode(encoding) == raw:
            return text, encoding
    if last_error is not None:
        raise last_error
    return raw.decode("utf-8"), "utf-8"


def _line_index(text: str) -> Tuple[int, ...]:
    starts = [0]
    starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")
    return tuple(starts)


@dataclass(frozen=True)
class SourceSpan:
    start_offset: int
    end_offset: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    path: str
    uri: str
    original_bytes: bytes
    encoding: str
    text: str
    revision: int
    line_index: Tuple[int, ...]
    sha256: str
    snapshot_fingerprint: str

    @classmethod
    def from_file(
        cls,
        path: PathLike,
        revision: Optional[int] = None,
        encoding: Optional[str] = None,
        snapshot_fingerprint: Optional[str] = None,
    ) -> "SourceDocument":
        resolved = canonical_path(path)
        raw = resolved.read_bytes()
        return cls.from_bytes(
            resolved,
            raw,
            revision=revision,
            encoding=encoding,
            snapshot_fingerprint=snapshot_fingerprint,
        )

    @classmethod
    def from_bytes(
        cls,
        path: PathLike,
        raw: bytes,
        revision: Optional[int] = None,
        encoding: Optional[str] = None,
        snapshot_fingerprint: Optional[str] = None,
    ) -> "SourceDocument":
        resolved = canonical_path(path)
        text, detected_encoding = _decode_source(raw, encoding=encoding)
        normalized_path = os.path.normcase(str(resolved))
        uri = Path(normalized_path).as_uri()
        identity = normalized_path.encode("utf-8")
        sha256 = hashlib.sha256(raw).hexdigest()
        if revision is None:
            revision = int(sha256[:16], 16)
        if snapshot_fingerprint is None:
            snapshot_fingerprint = sha256
        return cls(
            document_id=hashlib.sha256(identity).hexdigest(),
            path=str(resolved),
            uri=uri,
            original_bytes=bytes(raw),
            encoding=detected_encoding,
            text=text,
            revision=revision,
            line_index=_line_index(text),
            sha256=sha256,
            snapshot_fingerprint=snapshot_fingerprint,
        )

    def offset_to_line_column(self, offset: int) -> Tuple[int, int]:
        if offset < 0 or offset > len(self.text):
            raise ValueError("source offset is outside the document")
        line_index = bisect_right(self.line_index, offset) - 1
        return line_index + 1, offset - self.line_index[line_index] + 1

    def python_to_qt_offset(self, offset: int) -> int:
        if offset < 0 or offset > len(self.text):
            raise ValueError("source offset is outside the document")
        qt_offset = 0
        python_offset = 0
        while python_offset < offset:
            char = self.text[python_offset]
            if (
                char == "\r"
                and python_offset + 1 < len(self.text)
                and self.text[python_offset + 1] == "\n"
            ):
                qt_offset += 1
                python_offset += 2
                continue
            qt_offset += 2 if ord(char) > 0xFFFF else 1
            python_offset += 1
        return qt_offset

    def qt_to_python_offset(self, offset: int) -> int:
        if offset < 0:
            raise ValueError("Qt offset is outside the document")
        qt_offset = 0
        python_offset = 0
        while python_offset < len(self.text):
            if qt_offset == offset:
                return python_offset
            char = self.text[python_offset]
            if (
                char == "\r"
                and python_offset + 1 < len(self.text)
                and self.text[python_offset + 1] == "\n"
            ):
                qt_offset += 1
                python_offset += 2
                continue
            width = 2 if ord(char) > 0xFFFF else 1
            if qt_offset < offset < qt_offset + width:
                raise ValueError("Qt offset splits a UTF-16 surrogate pair")
            qt_offset += width
            python_offset += 1
        if qt_offset == offset:
            return len(self.text)
        raise ValueError("Qt offset is outside the document")


@dataclass(frozen=True)
class DeclarationRef:
    source_uri: str
    file_id: str
    source_revision: int
    snapshot_fingerprint: str
    document_sha256: str
    kind: str
    span: SourceSpan
    stable_key: str
    range_sha256: str


@dataclass(frozen=True)
class SourceRef:
    source_uri: str
    file_id: str
    source_revision: int
    snapshot_fingerprint: str
    document_sha256: str
    kind: str
    span: SourceSpan
    stable_key: str
    ownership: str
    editable: bool
    declaration_ref: DeclarationRef
    owner_path: Tuple[str, ...]
    range_sha256: str
    deletion_replacement: str = ""
    resolved_path: Tuple[str, ...] = ()
    scope: Optional[str] = None

    @property
    def read_only(self) -> bool:
        return not self.editable

    @property
    def document_id(self) -> str:
        return self.file_id

    @property
    def revision(self) -> int:
        return self.source_revision

    @property
    def semantic_key(self) -> str:
        return self.stable_key


@dataclass(frozen=True)
class ImportEdge:
    source_document_id: str
    target_document_id: str
    source_ref: SourceRef
    source_path: str
    alias: str
    owner_path: Tuple[str, ...]
    instance_id: str

    @property
    def projection_path(self) -> Tuple[str, ...]:
        return self.owner_path + (self.alias,)


@dataclass(frozen=True)
class SourceProjection:
    projection_id: str
    physical_ref: SourceRef
    edge_chain: Tuple[str, ...]
    alias_chain: Tuple[str, ...]
    projected_owner_path: Tuple[str, ...]
    ownership: str = "imported"
    editable: bool = False
    projected_resolved_path: Tuple[str, ...] = ()

    @property
    def source_uri(self) -> str:
        return self.physical_ref.source_uri


@dataclass(frozen=True)
class InsertionAnchor:
    source_uri: str
    file_id: str
    source_revision: int
    snapshot_fingerprint: str
    document_sha256: str
    offset: int
    slot: str
    owner_path: Tuple[str, ...]
    left_context_sha256: str
    right_context_sha256: str
    container_declaration_ref: Optional[DeclarationRef]
    editable: bool


class StaleSourceRefError(ValueError):
    pass
