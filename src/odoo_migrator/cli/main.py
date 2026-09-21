from __future__ import annotations

from pathlib import Path
import json

import typer
from rich.console import Console
from rich.table import Table

from odoo_migrator.core.planner import build_plan
from odoo_migrator.sources.manager import SourceManager
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.analysis.project import scan_custom_addons
from odoo_migrator.analysis.compat import compare_custom_to_target
from odoo_migrator.migrations.engine import MigrationEngine
from odoo_migrator.validation import validate_project

app = typer.Typer(help="Local source-aware Odoo custom-addon migration assistant.")
source_app = typer.Typer(help="Manage local official Odoo Community source snapshots.")
app.add_typer(source_app, name="source")
console = Console()


@app.command()
def plan(
    source: int = typer.Option(..., "--from"),
    target: int = typer.Option(..., "--to"),
):
    p = build_plan(source, target)
    console.print(f"[bold]Migration path:[/bold] {p.path_label}")
    for step in p.steps:
        console.print(f"  • {step.source} → {step.target}")


@source_app.command("ensure")
def source_ensure(version: int, refresh: bool = False):
    snap = SourceManager().ensure(version, refresh=refresh)
    console.print(f"[green]Ready[/green] Odoo {snap.branch}")
    console.print(f"Path: {snap.path}")
    console.print(f"Commit: {snap.commit}")


@source_app.command("info")
def source_info(version: int):
    snap = SourceManager().snapshot(version)
    if not snap:
        raise typer.Exit("Source snapshot not cached yet.")
    console.print_json(json.dumps(snap.as_dict()))


@app.command()
def analyze(
    addons: Path,
    source: int = typer.Option(..., "--from"),
    target: int = typer.Option(..., "--to"),
):
    plan = build_plan(source, target)
    manager = SourceManager()
    src_snap = manager.snapshot(source)
    dst_snap = manager.snapshot(target)
    if not src_snap or not dst_snap:
        console.print("[red]Both source and target Odoo snapshots must be cached first.[/red]")
        console.print(f"Run: odoo-migrator source ensure {source}")
        console.print(f"Run: odoo-migrator source ensure {target}")
        raise typer.Exit(2)

    custom = scan_custom_addons(addons)
    indexer = SourceIndexer()
    with console.status(f"Indexing Odoo {source} source..."):
        src_index = indexer.index(src_snap.path)
    with console.status(f"Indexing Odoo {target} source..."):
        dst_index = indexer.index(dst_snap.path)

    findings = compare_custom_to_target(custom.index, src_index, dst_index)
    console.print(f"[bold]Path:[/bold] {plan.path_label}")
    console.print(f"[bold]Custom modules:[/bold] {custom.module_count}")
    table = Table("Severity", "Code", "Module", "Message")
    for item in findings:
        table.add_row(item.severity.value, item.code, item.module, item.message)
    console.print(table)
    if not findings:
        console.print("[green]No issues found by the current v0.1 checks.[/green]")


@app.command()
def migrate(
    addons: Path,
    output: Path,
    source: int = typer.Option(..., "--from"),
    target: int = typer.Option(..., "--to"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    result = MigrationEngine().migrate(addons, output, source, target, dry_run=dry_run)
    console.print(f"[bold]Path:[/bold] {result.plan.path_label}")
    console.print(f"[bold]Changes:[/bold] {len(result.changes)}")
    for change in result.changes:
        console.print(f"  • {change.path}: {change.description}")
    if not dry_run:
        console.print(f"[green]Migrated copy:[/green] {result.output}")


@app.command()
def validate(path: Path):
    """Run static validation; this does not prove target runtime compatibility."""
    items = validate_project(path)
    if not items:
        console.print("[green]Static validation passed.[/green]")
        return
    table = Table("Level", "Code", "Path", "Message")
    for item in items:
        table.add_row(item.level, item.code, item.path, item.message)
    console.print(table)
    raise typer.Exit(1)
