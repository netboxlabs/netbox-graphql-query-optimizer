"""Complexity scoring and estimation."""

from typing import Optional

from graphql import GraphQLSchema

from . import utils
from .config import Config
from .inspector import Stats


def default_weights(cfg: Config) -> dict:
    """
    Get default field weights.

    Args:
        cfg: Configuration

    Returns:
        Dict with default_field_weight and type_weights
    """
    return {
        "default_field_weight": 1,
        "type_weights": cfg.type_weights or {},
    }


def build_cardinality_map(stats: Stats, calib: Optional[dict], cfg: Config) -> dict[str, int]:
    """
    Build cardinality map from calibration data with fallback.

    No hardcoded types - fully dynamic based on calibration.

    Args:
        stats: Collected query statistics
        calib: Calibration data (type name -> count)
        cfg: Configuration with pagination_default

    Returns:
        Dict mapping type name to estimated cardinality
    """
    cardinality = {}

    # Collect all unique type names from list fields
    for item in stats.list_field_nodes:
        type_name = item["type_name"]
        if type_name not in cardinality:
            # Use calibrated value if available, else pagination_default
            cardinality[type_name] = (calib or {}).get(type_name, cfg.pagination_default)

    return cardinality


def score(doc, schema: GraphQLSchema, weights: dict, cardinality: dict, cfg: Config) -> int:
    """
    Calculate complexity score for query.

    Args:
        doc: Parsed query document
        schema: GraphQL schema
        weights: Weight configuration
        cardinality: Type cardinality map
        cfg: Configuration

    Returns:
        Integer complexity score
    """
    total = 0

    def visit(node, parent_type):
        nonlocal total

        if utils.is_field(node):
            field_def = utils.get_field_def(schema, parent_type, node.name.value)
            if not field_def:
                return

            ret_named = utils.named_output_type(field_def.type)
            w = weights["type_weights"].get(ret_named.name, weights["default_field_weight"])
            factor = 1

            if utils.is_list_type(field_def.type):
                # Check if query provides limit
                lim = utils.arg_val(node, {"first", "limit"})
                if lim:
                    factor = lim
                else:
                    # Use cardinality if available, else pagination_default
                    factor = cardinality.get(ret_named.name, cfg.pagination_default)

            total += w * factor

            # Recurse into children
            for child in utils.child_selections(node):
                visit(child, ret_named)
        else:
            for child in utils.child_nodes(node):
                visit(child, parent_type)

    root = schema.query_type
    for op in utils.iter_operations(doc):
        visit(op, root)

    return int(total)


def estimate_rows(stats: Stats, cardinality: dict, cfg: Config) -> int:
    """
    Estimate total row count for query.

    Args:
        stats: Collected query statistics
        cardinality: Type cardinality map
        cfg: Configuration

    Returns:
        Estimated row count
    """
    rows = 0

    for item in stats.list_field_nodes:
        node = item["node"]
        type_name = item["type_name"]

        # Check if query provides limit
        lim = utils.arg_val(node, {"first", "limit"})
        if lim:
            rows += lim
        else:
            rows += cardinality.get(type_name, cfg.pagination_default)

    return max(1, rows)


def estimate_bytes(est_rows: int, avg_fields_per_node: float) -> int:
    """
    Rough byte size estimate.

    Args:
        est_rows: Estimated row count
        avg_fields_per_node: Average fields per node

    Returns:
        Estimated bytes (very rough)
    """
    return int(est_rows * avg_fields_per_node * 16)
