from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import zipfile

from .ranker import LogisticRanker


BRAIN_SCHEMA_VERSION = 4
BRAIN_MEMBER = "brain.json"
SUPPORTED_BRAIN_SCHEMA_VERSIONS = frozenset({1, 2, 3, BRAIN_SCHEMA_VERSION})


_TOP_LEVEL_KEYS_V3 = frozenset({
    "schema_version", "brain_type", "source_version", "target_version",
    "created_at", "fingerprint", "ranker", "training", "source_identities",
    "knowledge_policy", "steps",
})
_TOP_LEVEL_KEYS_V4 = _TOP_LEVEL_KEYS_V3 | frozenset({
    "pack_kind", "base_fingerprint", "distribution_policy",
    "enterprise_knowledge", "source_leakage_audit",
})
_STEP_KEYS = frozenset({
    "source", "target", "method_renames", "model_renames",
    "dependency_renames", "field_renames", "signature_adapters", "xml_id_renames",
    "js_module_renames", "asset_bundle_renames", "automatic_rules",
    "transformations", "compatibility",
})
_COMPATIBILITY_KEYS = frozenset({
    "removed_modules", "added_modules", "removed_models", "added_models",
    "removed_xml_ids", "added_xml_ids", "removed_js_modules",
    "added_js_modules", "removed_asset_bundles", "added_asset_bundles",
    "changed_view_architectures", "changed_template_architectures",
    "method_moves", "model_ownership_changes", "removed_model_xml_ids",
    "removed_group_xml_ids", "model_changes", "dependency_changes",
})
_TRAINING_KEYS = frozenset({
    "dataset", "validation", "production_validation", "enterprise_versions",
    "method_threshold", "method_margin", "metrics", "split_strategy",
    "history_supervision",
})
_SOURCE_IDENTITY_KEYS = frozenset({
    "version", "community_commit", "community_mode", "community_branch",
    "community_origin", "enterprise", "enterprise_mode", "enterprise_ref",
    "enterprise_commit", "enterprise_source_layer",
})
_TRANSFORMATION_KEYS = frozenset({
    "rule_id", "category", "classification", "automatic", "description", "evidence",
})
_MODEL_CHANGE_KEYS = frozenset({
    "model", "removed_fields", "removed_methods", "signature_changes",
    "signature_details",
})


def _reject_unknown_keys(value: Mapping, allowed: frozenset[str], context: str) -> None:
    unknown = set(map(str, value.keys())) - allowed
    if unknown:
        raise ValueError(
            f"Migration Brain schema contains unsupported keys in {context}: "
            + ", ".join(sorted(unknown))
        )


def _validate_mapping_items(items: Any, allowed: frozenset[str], context: str) -> None:
    if items is None:
        return
    if not isinstance(items, list):
        raise ValueError(f"Migration Brain schema expects a list for {context}.")
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ValueError(f"Migration Brain schema expects objects in {context}.")
        _reject_unknown_keys(item, allowed, f"{context}[{index}]")


