from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import xml.etree.ElementTree as ET


@dataclass(frozen=True, slots=True)
class ValidationItem:
    level: str
    code: str
    path: str
    message: str


def validate_project(root: Path) -> tuple[ValidationItem, ...]:
    root = Path(root).resolve(); results: list[ValidationItem] = []
    for path in root.rglob("*.py"):
        try: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeError) as exc:
            results.append(ValidationItem("blocker", "python.syntax", path.relative_to(root).as_posix(), str(exc)))
    for path in root.rglob("*.xml"):
        try: ET.parse(path)
        except (ET.ParseError, OSError) as exc:
            results.append(ValidationItem("blocker", "xml.parse", path.relative_to(root).as_posix(), str(exc)))
    for path in root.rglob("__manifest__.py"):
        try:
            value = ast.literal_eval(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not value.get("name"):
                raise ValueError("manifest must be a dictionary with a name")
        except (SyntaxError, ValueError, UnicodeError) as exc:
            results.append(ValidationItem("blocker", "manifest.invalid", path.relative_to(root).as_posix(), str(exc)))
    return tuple(results)
