"""Output formatting and reporting."""

from dataclasses import asdict, dataclass

from rich.console import Console
from rich.table import Table

from . import utils
from .rules import RuleResult

console = Console()


@dataclass
class AnalysisSummary:
    """Summary of query analysis."""

    rule_results: list[RuleResult]
    complexity_score: int
    estimated_rows: int
    estimated_bytes: int
    depth: int
    alias_count: int
    fanout_count: int


def emit(summary: AnalysisSummary, fmt: str) -> None:
    """
    Output analysis summary.

    Args:
        summary: Analysis results
        fmt: Output format ("json" or "console")
    """
    if fmt == "json":
        print(
            utils.to_json({
                "score": summary.complexity_score,
                "depth": summary.depth,
                "aliases": summary.alias_count,
                "fanout": summary.fanout_count,
                "rows": summary.estimated_rows,
                "bytes": summary.estimated_bytes,
                "findings": [asdict(r) for r in summary.rule_results],
            })
        )
    else:
        # Console output with rich
        console.print("\n[bold cyan]Query Analysis Summary[/bold cyan]\n")

        # Metrics table
        table = Table(show_header=False, box=None)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")

        # Depth (warn if > 5)
        depth_icon = "✓" if summary.depth <= 3 else ("⚠" if summary.depth <= 5 else "✖")
        depth_color = "green" if summary.depth <= 3 else ("yellow" if summary.depth <= 5 else "red")
        table.add_row("Depth", f"[{depth_color}]{depth_icon}[/{depth_color}] {summary.depth}")

        # Aliases (warn if > 10)
        alias_icon = "✓" if summary.alias_count <= 10 else "⚠"
        alias_color = "green" if summary.alias_count <= 10 else "yellow"
        table.add_row("Aliases", f"[{alias_color}]{alias_icon}[/{alias_color}] {summary.alias_count}")

        # Fan-out (warn if > 0)
        fanout_icon = "✓" if summary.fanout_count == 0 else "⚠"
        fanout_color = "green" if summary.fanout_count == 0 else "yellow"
        table.add_row("Fan-out", f"[{fanout_color}]{fanout_icon}[/{fanout_color}] {summary.fanout_count}")

        # Complexity (< 50 good, 50-200 moderate, 200-500 high, > 500 critical)
        if summary.complexity_score < 50:
            complexity_icon, complexity_color = "✓", "green"
        elif summary.complexity_score < 200:
            complexity_icon, complexity_color = "⚠", "yellow"
        elif summary.complexity_score < 500:
            complexity_icon, complexity_color = "⚠⚠", "bright_yellow"
        else:
            complexity_icon, complexity_color = "✖", "red"
        table.add_row("Complexity", f"[{complexity_color}]{complexity_icon}[/{complexity_color}] {summary.complexity_score}")

        # Est. Rows
        table.add_row("Est. Rows", f"[dim]{summary.estimated_rows}[/dim]")

        # Est. Bytes
        table.add_row("Est. Bytes", f"[dim]~{summary.estimated_bytes}[/dim]")

        console.print(table)

        # Findings
        if summary.rule_results:
            console.print("\n[bold cyan]Recommendations:[/bold cyan]\n")
            for r in summary.rule_results:
                icon = {
                    "ERROR": "[red]✖[/red]",
                    "WARN": "[yellow]⚠[/yellow]",
                    "INFO": "[blue]•[/blue]",
                }.get(r.severity, "•")

                msg = f"  {icon} [dim]{r.rule_id}[/dim]: {r.message}"
                if r.locations:
                    loc_str = ", ".join([f"line {l}:{c}" for l, c in r.locations])
                    msg += f" [dim]({loc_str})[/dim]"

                console.print(msg)
        else:
            console.print("\n[green]✓ No issues found[/green]")

        console.print()


def print_kv(title: str, data: dict) -> None:
    """
    Print key-value pairs (for schema pull, calibration).

    Args:
        title: Section title
        data: Key-value data
    """
    console.print(f"\n[bold cyan]{title}[/bold cyan]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="yellow")

    for k, v in data.items():
        table.add_row(k, str(v))

    console.print(table)
    console.print()
