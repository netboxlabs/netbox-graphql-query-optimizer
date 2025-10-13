"""Analysis rules for GraphQL queries."""

from dataclasses import dataclass, field
from typing import Any, Literal

from graphql import GraphQLError, GraphQLSchema

from . import utils
from .config import Config
from .inspector import Stats

Severity = Literal["INFO", "WARN", "ERROR"]


@dataclass
class RuleResult:
    """Result from a single rule check."""

    rule_id: str
    message: str
    severity: Severity
    locations: list[tuple[int, int]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def schema_validation_findings(errors: list[GraphQLError]) -> list[RuleResult]:
    """
    Convert GraphQL validation errors to rule results.

    Args:
        errors: List of GraphQL validation errors

    Returns:
        List of ERROR-level rule results
    """
    return [
        RuleResult(
            rule_id="schema-validation",
            message=str(e.message),
            severity="ERROR",
            locations=[],
            meta={},
        )
        for e in errors
    ]


def rule_alias_cap(doc, schema: GraphQLSchema, stats: Stats, cfg: Config) -> list[RuleResult]:
    """
    Check if alias count exceeds limit.

    Args:
        doc: Parsed query document
        schema: GraphQL schema
        stats: Collected statistics
        cfg: Configuration

    Returns:
        WARN if alias count > max_aliases
    """
    if stats.alias_count > cfg.max_aliases:
        return [
            RuleResult(
                rule_id="alias-cap",
                message=f"{stats.alias_count} aliases > max {cfg.max_aliases}",
                severity="WARN",
                locations=[],
                meta={},
            )
        ]
    return []


def rule_depth_breadth(doc, schema: GraphQLSchema, stats: Stats, cfg: Config) -> list[RuleResult]:
    """
    Check query depth and selection set breadth.

    Args:
        doc: Parsed query document
        schema: GraphQL schema
        stats: Collected statistics
        cfg: Configuration

    Returns:
        WARN if depth exceeds limit, INFO for breadth warnings
    """
    out = []

    # Check depth
    if stats.depth > cfg.max_depth:
        out.append(
            RuleResult(
                rule_id="depth",
                message=f"Depth {stats.depth} > {cfg.max_depth}",
                severity="WARN",
                locations=[],
                meta={},
            )
        )

    # Check breadth for each selection set
    for sel_set in utils.iter_selection_sets(doc):
        fields = utils.selection_fields(sel_set)
        if len(fields) > cfg.breadth_warn:
            out.append(
                RuleResult(
                    rule_id="breadth",
                    message=f"Selection breadth {len(fields)} fields",
                    severity="INFO",
                    locations=[],
                    meta={"selection_path": utils.path(sel_set)},
                )
            )

    return out


def rule_pagination_required(
    doc, schema: GraphQLSchema, stats: Stats, cfg: Config
) -> list[RuleResult]:
    """
    Check if list fields have pagination arguments.

    Only checks for limit args: first, last, limit, offset
    (NOT cursor args like after/before)

    Args:
        doc: Parsed query document
        schema: GraphQL schema
        stats: Collected statistics
        cfg: Configuration

    Returns:
        WARN for list fields without pagination
    """
    out = []
    for item in stats.list_field_nodes:
        node = item["node"]
        if not utils.has_any_arg(node, {"first", "last", "limit", "offset"}):
            out.append(
                RuleResult(
                    rule_id="pagination",
                    message=f"List field '{node.name.value}' has no pagination args",
                    severity="WARN",
                    locations=[utils.loc(node)],
                    meta={},
                )
            )
    return out


def rule_fanout(doc, schema: GraphQLSchema, stats: Stats, cfg: Config) -> list[RuleResult]:
    """
    Check for list→list nested paths (fan-out).

    Args:
        doc: Parsed query document
        schema: GraphQL schema
        stats: Collected statistics
        cfg: Configuration

    Returns:
        WARN if fan-out detected
    """
    if stats.fanout_count > 0:
        return [
            RuleResult(
                rule_id="fanout",
                message=f"{stats.fanout_count} list→list nests without pagination",
                severity="WARN",
                locations=[],
                meta={},
            )
        ]
    return []


def rule_filter_pushdown(doc, schema: GraphQLSchema, stats: Stats, cfg: Config) -> list[RuleResult]:
    """
    Suggest filter push-down for list fields.

    Args:
        doc: Parsed query document
        schema: GraphQL schema
        stats: Collected statistics
        cfg: Configuration

    Returns:
        INFO suggestions for available filters
    """
    out = []

    # Track parent type for field resolution
    def find_parent_type(node):
        # This is a simplified version - in real use we'd track context
        return schema.query_type

    for item in stats.list_field_nodes:
        node = item["node"]
        # Get field def (we need parent type, simplified here)
        parent_type = schema.query_type
        field_def = utils.get_field_def(schema, parent_type, node.name.value)

        if field_def:
            candidates = utils.filterable_args(field_def)
            if candidates and not utils.has_any_arg(node, set(candidates)):
                out.append(
                    RuleResult(
                        rule_id="filter-pushdown",
                        message=f"Consider applying filters at '{node.name.value}' using: {', '.join(candidates)}",
                        severity="INFO",
                        locations=[utils.loc(node)],
                        meta={"args": candidates},
                    )
                )

    return out


def rule_overfetch(doc, schema: GraphQLSchema, stats: Stats, cfg: Config) -> list[RuleResult]:
    """
    Check for overfetch (too many fields requested).

    Checks both global field count and per-object field counts.

    Args:
        doc: Parsed query document
        schema: GraphQL schema
        stats: Collected statistics
        cfg: Configuration

    Returns:
        WARN/INFO for queries requesting too many fields
    """
    out = []

    # Check global field count across entire query
    if stats.total_field_count > 50:
        severity = "WARN" if stats.total_field_count > 75 else "INFO"
        out.append(
            RuleResult(
                rule_id="overfetch",
                message=f"Query requests {stats.total_field_count} total fields (consider requesting only necessary fields)",
                severity=severity,
                locations=[],
                meta={"total_fields": stats.total_field_count},
            )
        )

    # We need to track parent types through the traversal
    def visit(node, parent_type):
        if utils.is_field(node):
            field_def = utils.get_field_def(schema, parent_type, node.name.value)
            if not field_def:
                return

            # Check selection set for leaf count
            if node.selection_set:
                leafs = []
                for child in utils.selection_fields(node.selection_set):
                    child_field_def = utils.get_field_def(
                        schema, utils.named_output_type(field_def.type), child.name.value
                    )
                    if child_field_def and utils.is_leaf_field(schema, child, utils.named_output_type(field_def.type)):
                        leafs.append(child)

                if len(leafs) > cfg.leaf_warn:
                    out.append(
                        RuleResult(
                            rule_id="overfetch",
                            message=f"Large leaf set {len(leafs)} fields in '{node.name.value}'",
                            severity="INFO",
                            locations=[utils.loc(node)],
                            meta={},
                        )
                    )

            # Recurse
            next_parent = utils.named_output_type(field_def.type)
            for child in utils.child_selections(node):
                visit(child, next_parent)
        else:
            for child in utils.iter_children(node):
                visit(child, parent_type)

    root = schema.query_type
    for op in utils.iter_operations(doc):
        visit(op, root)

    return out
