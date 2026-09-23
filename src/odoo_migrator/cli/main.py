from __future__ import annotations

from pathlib import Path
import json

import typer
from rich.console import Console
from rich.table import Table

from odoo_migrator.core.planner import build_plan
from odoo_migrator.sources.manager import SourceManager, SourceManagerError
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.analysis.project import scan_custom_addons
from odoo_migrator.analysis.compat import compare_custom_to_target
from odoo_migrator.migrations.engine import MigrationEngine
from odoo_migrator.validation import validate_project
from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.migrations.registry import UnsupportedMigrationPathError
from odoo_migrator.sources.registry import SourceMode
from odoo_migrator.brain import BrainPack, BrainRuntimeMigrator, BrainTrainer

app = typer.Typer(help="Local source-aware Odoo custom-addon migration assistant.")
source_app = typer.Typer(help="Manage local official Odoo Community source snapshots.")
brain_app = typer.Typer(help="Train and use the reusable Migration Brain.")
app.add_typer(source_app, name="source")
app.add_typer(brain_app, name="brain")
console = Console()


def _terminal_text(value: object) -> str:
    """Keep normal CLI output usable on legacy Windows code pages."""
    return str(value).translate({0x2192: "->", 0x2022: "-", 0x2014: "-", 0x2026: "..."})


@app.command()
def plan(
    source: int=typer.Option(..., "--from"),
    target: int=typer.Option(..., "--to"),
):
    try:
        p = build_plan(source, target)
    except ValueError as exc:
        console.print(f"[red]{_terminal_text(exc)}[/red]")
        raise typer.Exit(2)
    console.print(f"[bold]Migration path:[/bold] {_terminal_text(p.path_label)}")
    for step in p.steps:
        console.print(_terminal_text(f"  - {step.source} -> {step.target}"))


@source_app.command("ensure")
def source_ensure(version: int, refresh: bool=False, latest: bool=False):
    mode = SourceMode.LATEST_OFFICIAL_BRANCH if latest else SourceMode.VERIFIED_SNAPSHOT
    try:
        snap = SourceManager().ensure(version, refresh=refresh, mode=mode)
    except SourceManagerError as exc:
        console.print(f"[red]{_terminal_text(exc)}[/red]")
        raise typer.Exit(2)
    console.print(f"[green]Ready[/green] Odoo {snap.branch}")
    console.print(f"Path: {snap.path}")
    console.print(f"Mode: {snap.source_mode.value}")
    console.print(f"Expected commit: {snap.expected_commit or 'none (branch head)'}")
    console.print(f"Actual commit: {snap.actual_commit}")


@source_app.command("info")
def source_info(version: int, latest: bool=False):
    mode = SourceMode.LATEST_OFFICIAL_BRANCH if latest else SourceMode.VERIFIED_SNAPSHOT
    try:
        snap = SourceManager().snapshot(version, mode=mode)
    except SourceManagerError as exc:
        console.print(f"[red]{_terminal_text(exc)}[/red]")
        raise typer.Exit(2)
    if not snap:
        raise typer.Exit("Source snapshot not cached yet.")
    console.print_json(json.dumps(snap.as_dict()))


@brain_app.command("build")
def brain_build(
    output: Path=typer.Option(
        Path.home() / ".odoo-addon-migrator" / "brain" / "migration_brain.omb",
        "--output",
    ),
    source: int=typer.Option(14, "--from"),
    target: int=typer.Option(19, "--to"),
    enterprise: Path | None=typer.Option(
        None,
        "--enterprise",
        help="Optional local Enterprise repo/folder containing version branches or folders.",
    ),
):
    """Train once from official source and write a reusable .omb brain pack."""
    trainer = BrainTrainer()
    try:
        with console.status("Training Migration Brain from Odoo source..."):
            result = trainer.build(
                output,
                source=source,
                target=target,
                enterprise_root=enterprise,
            )
    except (ValueError, SourceManagerError) as exc:
        console.print(f"[red]{_terminal_text(exc)}[/red]")
        raise typer.Exit(2)
    console.print(f"[green]Migration Brain ready:[/green] {result.output}")
    console.print(f"Training samples: {result.training_samples}")
    console.print(f"Method renames learned: {result.method_renames}")
    console.print(f"Model renames learned: {result.model_renames}")
    console.print(f"Dependency renames learned: {result.dependency_renames}")
    console.print_json(json.dumps(result.validation_metrics))


