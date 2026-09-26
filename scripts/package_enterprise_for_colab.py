from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import time
import zipfile

from odoo_migrator.sources.enterprise import resolve_enterprise_source


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package authorized Enterprise source as Colab-friendly version archives."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-version", type=int, default=14)
    parser.add_argument("--to-version", type=int, default=19)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _excluded(relative: Path) -> bool:
    return (
        ".git" in relative.parts
        or "__pycache__" in relative.parts
        or relative.suffix.casefold() in {".pyc", ".pyo"}
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_version(
    source_root: Path,
    output_dir: Path,
    version: int,
    *,
    force: bool = False,
) -> Path:
    resolution = resolve_enterprise_source(source_root, version)
    source = resolution.source_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"odoo-enterprise-{version}.0.zip"
    if destination.exists() and not force:
        raise FileExistsError(
            f"Archive already exists: {destination}. Use --force to rebuild it."
        )
    if output_dir == source or source in output_dir.parents:
        raise ValueError("Archive output must not be placed inside Enterprise source.")

    files = [
        path
        for path in source.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not _excluded(path.relative_to(source))
    ]
    files.sort(key=lambda item: item.relative_to(source).as_posix())
    if not any(path.name == "__manifest__.py" for path in files):
        raise ValueError(f"No addon manifests found for Enterprise Odoo {version}: {source}")

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    started = time.perf_counter()
    print(
        f"Odoo {version}: packaging {len(files):,} files from {source}",
        flush=True,
    )
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for index, path in enumerate(files, start=1):
                relative = path.relative_to(source)
                archive.write(path, (Path(f"{version}.0") / relative).as_posix())
                if index % 2000 == 0 or index == len(files):
                    elapsed = time.perf_counter() - started
                    print(
                        f"Odoo {version}: {index:,}/{len(files):,} files "
                        f"({index / len(files) * 100:.1f}%) elapsed {elapsed:.1f}s",
                        flush=True,
                    )
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(
        f"Odoo {version}: ready {destination} "
        f"({destination.stat().st_size / 1024 / 1024:.1f} MiB)",
        flush=True,
    )
    return destination


def main() -> int:
    args = _parse_args()
    if args.to_version < args.from_version:
        raise ValueError("Target version must not be lower than source version.")
    archives = [
        package_version(
            args.source.expanduser(),
            args.output.expanduser(),
            version,
            force=args.force,
        )
        for version in range(args.from_version, args.to_version + 1)
    ]
    checksum_path = args.output.expanduser().resolve() / "SHA256SUMS.txt"
    checksum_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in archives),
        encoding="utf-8",
    )
    print(f"Checksums: {checksum_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
