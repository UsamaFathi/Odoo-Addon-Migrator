from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import ast
import json
import xml.etree.ElementTree as ET
import hashlib
import inspect
import re

INDEX_SCHEMA_VERSION = 4


@dataclass(slots=True)
class ModelInfo:
    name: str
    methods: set[str] = field(default_factory=set)
    fields: set[str] = field(default_factory=set)
    inherits: set[str] = field(default_factory=set)
    delegated_inherits: set[str] = field(default_factory=set)
    signatures: dict[str, str] = field(default_factory=dict)
    source_path: str | None = None
    line: int | None = None
    method_locations: dict[str, tuple[str, int]] = field(default_factory=dict)
    field_locations: dict[str, tuple[str, int]] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"name": self.name, "methods": sorted(self.methods), "fields": sorted(self.fields),
                "inherits": sorted(self.inherits), "delegated_inherits": sorted(self.delegated_inherits), "signatures": self.signatures,
                "source_path": self.source_path, "line": self.line, "method_locations": self.method_locations,
                "field_locations": self.field_locations}


@dataclass(slots=True)
class ViewInfo:
    xml_id: str
    inherit_id: str | None = None
    xpaths: tuple[str, ...] = ()
    architecture: str = ""

    def to_json(self) -> dict:
        return {"xml_id": self.xml_id, "inherit_id": self.inherit_id, "xpaths": list(self.xpaths), "architecture": self.architecture}


@dataclass(slots=True)
class ModuleInfo:
    name: str
    path: str
    depends: list[str] = field(default_factory=list)
    models: dict[str, ModelInfo] = field(default_factory=dict)
    xml_ids: set[str] = field(default_factory=set)
    manifest: dict = field(default_factory=dict)
    files: dict[str, int] = field(default_factory=dict)
    controllers: dict[str, list[str]] = field(default_factory=dict)
    assets: set[str] = field(default_factory=set)
    views: dict[str, ViewInfo] = field(default_factory=dict)
    model_xml_ids: dict[str, str] = field(default_factory=dict)
    defined_models: set[str] = field(default_factory=set)
    js_modules: set[str] = field(default_factory=set)
    js_dependencies: set[str] = field(default_factory=set)

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "depends": self.depends,
            "models": {k: v.to_json() for k, v in self.models.items()},
            "xml_ids": sorted(self.xml_ids),
            "manifest": self.manifest,
            "files": self.files,
            "controllers": self.controllers,
            "assets": sorted(self.assets),
            "views": {k: v.to_json() for k, v in self.views.items()},
            "model_xml_ids": self.model_xml_ids,
            "defined_models": sorted(self.defined_models),
            "js_modules": sorted(self.js_modules),
            "js_dependencies": sorted(self.js_dependencies),
        }


