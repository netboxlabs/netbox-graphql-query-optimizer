"""AST inspection and statistics collection."""

from dataclasses import dataclass
from typing import Any

from graphql import GraphQLSchema

from . import utils


@dataclass
class Stats:
    """Statistics collected from query AST."""

    depth: int
    alias_count: int
    fanout_count: int
    list_field_nodes: list[dict[str, Any]]  # [{node, type_name, has_pagination}, ...]
    avg_fields_per_node: float
    total_field_count: int  # Total fields requested across entire query


def collect_stats(doc, schema: GraphQLSchema) -> Stats:
    """
    Collect statistics from query AST.

    Args:
        doc: Parsed GraphQL document
        schema: GraphQL schema

    Returns:
        Stats object with collected metrics
    """
    depth = 0
    alias_count = 0
    fanout_count = 0
    list_field_nodes = []
    total_fields = 0
    total_nodes = 0
    list_ancestor_stack = []

    def visit(node, current_depth, parent_type):
        nonlocal depth, alias_count, fanout_count, total_fields, total_nodes

        if utils.is_field(node):
            total_fields += 1
            total_nodes += 1

            # Count aliases
            if node.alias:
                alias_count += 1

            # Get field definition
            field_def = utils.get_field_def(schema, parent_type, node.name.value)
            if not field_def:
                return

            returns_list = utils.is_list_type(field_def.type)

            if returns_list:
                ret_type = utils.named_output_type(field_def.type)
                has_pagination = utils.has_any_arg(node, {"first", "last", "limit", "offset"})

                list_field_nodes.append({
                    "node": node,
                    "type_name": ret_type.name,
                    "has_pagination": has_pagination,
                })

                # Detect fan-out: nested lists where pagination is missing
                if list_ancestor_stack:
                    # Count as fan-out only if current list or any ancestor lacks pagination
                    if not has_pagination or not all(list_ancestor_stack):
                        fanout_count += 1

                list_ancestor_stack.append(has_pagination)

            # Recurse into children
            next_parent = utils.named_output_type(field_def.type)
            for child in utils.child_selections(node):
                visit(child, current_depth + 1, next_parent)

            if returns_list:
                list_ancestor_stack.pop()

        else:
            # Handle non-field nodes (operations, inline fragments, etc.)
            for child in utils.iter_children(node):
                visit(child, current_depth, parent_type)

        depth = max(depth, current_depth)

    # Visit all operations
    root = schema.query_type
    for op in utils.iter_operations(doc):
        visit(op, 0, root)

    avg = total_fields / max(1, total_nodes)
    return Stats(
        depth=depth,
        alias_count=alias_count,
        fanout_count=fanout_count,
        list_field_nodes=list_field_nodes,
        avg_fields_per_node=avg,
        total_field_count=total_fields,
    )


def extract_list_types(doc, schema: GraphQLSchema) -> set[str]:
    """
    Extract all unique type names that are returned as lists in the query.

    Args:
        doc: Parsed GraphQL document
        schema: GraphQL schema

    Returns:
        Set of type names (strings)
    """
    types = set()

    def visit(node, parent_type):
        if utils.is_field(node):
            field_def = utils.get_field_def(schema, parent_type, node.name.value)
            if not field_def:
                return

            if utils.is_list_type(field_def.type):
                ret_type = utils.named_output_type(field_def.type)
                types.add(ret_type.name)

            next_parent = utils.named_output_type(field_def.type)
            for child in utils.child_selections(node):
                visit(child, next_parent)
        else:
            for child in utils.iter_children(node):
                visit(child, parent_type)

    root = schema.query_type
    for op in utils.iter_operations(doc):
        visit(op, root)

    return types
