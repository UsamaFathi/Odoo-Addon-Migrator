from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import zipfile

from .ranker import LogisticRanker


BRAIN_SCHEMA_VERSION = 2
BRAIN_MEMBER = "brain.json"
SUPPORTED_BRAIN_SCHEMA_VERSIONS = frozenset({1, BRAIN_SCHEMA_VERSION})


@dataclass(frozen=True, slots=True)
class BrainPack:
    payload: dict[str, Any]

    @property
    def source(self) -> int:
        return int(self.payload["source_version"])

    @property
    def target(self) -> int:
        return int(self.payload["target_version"])

    @property
    def fingerprint(self) -> str:
        return str(self.payload.get("fingerprint", ""))

    @property
    def ranker(self) -> LogisticRanker:
        return LogisticRanker.from_dict(self.payload["ranker"])

    @property
    def training(self) -> dict[str, Any]:
        return dict(self.payload.get("training", {}))

    @property
    def source_identities(self) -> dict[str, Any]:
        return dict(self.payload.get("source_identities", {}))

    @property
    def contains_source_code(self) -> bool:
        """A pack contains derived knowledge only, never source text."""
        forbidden = {"source_text", "target_text", "source_code", "target_code", "file_contents"}

        def scan(value: Any) -> bool:
            if isinstance(value, Mapping):
                return any(str(key).lower() in forbidden or scan(item) for key, item in value.items())
            if isinstance(value, (list, tuple)):
                return any(scan(item) for item in value)
            return False

        return scan(self.payload)

    def step(self, source: int, target: int) -> dict[str, Any]:
        key = f"{source}_to_{target}"
        try:
            return dict(self.payload["steps"][key])
        except KeyError as exc:
            raise ValueError(f"Migration Brain does not contain step {source} -> {target}.") from exc

    def supports(self, source: int, target: int) -> bool:
        return all(
            f"{version}_to_{version + 1}" in self.payload.get("steps", {})
            for version in range(source, target)
        )

    def save(self, path: str | Path) -> Path:
        if self.contains_source_code:
            raise ValueError("Migration Brain pack must not contain Odoo source code.")
        destination = Path(path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(self.payload)
        payload["schema_version"] = BRAIN_SCHEMA_VERSION
        payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        payload["fingerprint"] = ""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["fingerprint"] = hashlib.sha256(canonical).hexdigest()
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")

        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.writestr(BRAIN_MEMBER, encoded)
        temporary.replace(destination)
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "BrainPack":
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"Migration Brain pack does not exist: {source}")
        try:
            with zipfile.ZipFile(source, "r") as archive:
                members = set(archive.namelist())
                if members != {BRAIN_MEMBER}:
                    raise ValueError("Migration Brain pack contains unsupported or unsafe members.")
                raw = archive.read(BRAIN_MEMBER)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise ValueError(f"Invalid Migration Brain pack: {source}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid Migration Brain metadata: {source}") from exc

        if int(payload.get("schema_version", 0)) not in SUPPORTED_BRAIN_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported Migration Brain schema: {payload.get('schema_version')!r}"
            )

        fingerprint = str(payload.get("fingerprint", ""))
        verify = dict(payload)
        verify["fingerprint"] = ""
        canonical = json.dumps(verify, sort_keys=True, separators=(",", ":")).encode("utf-8")
        actual = hashlib.sha256(canonical).hexdigest()
        if not fingerprint or fingerprint != actual:
            raise ValueError("Migration Brain pack fingerprint verification failed.")

        ranker = payload.get("ranker")
        if not isinstance(ranker, Mapping):
            raise ValueError("Migration Brain pack is missing its trained ranker.")
        LogisticRanker.from_dict(ranker)
        loaded = cls(payload)
        if loaded.contains_source_code:
            raise ValueError("Migration Brain pack must not contain Odoo source code.")
        return loaded


def new_brain_payload(
    *,
    source: int,
    target: int,
    ranker: LogisticRanker,
    steps: Mapping[str, Mapping[str, Any]],
    training: Mapping[str, Any],
    source_identities: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": BRAIN_SCHEMA_VERSION,
        "brain_type": "odoo_migration_brain",
        "source_version": int(source),
        "target_version": int(target),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": "",
        "ranker": ranker.as_dict(),
        "training": dict(training),
        "source_identities": dict(source_identities),
        "knowledge_policy": {
            "source_code_embedded": False,
            "automatic_changes_require_deterministic_transform": True,
            "ambiguous_predictions_are_review_only": True,
        },
        "steps": {key: dict(value) for key, value in steps.items()},
    }