@brain_app.command("info")
def brain_info(path: Path):
    """Inspect a trained Migration Brain without loading any Odoo source."""
    try:
        brain = BrainPack.load(path)
    except ValueError as exc:
        console.print(f"[red]{_terminal_text(exc)}[/red]")
        raise typer.Exit(2)
    payload = brain.payload
    table = Table("Step", "Method renames", "Model renames", "Dependency renames")
    for key, step in payload.get("steps", {}).items():
        table.add_row(
            key,
            str(len(step.get("method_renames", ()))),
            str(len(step.get("model_renames", ()))),
            str(len(step.get("dependency_renames", ()))),
        )
    console.print(f"[bold]Brain fingerprint:[/bold] {brain.fingerprint}")
    console.print(f"[bold]Range:[/bold] Odoo {brain.source} -> {brain.target}")
    console.print(table)
    console.print("[bold]Validation metrics[/bold]")
    console.print_json(json.dumps(payload.get("training", {}).get("validation", {})))


@brain_app.command("migrate")
def brain_migrate(
    addons: Path,
    output: Path,
    brain: Path=typer.Option(..., "--brain"),
    source: int=typer.Option(..., "--from"),
    target: int=typer.Option(..., "--to"),
):
    """Migrate custom addons using only a trained .omb pack; no Odoo source is indexed."""
    try:
        runtime = BrainRuntimeMigrator(brain)
        result = runtime.migrate(
            addons,
            output,
            source=source,
            target=target,
        )
    except (ValueError, FileExistsError) as exc:
        console.print(f"[red]{_terminal_text(exc)}[/red]")
        raise typer.Exit(2)
    console.print(f"[green]Brain migration complete:[/green] {result.output}")
    console.print(f"Changes: {len(result.changes)}")
    console.print(f"Static validation: {result.validation_state}")
    console.print(f"Metadata: {result.metadata_path}")


@app.command()
def analyze(
    addons: Path,
    source: int=typer.Option(..., "--from"),
    target: int=typer.Option(..., "--to"),
):
    try:
        with console.status("Preparing official Odoo snapshots and indexes..."):
            result = AnalysisService().analyze(addons, source, target)
    except UnsupportedMigrationPathError as exc:
        console.print("[red]Migration path is not fully supported.[/red]")
        for step in exc.steps: console.print(_terminal_text(f"  Missing pack: {step.source} -> {step.target}"))
        raise typer.Exit(2)
    except ValueError as exc:
        console.print(f"[red]{_terminal_text(exc)}[/red]")
        raise typer.Exit(2)
    findings = result.findings
    console.print(f"[bold]Path:[/bold] {_terminal_text(result.plan.path_label)}")
    console.print(f"[bold]Custom modules:[/bold] {result.scan.module_count}")
    console.print(f"[bold]Source commit:[/bold] {result.source_snapshot.commit}")
    console.print(f"[bold]Target commit:[/bold] {result.target_snapshot.commit}")
    table = Table("Severity", "Code", "Module", "Message")
    for item in findings:
        table.add_row(item.severity.value, item.code, item.module, item.message)
    console.print(table)
    if not findings:
        console.print("[green]No issues found by the current static checks.[/green]")


@app.command()
def migrate(
    addons: Path,
    output: Path,
    source: int=typer.Option(..., "--from"),
    target: int=typer.Option(..., "--to"),
    dry_run: bool=typer.Option(False, "--dry-run"),
):
    try:
        analysis = AnalysisService().analyze(addons, source, target)
        result = MigrationService().migrate(addons, output, analysis, dry_run=dry_run)
    except UnsupportedMigrationPathError as exc:
        console.print("[red]Migration path is not fully supported.[/red]")
        for step in exc.steps: console.print(_terminal_text(f"  Missing pack: {step.source} -> {step.target}"))
        raise typer.Exit(2)
    except ValueError as exc:
        console.print(f"[red]{_terminal_text(exc)}[/red]")
        raise typer.Exit(2)
    console.print(f"[bold]Path:[/bold] {_terminal_text(result.plan.path_label)}")
    console.print(f"[bold]Changes:[/bold] {len(result.changes)}")
    for change in result.changes:
        console.print(_terminal_text(f"  - {change.path}: {change.description}"))
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
