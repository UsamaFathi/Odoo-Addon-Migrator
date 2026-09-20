from __future__ import annotations

SUPPORTED_MAJORS = tuple(range(14, 20))


def normalize_version(value: int | str) -> int:
    if isinstance(value, int):
        version = value
    else:
        raw = str(value).strip().lower().removeprefix("v")
        raw = raw.split(".", 1)[0]
        if not raw.isdigit():
            raise ValueError(f"Invalid Odoo version: {value!r}")
        version = int(raw)
    if version not in SUPPORTED_MAJORS:
        raise ValueError(
            f"Unsupported Odoo version {version}. Supported: "
            + ", ".join(map(str, SUPPORTED_MAJORS))
        )
    return version


def branch(version: int | str) -> str:
    return f"{normalize_version(version)}.0"