@dataclass(slots=True)
class OdooIndex:
    root: str
    modules: dict[str, ModuleInfo]
    schema_version: int = INDEX_SCHEMA_VERSION
    source_commit: str | None = None

    @property
    def models(self) -> dict[str, ModelInfo]:
        merged: dict[str, ModelInfo] = {}
        for module in self.modules.values():
            for name, info in module.models.items():
                item = merged.setdefault(name, ModelInfo(name))
                item.methods.update(info.methods)
                item.fields.update(info.fields)
                item.inherits.update(info.inherits)
                item.delegated_inherits.update(info.delegated_inherits)
                item.signatures.update(info.signatures)
                item.method_locations.update(info.method_locations)
                item.field_locations.update(info.field_locations)
                if not item.source_path: item.source_path, item.line = info.source_path, info.line
        return merged

    @property
    def xml_ids(self) -> set[str]:
        ids: set[str] = set()
        for module in self.modules.values():
            ids.update(module.xml_ids)
        return ids

    @property
    def model_xml_ids(self) -> dict[str, str]:
        return {xml_id: model for module in self.modules.values() for xml_id, model in module.model_xml_ids.items()}

    @property
    def js_modules(self) -> set[str]:
        return {name for module in self.modules.values() for name in module.js_modules}

    def resolve_model_external_id(self, external_id: str) -> str | None:
        """Resolve Odoo's generated model IDs without assuming one module.

        Odoo's access CSVs commonly use ``model_sale_order`` while XML IDs are
        also addressable as ``base.model_sale_order`` (or the defining custom
        module). We accept explicit indexed mappings first, then generated
        aliases only when they identify exactly one indexed technical model.
        """
        value = external_id.strip()
        explicit = self.model_xml_ids
        if value in explicit:
            return explicit[value]
        if "." in value:
            return None
        short = value.rsplit(".", 1)[-1]
        if not short.startswith("model_"):
            return None
        candidate = short[6:].replace("_", ".")
        matches = [name for name in self.models if name == candidate]
        return matches[0] if len(matches) == 1 else None

    def save(self, path: Path) -> None:
        data = {"schema_version": self.schema_version, "source_commit": self.source_commit,
                "root": self.root, "modules": {k: v.to_json() for k, v in self.modules.items()}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class SourceIndexer:
    """Lightweight static indexer. It intentionally avoids importing Odoo."""

    def index(self, root: Path, source_commit: str | None = None, cache_dir: Path | None = None) -> OdooIndex:
        root = Path(root).resolve()
        fingerprint = source_commit or self.project_fingerprint(root)
        cache_key = hashlib.sha256(f"{root}|{fingerprint}|{INDEX_SCHEMA_VERSION}".encode()).hexdigest()[:24]
        cache_path = Path(cache_dir or Path.home() / ".odoo-addon-migrator" / "indexes") / f"{cache_key}.json"
        if cache_path.exists():
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if data.get("schema_version") == INDEX_SCHEMA_VERSION and data.get("source_commit") == source_commit:
                if source_commit is not None or data.get("project_fingerprint") == fingerprint:
                    return self._from_json(data)
        modules: dict[str, ModuleInfo] = {}
        for manifest in root.rglob("__manifest__.py"):
            if ".git" in manifest.parts:
                continue
            module_dir = manifest.parent
            module = ModuleInfo(name=module_dir.name, path=str(module_dir))
            module.manifest = self._manifest(manifest)
            module.depends = [str(x) for x in module.manifest.get("depends", [])]
            module.files = {"python": len(list(module_dir.rglob("*.py"))),
                            "xml": len(list(module_dir.rglob("*.xml"))),
                            "javascript": len(list(module_dir.rglob("*.js"))),
                            "csv": len(list(module_dir.rglob("*.csv")))}
            module.assets = {str(path.relative_to(module_dir)) for path in module_dir.rglob("*")
                             if path.is_file() and ("static" in path.parts or "assets" in path.parts)}
            self._scan_python(module_dir, module)
            self._scan_xml(module_dir, module)
            self._scan_javascript(module_dir, module)
            self._add_generated_model_ids(module)
            modules[module.name] = module
        result = OdooIndex(root=str(root), modules=modules, source_commit=source_commit)
        result.save(cache_path)
        payload = json.loads(cache_path.read_text(encoding="utf-8")); payload["project_fingerprint"] = fingerprint
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return result

    @staticmethod
    def project_fingerprint(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(str(path.stat().st_size).encode())
            digest.update(str(path.stat().st_mtime_ns).encode())
        return digest.hexdigest()

    @staticmethod
    def _manifest(path: Path) -> dict:
        try:
            value = ast.literal_eval(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (SyntaxError, ValueError, OSError):
            return {}

    @staticmethod
    def _add_generated_model_ids(module: ModuleInfo) -> None:
        for model_name in module.defined_models:
            generated = f"model_{model_name.replace('.', '_')}"
            module.model_xml_ids.setdefault(generated, model_name)
            module.model_xml_ids.setdefault(f"{module.name}.{generated}", model_name)

    @staticmethod
    def _from_json(data: dict) -> OdooIndex:
        modules = {}
        for name, raw in data.get("modules", {}).items():
            info = ModuleInfo(name=name, path=raw["path"], depends=raw.get("depends", []), xml_ids=set(raw.get("xml_ids", [])),
                              manifest=raw.get("manifest", {}), files=raw.get("files", {}), controllers=raw.get("controllers", {}), assets=set(raw.get("assets", [])),
                              views={key: ViewInfo(value["xml_id"], value.get("inherit_id"), tuple(value.get("xpaths", [])), value.get("architecture", "")) for key, value in raw.get("views", {}).items()},
                              model_xml_ids=raw.get("model_xml_ids", {}), defined_models=set(raw.get("defined_models", [])),
                              js_modules=set(raw.get("js_modules", [])), js_dependencies=set(raw.get("js_dependencies", [])))
            for model, model_raw in raw.get("models", {}).items():
                info.models[model] = ModelInfo(model, set(model_raw.get("methods", [])), set(model_raw.get("fields", [])),
                                               set(model_raw.get("inherits", [])), set(model_raw.get("delegated_inherits", [])), model_raw.get("signatures", {}),
                                               model_raw.get("source_path"), model_raw.get("line"),
                                               {k: tuple(v) for k, v in model_raw.get("method_locations", {}).items()},
                                               {k: tuple(v) for k, v in model_raw.get("field_locations", {}).items()})
            modules[name] = info
        return OdooIndex(data.get("root", ""), modules, data.get("schema_version", INDEX_SCHEMA_VERSION), data.get("source_commit"))

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
                model_names, inherited, delegated, declared = self._model_definition(node)
                if not model_names:
                    continue
                module.defined_models.update(declared)
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
                    relative_path = path.relative_to(module_dir).as_posix()
                    if not info.source_path:
                        info.source_path, info.line = relative_path, node.lineno
                    info.methods.update(methods)
                    info.fields.update(fields)
                    info.inherits.update(inherited)
                    info.delegated_inherits.update(delegated)
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            info.signatures[child.name] = str(inspect.Signature.from_callable(lambda: None)) if False else ast.unparse(child.args)
                            info.method_locations[child.name] = (relative_path, child.lineno)
                    for child in node.body:
                        if isinstance(child, (ast.Assign, ast.AnnAssign)):
                            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                            if self._is_fields_call(child.value):
                                for target in targets:
                                    if isinstance(target, ast.Name): info.field_locations[target.id] = (relative_path, child.lineno)

    @staticmethod
    def _literal_strings(value: ast.AST | None) -> list[str]:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return [value.value]
        if isinstance(value, (ast.List, ast.Tuple)):
            return [elt.value for elt in value.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
        return []

    def _model_definition(self, node: ast.ClassDef) -> tuple[list[str], list[str], list[str], list[str]]:
        declared: list[str] = []; inherited: list[str] = []; delegated: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == "_name": declared.extend(self._literal_strings(stmt.value))
                    elif target.id == "_inherit": inherited.extend(self._literal_strings(stmt.value))
                    elif target.id == "_inherits" and isinstance(stmt.value, ast.Dict):
                        for key in stmt.value.keys:
                            delegated.extend(self._literal_strings(key))
        # An extension (_inherit only) defines members on the inherited model;
        # a named model has exactly its own effective technical model name.
        effective = declared if declared else inherited
        return list(dict.fromkeys(effective)), list(dict.fromkeys(inherited)), list(dict.fromkeys(delegated)), list(dict.fromkeys(declared))

    @staticmethod
    def _is_fields_call(value: ast.AST | None) -> bool:
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute):
            return False
        obj = value.func.value
        return isinstance(obj, ast.Name) and obj.id == "fields"

    @classmethod
    def _scan_javascript(cls, module_dir: Path, module: ModuleInfo) -> None:
        for path in module_dir.rglob("*.js"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            code = cls._strip_js_comments(text)
            module.js_modules.update(re.findall(r"\bodoo\.define\s*\(\s*['\"]([^'\"]+)['\"]", code))
            module.js_modules.update(re.findall(r"@odoo-module\s+alias\s*=\s*([^\s*]+)", text))
            module.js_dependencies.update(cls.javascript_dependencies(text))

    @classmethod
    def javascript_dependencies(cls, text: str) -> set[str]:
        code = cls._strip_js_comments(text)
        dependencies = set(re.findall(r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", code))
        dependencies.update(re.findall(r"\bfrom\s+['\"]([^'\"]+)['\"]", code))
        dependencies.update(re.findall(r"\bimport\s+['\"]([^'\"]+)['\"]", code))
        return dependencies

    @staticmethod
    def _strip_js_comments(text: str) -> str:
        output = []; index = 0; quote = None
        while index < len(text):
            char = text[index]; nxt = text[index + 1] if index + 1 < len(text) else ""
            if quote:
                output.append(char)
                if char == "\\" and nxt:
                    output.append(nxt); index += 2; continue
                if char == quote: quote = None
                index += 1; continue
            if char in {"'", '"', "`"}:
                quote = char; output.append(char); index += 1; continue
            if char == "/" and nxt == "/":
                index += 2
                while index < len(text) and text[index] not in "\r\n": index += 1
                output.append("\n"); continue
            if char == "/" and nxt == "*":
                index += 2
                while index + 1 < len(text) and text[index:index + 2] != "*/": index += 1
                index += 2; output.append(" "); continue
            output.append(char); index += 1
        return "".join(output)

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
                if elem.tag == "record" and elem.attrib.get("model") == "ir.ui.view" and xml_id:
                    inherit_id = None; xpaths = []; architecture = ""
                    for field in elem.findall("field"):
                        if field.attrib.get("name") == "inherit_id": inherit_id = field.attrib.get("ref")
                        if field.attrib.get("name") == "arch":
                            xpaths = [node.attrib.get("expr", "") for node in field.iter("xpath") if node.attrib.get("expr")]
                            architecture = "".join(ET.tostring(child, encoding="unicode") for child in field)
                    module.views[f"{module.name}.{xml_id}"] = ViewInfo(f"{module.name}.{xml_id}", inherit_id, tuple(xpaths), architecture)
                if elem.tag == "record" and elem.attrib.get("model") == "ir.model" and xml_id:
                    model_field = next((field.text for field in elem.findall("field") if field.attrib.get("name") == "model"), None)
                    if model_field:
                        module.model_xml_ids[f"{module.name}.{xml_id}"] = model_field.strip()
