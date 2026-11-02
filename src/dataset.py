"""One immutable, hash-verified input snapshot shared by both future adapters."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class InputText:
    text_id: str
    split: str
    text_sha256: str
    content: str


def load_snapshot(root: Path, descriptor: Path | None = None) -> tuple[InputText, ...]:
    lock = json.loads((descriptor or root / "data/active_dataset.json").read_text(encoding="utf-8"))
    manifest = (root / lock["manifest_path"]).resolve()
    if not manifest.is_relative_to(root.resolve()):
        raise ValueError("Manifest escapes dataset root")
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != lock["manifest_sha256"]:
        raise ValueError("Manifest hash mismatch")
    inputs = []
    seen = set()
    for line in raw.decode("utf-8").splitlines():
        row = json.loads(line)
        path = (root / row["text_path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Input escapes dataset root")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row["text_sha256"]:
            raise ValueError(f"Input hash mismatch: {row['text_id']}")
        if row["text_id"] in seen:
            raise ValueError("Duplicate input ID")
        seen.add(row["text_id"])
        inputs.append(InputText(row["text_id"], row["split"], row["text_sha256"], content.decode("utf-8")))
    return tuple(inputs)
