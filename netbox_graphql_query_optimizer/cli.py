"""CLI for netbox-gqo."""

import sys
from dataclasses import dataclass
from typing import Literal, Optional

import typer
from rich.console import Console

from . import calibrate as calibrate_mod
from . import config, cost, inspector, parser, rules, schema_loader, utils
from .report import AnalysisSummary, emit, print_kv

app = typer.Typer(help="NetBox GraphQL Query Optimizer")
schema_app = typer.Typer(help="Schema operations")
app.add_typer(schema_app, name="schema")

console = Console()


@dataclass
class AnalyzeOptions:
    """Options for analyze command."""

    url: Optional[str] = None
    schema_file: Optional[str] = None
    calibration_file: Optional[str] = None
    output: Literal["console", "json"] = "console"
    fail_on_score: Optional[int] = None
    fail_on_error: bool = False
    score_only: bool = False


@schema_app.command("pull")
def schema_pull(
    url: Optional[str] = typer.Option(None, help="NetBox base URL"),
    token: Optional[str] = typer.Option(None, help="API token"),
    out: Optional[str] = typer.Option(None, help="Output file path"),
):
    """Fetch and cache the GraphQL schema from NetBox."""
    try:
        cfg = config.load()
        full_url = utils.ensure_graphql_url(url or cfg.default_url)

        if not full_url or full_url == "None/graphql/":
            console.print("[red]Error: No URL provided. Use --url or set default_url in config.[/red]")
            raise typer.Exit(1)

        console.print(f"[cyan]Fetching schema from {full_url}...[/cyan]")
        profile = schema_loader.load_schema(url=full_url, cfg=cfg, allow_cache=True, refresh=True, token=token)

        # If custom output path specified, write just the schema JSON
        if out:
            utils.write_json(out, profile.schema_json)
            path = out
        else:
            path = schema_loader.cache_path_for(profile.url, cfg)

        print_kv("Schema pulled", {"url": profile.url, "hash": profile.hash, "path": path})
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command("calibrate")
def calibrate_cmd(
    url: Optional[str] = typer.Option(None, help="NetBox base URL"),
    token: Optional[str] = typer.Option(None, help="API token"),
    query: Optional[str] = typer.Option(None, help="Query file to analyze for types"),
    out: Optional[str] = typer.Option(None, help="Output file path"),
):
    """Calibrate cardinality estimates from NetBox REST API."""
    try:
        cfg = config.load()
        base_url = url or cfg.default_url

        if not base_url:
            console.print("[red]Error: No URL provided. Use --url or set default_url in config.[/red]")
            raise typer.Exit(1)

        # Determine which types to probe
        types_to_probe = None
        if query:
            console.print(f"[cyan]Analyzing query to determine types...[/cyan]")
            doc = parser.parse_query(utils.read_text(query))
            full_url = utils.ensure_graphql_url(base_url)
            profile = schema_loader.load_schema(url=full_url, cfg=cfg, allow_cache=True)
            schema = parser.build_schema(profile.schema_json)
            types_to_probe = inspector.extract_list_types(doc, schema)
            console.print(f"[cyan]Found {len(types_to_probe)} list types in query[/cyan]")

        console.print(f"[cyan]Probing REST API at {base_url}...[/cyan]")
        calib = calibrate_mod.calibrate(base_url, token, types_to_probe, cfg)

        path = out or calibrate_mod.cache_path_for(base_url, cfg)
        utils.ensure_dir(utils.dirname(path))
        utils.write_json(path, calib)

        print_kv("Calibration saved", {**calib, "path": path})
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command("analyze")
def analyze_cmd(
    query_file: str = typer.Argument(..., help="GraphQL query file"),
    url: Optional[str] = typer.Option(None, help="NetBox base URL"),
    schema: Optional[str] = typer.Option(None, help="Schema file path"),
    calibration: Optional[str] = typer.Option(None, help="Calibration file path"),
    output: str = typer.Option("console", help="Output format (console|json)"),
    fail_on_score: Optional[int] = typer.Option(None, help="Exit code 2 if score exceeds threshold"),
    fail_on_error: bool = typer.Option(False, help="Exit code 2 if any ERROR-level findings"),
    score_only: bool = typer.Option(False, help="Print only numeric score"),
):
    """Analyze a GraphQL query for performance issues."""
    try:
        opts = AnalyzeOptions(
            url=url,
            schema_file=schema,
            calibration_file=calibration,
            output=output,
            fail_on_score=fail_on_score,
            fail_on_error=fail_on_error,
            score_only=score_only,
        )

        summary = run_analyze(query_file, opts)

        if score_only:
            print(summary.complexity_score)
        else:
            emit(summary, output)

        # Check exit conditions
        exit_code = 0
        if fail_on_score and summary.complexity_score > fail_on_score:
            exit_code = 2
        if fail_on_error and any(r.severity == "ERROR" for r in summary.rule_results):
            exit_code = 2

        if exit_code != 0:
            raise typer.Exit(exit_code)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if "--debug" in sys.argv:
            raise
        raise typer.Exit(1)


def run_analyze(query_path: str, opts: AnalyzeOptions) -> AnalysisSummary:
    """
    Run analysis on a query file.

    Args:
        query_path: Path to GraphQL query file
        opts: Analysis options

    Returns:
        AnalysisSummary with results
    """
    cfg = config.load()

    # Ensure URL has /graphql/ suffix
    url = None
    if opts.url or cfg.default_url:
        url = utils.ensure_graphql_url(opts.url or cfg.default_url)

    # Load schema (introspection or file)
    profile = schema_loader.load_schema(url=url, schema_file=opts.schema_file, cfg=cfg, allow_cache=True)
    schema = parser.build_schema(profile.schema_json)

    # Parse query
    doc = parser.parse_query(utils.read_text(query_path))

    # Validate query against schema
    validation_errors = parser.validate_query(doc, schema)

    # Collect AST stats
    stats = inspector.collect_stats(doc, schema)

    # Run rules
    findings = []
    if validation_errors:
        findings.extend(rules.schema_validation_findings(validation_errors))

    findings.extend(rules.rule_pagination_required(doc, schema, stats, cfg))
    findings.extend(rules.rule_alias_cap(doc, schema, stats, cfg))
    findings.extend(rules.rule_depth_breadth(doc, schema, stats, cfg))
    findings.extend(rules.rule_fanout(doc, schema, stats, cfg))
    findings.extend(rules.rule_filter_pushdown(doc, schema, stats, cfg))
    findings.extend(rules.rule_overfetch(doc, schema, stats, cfg))

    # Load calibration (optional)
    base_url = utils.base_url_from_graphql(profile.url)
    calib = calibrate_mod.load_calibration(opts.calibration_file) or calibrate_mod.load_cached_for(
        base_url, cfg
    )

    # Score & estimates
    weights = cost.default_weights(cfg)
    cardinality = cost.build_cardinality_map(stats, calib, cfg)
    complexity = cost.score(doc, schema, weights, cardinality, cfg)
    est_rows = cost.estimate_rows(stats, cardinality, cfg)
    est_bytes = cost.estimate_bytes(est_rows, stats.avg_fields_per_node)

    return AnalysisSummary(
        rule_results=findings,
        complexity_score=complexity,
        estimated_rows=est_rows,
        estimated_bytes=est_bytes,
        depth=stats.depth,
        alias_count=stats.alias_count,
        fanout_count=stats.fanout_count,
    )


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
