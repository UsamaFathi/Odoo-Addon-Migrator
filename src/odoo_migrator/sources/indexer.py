from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import ast
import json
import xml.etree.ElementTree as ET


@dataclass(slots=True)
class ModelInfo:
    name: str
    methods: set[str] = field(default_factory=set)
    fields: set[str] = field(default_factory=set)

    def to_json(self) -> dict:
        return {"name": self.name, "methods": sorted(self.methods), "fields": sorted(self.fields)}


@dataclass(slots=True)
class ModuleInfo:
    name: str
    path: str
    depends: list[str] = field(default_factory=list)
    models: dict[str, ModelInfo] = field(default_factory=dict)
    xml_ids: set[str] = field(default_factory=set)

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "depends": self.depends,
            "models": {k: v.to_json() for k, v in self.models.items()},
            "xml_ids": sorted(self.xml_ids),
        }


@dataclass(slots=True)
class OdooIndex:
    root: str
    modules: dict[str, ModuleInfo]

    @property
    def models(self) -> dict[str, ModelInfo]:
        merged: dict[str, ModelInfo] = {}
        for module in self.modules.values():
            for name, info in module.models.items():
                item = merged.setdefault(name, ModelInfo(name))
                item.methods.update(info.methods)
                item.fields.update(info.fields)
        return merged

    @property
    def xml_ids(self) -> set[str]:
        ids: set[str] = set()
        for module in self.modules.values():
            ids.update(module.xml_ids)
        return ids

    def save(self, path: Path) -> None:
        data = {"root": self.root, "modules": {k: v.to_json() for k, v in self.modules.items()}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class SourceIndexer:
    """Lightweight static indexer. It intentionally avoids importing Odoo."""

    def index(self, root: Path) -> OdooIndex:
        root = Path(root).resolve()
        modules: dict[str, ModuleInfo] = {}
        for manifest in root.rglob("__manifest__.py"):
            if ".git" in manifest.parts:
                continue
            module_dir = manifest.parent
            module = ModuleInfo(name=module_dir.name, path=str(module_dir))
            module.depends = self._manifest_depends(manifest)
            self._scan_python(module_dir, module)
            self._scan_xml(module_dir, module)
            modules[module.name] = module
        return OdooIndex(root=str(root), modules=modules)

    @staticmethod
    def _manifest_depends(path: Path) -> list[str]:
        try:
            value = ast.literal_eval(path.read_text(encoding="utf-8"))
            deps = value.get("depends", []) if isinstance(value, dict) else []
            return [str(x) for x in deps]
        except Exception:
            return []

    def _scan_python(self, module_dir: Path, module: ModuleInfo) -> None:
        for path in module_dir.rglob("*.py"):
            if path.name == "__manifest__.py" or "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
            except SyntaxError:
                continue
            for node in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                model_names = self._model_names(node)
                if not model_names:
                    continue
                methods = {n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                fields = set()
                for n in node.body:
                    if isinstance(n, (ast.Assign, ast.AnnAssign)):
                        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                        value = n.value
                        if self._is_fields_call(value):
                            for target in targets:
                                if isinstance(target, ast.Name):
                                    fields.add(target.id)
                for model_name in model_names:
                    info = module.models.setdefault(model_name, ModelInfo(model_name))
                    info.methods.update(methods)
                    info.fields.update(fields)

    @staticmethod
    def _literal_strings(value: ast.AST | None) -> list[str]:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return [value.value]
        if isinstance(value, (ast.List, ast.Tuple)):
            return [elt.value for elt in value.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
        return []

    def _model_names(self, node: ast.ClassDef) -> list[str]:
        names: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id in {"_name", "_inherit"}:
                        names.extend(self._literal_strings(stmt.value))
        return list(dict.fromkeys(names))

    @staticmethod
    def _is_fields_call(value: ast.AST | None) -> bool:
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute):
            return False
        obj = value.func.value
        return isinstance(obj, ast.Name) and obj.id == "fields"

    @staticmethod
    def _scan_xml(module_dir: Path, module: ModuleInfo) -> None:
        for path in module_dir.rglob("*.xml"):
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError:
                continue
            for elem in root.iter():
                xml_id = elem.attrib.get("id")
                if xml_id:
                    module.xml_ids.add(f"{module.name}.{xml_id}")
