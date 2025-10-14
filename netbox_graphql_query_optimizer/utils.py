"""Utility functions for GraphQL query analysis."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from graphql import (
    FieldNode,
    GraphQLField,
    GraphQLList,
    GraphQLNamedType,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLType,
    ObjectValueNode,
    get_introspection_query,
)

# Standard GraphQL introspection query
INTROSPECTION_QUERY = get_introspection_query()


# File system utilities
def ensure_dir(path: str) -> None:
    """Ensure directory exists, creating it if necessary."""
    Path(path).mkdir(parents=True, exist_ok=True)


def exists(path: str) -> bool:
    """Check if file exists."""
    return Path(path).exists()


def dirname(path: str) -> str:
    """Get directory name from path."""
    return str(Path(path).parent)


def join(*parts: str) -> str:
    """Join path components."""
    return str(Path(*parts))


def expand_path(path: str) -> str:
    """Expand ~ and environment variables in path."""
    return str(Path(path).expanduser())


# File I/O
def read_text(path: str) -> str:
    """Read text file."""
    return Path(path).read_text()


def read_json(path: str) -> dict:
    """Read JSON file."""
    with open(path) as f:
        return json.load(f)


def write_json(path: str, data: Any) -> None:
    """Write JSON file with pretty formatting."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def to_json(data: Any) -> str:
    """Convert data to JSON string."""
    return json.dumps(data, indent=2)


