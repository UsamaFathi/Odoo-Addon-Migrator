from pathlib import Path

from odoo_migrator.validation import validate_project


def test_validation_detects_python_and_xml_errors(tmp_path: Path):
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "bad.xml").write_text("<odoo>", encoding="utf-8")
    codes = {item.code for item in validate_project(tmp_path)}
    assert codes == {"python.syntax", "xml.parse"}


def test_validation_accepts_basic_manifest(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir()
    (addon / "__manifest__.py").write_text("{'name': 'Demo', 'depends': []}\n", encoding="utf-8")
    assert validate_project(tmp_path) == ()