def _validate_schema_v3(payload: Mapping[str, Any]) -> None:
    _reject_unknown_keys(payload, _TOP_LEVEL_KEYS_V3, "brain")
    if payload.get("brain_type") != "odoo_migration_brain":
        raise ValueError("Migration Brain schema has an invalid brain_type.")
    try:
        source_version = int(payload["source_version"])
        target_version = int(payload["target_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Migration Brain schema has invalid version metadata.") from exc
    if target_version <= source_version:
        raise ValueError("Migration Brain target version must be higher than source version.")

    ranker = payload.get("ranker")
    if not isinstance(ranker, Mapping):
        raise ValueError("Migration Brain schema is missing ranker metadata.")
    _reject_unknown_keys(
        ranker,
        frozenset({"type", "feature_names", "weights", "bias"}),
        "ranker",
    )

    training = payload.get("training", {})
    if not isinstance(training, Mapping):
        raise ValueError("Migration Brain schema expects training metadata.")
    _reject_unknown_keys(training, _TRAINING_KEYS, "training")

    identities = payload.get("source_identities", {})
    if not isinstance(identities, Mapping):
        raise ValueError("Migration Brain schema expects source identities.")
    for version, identity in identities.items():
        if not isinstance(identity, Mapping):
            raise ValueError(f"Migration Brain source identity {version!r} must be an object.")
        _reject_unknown_keys(identity, _SOURCE_IDENTITY_KEYS, f"source_identities.{version}")

    policy = payload.get("knowledge_policy", {})
    if not isinstance(policy, Mapping):
        raise ValueError("Migration Brain schema expects a knowledge policy.")
    _reject_unknown_keys(
        policy,
        frozenset({
            "source_code_embedded",
            "automatic_changes_require_deterministic_transform",
            "ambiguous_predictions_are_review_only",
        }),
        "knowledge_policy",
    )
    if policy.get("source_code_embedded") is not False:
        raise ValueError("Migration Brain knowledge policy must prohibit embedded source code.")
    if policy.get("automatic_changes_require_deterministic_transform") is not True:
        raise ValueError("Migration Brain automatic changes must require deterministic transforms.")
    if policy.get("ambiguous_predictions_are_review_only") is not True:
        raise ValueError("Migration Brain ambiguous predictions must remain review-only.")

    steps = payload.get("steps")
    if not isinstance(steps, Mapping):
        raise ValueError("Migration Brain schema is missing migration steps.")
    for step_name, step in steps.items():
        if not isinstance(step, Mapping):
            raise ValueError(f"Migration Brain step {step_name!r} must be an object.")
        _reject_unknown_keys(step, _STEP_KEYS, f"steps.{step_name}")
        try:
            step_source = int(step["source"])
            step_target = int(step["target"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Migration Brain step {step_name!r} has invalid versions.") from exc
        expected_name = f"{step_source}_to_{step_target}"
        if step_name != expected_name or step_target != step_source + 1:
            raise ValueError(
                f"Migration Brain step {step_name!r} must describe one adjacent version step."
            )
        if step_source < source_version or step_target > target_version:
            raise ValueError(f"Migration Brain step {step_name!r} is outside the pack range.")

        _validate_mapping_items(
            step.get("method_renames", []),
            frozenset({"model", "from", "to", "confidence", "margin", "features", "evidence"}),
            f"steps.{step_name}.method_renames",
        )
        _validate_mapping_items(
            step.get("model_renames", []),
            frozenset({"from", "to", "confidence", "evidence"}),
            f"steps.{step_name}.model_renames",
        )
        _validate_mapping_items(
            step.get("dependency_renames", []),
            frozenset({"from", "to", "confidence", "evidence"}),
            f"steps.{step_name}.dependency_renames",
        )
        _validate_mapping_items(
            step.get("field_renames", []),
            frozenset({"model", "from", "to", "confidence", "margin", "evidence"}),
            f"steps.{step_name}.field_renames",
        )
        _validate_mapping_items(
            step.get("signature_adapters", []),
            frozenset({
                "model", "method", "source_signature", "target_signature",
                "parameter_renames", "confidence", "evidence",
            }),
            f"steps.{step_name}.signature_adapters",
        )
        for adapter_index, adapter in enumerate(step.get("signature_adapters", [])):
            _validate_mapping_items(
                adapter.get("parameter_renames", []),
                frozenset({"from", "to"}),
                f"steps.{step_name}.signature_adapters[{adapter_index}].parameter_renames",
            )
        _validate_mapping_items(
            step.get("xml_id_renames", []),
            frozenset({"kind", "from", "to", "confidence", "evidence"}),
            f"steps.{step_name}.xml_id_renames",
        )
        _validate_mapping_items(
            step.get("js_module_renames", []),
            frozenset({"from", "to", "confidence", "evidence"}),
            f"steps.{step_name}.js_module_renames",
        )
        _validate_mapping_items(
            step.get("asset_bundle_renames", []),
            frozenset({"from", "to", "confidence", "evidence"}),
            f"steps.{step_name}.asset_bundle_renames",
        )

        transformations = step.get("transformations", [])
        _validate_mapping_items(
            transformations,
            _TRANSFORMATION_KEYS,
            f"steps.{step_name}.transformations",
        )

        compatibility = step.get("compatibility", {})
        if not isinstance(compatibility, Mapping):
            raise ValueError(f"Migration Brain compatibility for {step_name} must be an object.")
        _reject_unknown_keys(
            compatibility,
            _COMPATIBILITY_KEYS,
            f"steps.{step_name}.compatibility",
        )
        _validate_mapping_items(
            compatibility.get("model_changes", []),
            _MODEL_CHANGE_KEYS,
            f"steps.{step_name}.compatibility.model_changes",
        )


def _validate_schema_v4(payload: Mapping[str, Any]) -> None:
    _reject_unknown_keys(payload, _TOP_LEVEL_KEYS_V4, "brain")
    legacy_payload = {
        key: value
        for key, value in payload.items()
        if key in _TOP_LEVEL_KEYS_V3
    }
    legacy_payload["knowledge_policy"] = {
        key: value
        for key, value in payload.get("knowledge_policy", {}).items()
        if key in {
            "source_code_embedded",
            "automatic_changes_require_deterministic_transform",
            "ambiguous_predictions_are_review_only",
        }
    }
    _validate_schema_v3(legacy_payload)

    pack_kind = payload.get("pack_kind")
    if pack_kind not in {"community", "enterprise_composite", "enterprise_overlay"}:
        raise ValueError("Migration Brain schema has an invalid pack_kind.")
    enterprise_knowledge = payload.get("enterprise_knowledge")
    if not isinstance(enterprise_knowledge, bool):
        raise ValueError("Migration Brain schema requires enterprise_knowledge metadata.")
    if pack_kind == "community" and enterprise_knowledge:
        raise ValueError("A Community Brain cannot contain Enterprise knowledge.")
    if pack_kind in {"enterprise_composite", "enterprise_overlay"} and not enterprise_knowledge:
        raise ValueError("An Enterprise Brain pack must declare Enterprise knowledge.")

    base_fingerprint = payload.get("base_fingerprint")
    if pack_kind == "enterprise_overlay":
        if not isinstance(base_fingerprint, str) or len(base_fingerprint) != 64:
            raise ValueError("An Enterprise overlay must bind to a base Brain fingerprint.")
    elif base_fingerprint is not None:
        raise ValueError("Only an Enterprise overlay may define base_fingerprint.")

    expected_policy = (
        "public_community"
        if pack_kind == "community"
        else "local_authorized_use_only"
    )
    if payload.get("distribution_policy") != expected_policy:
        raise ValueError(
            f"Migration Brain {pack_kind} requires distribution_policy={expected_policy!r}."
        )

    policy = payload.get("knowledge_policy", {})
    _reject_unknown_keys(
        policy,
        frozenset({
            "source_code_embedded",
            "enterprise_source_embedded",
            "training_examples_embedded",
            "automatic_changes_require_deterministic_transform",
            "ambiguous_predictions_are_review_only",
        }),
        "knowledge_policy",
    )
    if policy.get("enterprise_source_embedded") is not False:
        raise ValueError("Migration Brain packs must not embed Enterprise source.")
    if policy.get("training_examples_embedded") is not False:
        raise ValueError("Migration Brain packs must not embed raw training examples.")

    audit = payload.get("source_leakage_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("Migration Brain schema requires source leakage audit metadata.")
    _reject_unknown_keys(
        audit,
        frozenset({"status", "files_scanned", "fragments_checked"}),
        "source_leakage_audit",
    )
    if audit.get("status") not in {"not_required", "passed"}:
        raise ValueError("Migration Brain source leakage audit did not pass.")


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
    def pack_kind(self) -> str:
        explicit = self.payload.get("pack_kind")
        if explicit:
            return str(explicit)
        return (
            "enterprise_composite"
            if self.payload.get("training", {}).get("enterprise_versions")
            else "community"
        )

    @property
    def base_fingerprint(self) -> str | None:
        value = self.payload.get("base_fingerprint")
        return str(value) if value else None

    @property
    def enterprise_knowledge(self) -> bool:
        if "enterprise_knowledge" in self.payload:
            return bool(self.payload["enterprise_knowledge"])
        return bool(self.payload.get("training", {}).get("enterprise_versions"))

    @property
    def distribution_policy(self) -> str:
        return str(
            self.payload.get(
                "distribution_policy",
                "local_authorized_use_only"
                if self.enterprise_knowledge
                else "public_community",
            )
        )

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
        enterprise_knowledge = bool(
            payload.get("enterprise_knowledge")
            or payload.get("training", {}).get("enterprise_versions")
        )
        pack_kind = payload.setdefault(
            "pack_kind",
            "enterprise_composite" if enterprise_knowledge else "community",
        )
        payload.setdefault("base_fingerprint", None)
        payload.setdefault("enterprise_knowledge", enterprise_knowledge)
        payload.setdefault(
            "distribution_policy",
            "public_community" if pack_kind == "community" else "local_authorized_use_only",
        )
        policy = dict(payload.get("knowledge_policy", {}))
        policy.setdefault("enterprise_source_embedded", False)
        policy.setdefault("training_examples_embedded", False)
        payload["knowledge_policy"] = policy
        payload.setdefault(
            "source_leakage_audit",
            {
                "status": "not_required" if not enterprise_knowledge else "pending",
                "files_scanned": 0,
                "fragments_checked": 0,
            },
        )
        _validate_schema_v4(payload)
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
        if int(payload.get("schema_version", 0)) >= 4:
            _validate_schema_v4(payload)
        elif int(payload.get("schema_version", 0)) >= 3:
            _validate_schema_v3(payload)
        return loaded


def new_brain_payload(
    *,
    source: int,
    target: int,
    ranker: LogisticRanker,
    steps: Mapping[str, Mapping[str, Any]],
    training: Mapping[str, Any],
    source_identities: Mapping[str, Any],
    pack_kind: str = "community",
    base_fingerprint: str | None = None,
    source_leakage_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    enterprise_knowledge = pack_kind in {"enterprise_composite", "enterprise_overlay"}
    return {
        "schema_version": BRAIN_SCHEMA_VERSION,
        "brain_type": "odoo_migration_brain",
        "source_version": int(source),
        "target_version": int(target),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": "",
        "pack_kind": pack_kind,
        "base_fingerprint": base_fingerprint,
        "distribution_policy": (
            "local_authorized_use_only" if enterprise_knowledge else "public_community"
        ),
        "enterprise_knowledge": enterprise_knowledge,
        "ranker": ranker.as_dict(),
        "training": dict(training),
        "source_identities": dict(source_identities),
        "knowledge_policy": {
            "source_code_embedded": False,
            "enterprise_source_embedded": False,
            "training_examples_embedded": False,
            "automatic_changes_require_deterministic_transform": True,
            "ambiguous_predictions_are_review_only": True,
        },
        "source_leakage_audit": dict(source_leakage_audit or {
            "status": "not_required" if not enterprise_knowledge else "pending",
            "files_scanned": 0,
            "fragments_checked": 0,
        }),
        "steps": {key: dict(value) for key, value in steps.items()},
    }