# Hashing & timestamps
def now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def sha256(obj: Any) -> str:
    """Calculate SHA-256 hash of object."""
    s = json.dumps(obj, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def sanitize_host(url: str) -> str:
    """Extract sanitized hostname from URL for use in filenames."""
    if url.startswith("file://"):
        return "file"
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path
    # Remove port, replace special chars
    host = host.split(":")[0]
    return host.replace("/", "_").replace(":", "_")


# URL manipulation
def ensure_graphql_url(url: str) -> str:
    """Ensure URL ends with /graphql/ - append if missing."""
    url = url.rstrip("/")
    if not url.endswith("/graphql"):
        url = f"{url}/graphql/"
    elif not url.endswith("/"):
        url = f"{url}/"
    return url


def base_url_from_graphql(graphql_url: str) -> str:
    """Extract base URL from GraphQL URL (remove /graphql/ suffix)."""
    if graphql_url.startswith("file://"):
        return "file://"
    return graphql_url.replace("/graphql/", "/").replace("/graphql", "").rstrip("/") + "/"


# GraphQL type helpers
def is_list_type(graphql_type: GraphQLType) -> bool:
    """Check if GraphQL type is a list type."""
    # Unwrap non-null first
    if isinstance(graphql_type, GraphQLNonNull):
        graphql_type = graphql_type.of_type
    return isinstance(graphql_type, GraphQLList)


def named_output_type(graphql_type: GraphQLType) -> GraphQLNamedType:
    """Unwrap non-null/list wrappers to get the named type."""
    while isinstance(graphql_type, (GraphQLNonNull, GraphQLList)):
        graphql_type = graphql_type.of_type
    return graphql_type


def get_field_def(
    schema: GraphQLSchema, parent_type: GraphQLObjectType, field_name: str
) -> Optional[GraphQLField]:
    """Get field definition from parent type."""
    if not isinstance(parent_type, GraphQLObjectType):
        return None
    return parent_type.fields.get(field_name)


def is_field(node: Any) -> bool:
    """Check if AST node is a field node."""
    return isinstance(node, FieldNode)


def is_leaf_field(schema: GraphQLSchema, field_node: FieldNode, parent_type: GraphQLObjectType) -> bool:
    """Check if field is a leaf (scalar/enum) with no selection set."""
    field_def = get_field_def(schema, parent_type, field_node.name.value)
    if not field_def:
        return False
    return_type = named_output_type(field_def.type)
    # If it's not an object/interface/union, it's a leaf
    return not isinstance(return_type, GraphQLObjectType)


# AST traversal helpers
def iter_operations(doc):
    """Iterate over all operations in document."""
    for definition in doc.definitions:
        if hasattr(definition, "operation"):
            yield definition


def iter_children(node):
    """Iterate over child nodes."""
    if hasattr(node, "selection_set") and node.selection_set:
        yield from node.selection_set.selections
    elif hasattr(node, "selections"):
        yield from node.selections


def child_selections(field_node: FieldNode):
    """Get child selections from a field node."""
    if field_node.selection_set:
        return field_node.selection_set.selections
    return []


def child_nodes(node):
    """Get child nodes (generic)."""
    return list(iter_children(node))


def iter_selection_sets(doc):
    """Iterate over all selection sets in document."""
    def visit(node):
        if hasattr(node, "selection_set") and node.selection_set:
            yield node.selection_set
            for child in node.selection_set.selections:
                yield from visit(child)

    for op in iter_operations(doc):
        yield from visit(op)


def selection_fields(selection_set):
    """Get field nodes from selection set."""
    return [s for s in selection_set.selections if isinstance(s, FieldNode)]


# Argument helpers
def has_any_arg(field_node: FieldNode, names: set[str]) -> bool:
    """
    Check if field has any of the specified arguments.

    Supports both top-level arguments and nested fields in input objects.
    For example:
    - Top-level: device_list(limit: 10)
    - Nested: device_list(pagination: {limit: 10})
    """
    if not field_node.arguments:
        return False

    # Check top-level argument names
    arg_names = {arg.name.value for arg in field_node.arguments}
    if arg_names & names:
        return True

    # Check nested fields inside ObjectValue arguments
    for arg in field_node.arguments:
        if isinstance(arg.value, ObjectValueNode):
            # Check fields inside the object
            nested_names = {field.name.value for field in arg.value.fields}
            if nested_names & names:
                return True

    return False


def arg_val(field_node: FieldNode, names: set[str]) -> Optional[int]:
    """
    Get integer value of first matching argument.

    Supports both top-level arguments and nested fields in input objects.
    For example:
    - Top-level: device_list(limit: 10) returns 10
    - Nested: device_list(pagination: {limit: 10}) returns 10
    """
    if not field_node.arguments:
        return None

    # Check top-level arguments first
    for arg in field_node.arguments:
        if arg.name.value in names:
            # Extract int value from AST
            if hasattr(arg.value, "value"):
                try:
                    return int(arg.value.value)
                except (ValueError, TypeError):
                    pass

    # Check nested fields inside ObjectValue arguments
    for arg in field_node.arguments:
        if isinstance(arg.value, ObjectValueNode):
            # Look for matching field names inside the object
            for field in arg.value.fields:
                if field.name.value in names:
                    if hasattr(field.value, "value"):
                        try:
                            return int(field.value.value)
                        except (ValueError, TypeError):
                            pass

    return None


def field_def_for_node(schema: GraphQLSchema, node: FieldNode, parent_type: GraphQLObjectType = None) -> Optional[GraphQLField]:
    """Get field definition for a field node."""
    if parent_type:
        return get_field_def(schema, parent_type, node.name.value)
    return None


def infer_named_return_type(field_def: GraphQLField) -> str:
    """Get the named return type from a field definition."""
    return_type = named_output_type(field_def.type)
    return return_type.name


def filterable_args(field_def: GraphQLField) -> list[str]:
    """
    Identify filterable arguments using heuristics:
    - Common filter arg names: id, name, slug, tenant, site, role, status, etc.
    - Input types ending with "Filter"
    """
    if not field_def or not field_def.args:
        return []

    candidates = []
    common_filters = {"id", "name", "slug", "tenant", "site", "role", "status", "region", "tag"}

    for arg_name, arg_def in field_def.args.items():
        # Check if arg name is a common filter
        if arg_name in common_filters:
            candidates.append(arg_name)
        # Check if type name ends with "Filter"
        elif hasattr(arg_def.type, "name") and arg_def.type.name and arg_def.type.name.endswith("Filter"):
            candidates.append(arg_name)
        # Unwrap NonNull and check
        elif isinstance(arg_def.type, GraphQLNonNull):
            inner = arg_def.type.of_type
            if hasattr(inner, "name") and inner.name and inner.name.endswith("Filter"):
                candidates.append(arg_name)

    return candidates


def path(node) -> str:
    """Get path to node (for debugging/display)."""
    # Simple implementation - return node type
    if hasattr(node, "name"):
        return f"{node.__class__.__name__}:{node.name.value}"
    return node.__class__.__name__


def loc(node) -> tuple[int, int]:
    """Get location (line, col) from AST node."""
    if hasattr(node, "loc") and node.loc:
        # GraphQL line numbers are 1-based
        line = node.loc.source.get_location(node.loc.start).line
        col = node.loc.source.get_location(node.loc.start).column
        return (line, col)
    return (0, 0)


# HTTP response helpers
def safe_json_response(response, context: str = "API request") -> dict:
    """
    Safely parse JSON from HTTP response with helpful error messages.

    Args:
        response: requests.Response object
        context: Description of what operation failed (e.g., "GraphQL introspection")

    Returns:
        Parsed JSON as dict

    Raises:
        RuntimeError: If response is not valid JSON, with detailed diagnostic info
    """
    try:
        return response.json()
    except json.JSONDecodeError as e:
        # Get response details for debugging
        url = response.url
        status = response.status_code
        content_type = response.headers.get("Content-Type", "unknown")

        # Preview response body (first 300 chars)
        body_preview = response.text[:300]
        if len(response.text) > 300:
            body_preview += "..."

        # Build helpful error message
        error_parts = [
            f"{context} failed - server returned non-JSON response",
            "",
            f"  URL: {url}",
            f"  Status: {status}",
            f"  Content-Type: {content_type}",
            "",
            "  Response preview:",
            f"  {body_preview}",
            "",
            "  Suggestions:",
            "  - Verify the URL is correct and points to a valid endpoint",
        ]

        # Add context-specific suggestions
        if "graphql" in context.lower():
            error_parts.append("  - Ensure the GraphQL endpoint is accessible (try /graphql/)")
            error_parts.append("  - Authentication may be required - try adding --token YOUR_TOKEN")
        elif "rest" in context.lower() or "calibration" in context.lower():
            error_parts.append("  - Authentication may be required - verify your API token")
            error_parts.append("  - Check that the REST API endpoint is accessible")

        error_parts.append("  - Verify the server is running and properly configured")

        # Add original JSON error for debugging
        error_parts.append("")
        error_parts.append(f"  Original JSON error: {e}")

        raise RuntimeError("\n".join(error_parts))
