"""GraphQL parsing and validation."""

from graphql import (
    GraphQLError,
    GraphQLSchema,
    build_client_schema,
    parse,
    validate,
)


def build_schema(schema_json: dict) -> GraphQLSchema:
    """
    Build GraphQL schema from introspection JSON.

    Args:
        schema_json: Introspection result, either {"__schema": {...}} or {"data": {"__schema": {...}}}

    Returns:
        GraphQLSchema object
    """
    # Handle both formats
    if "__schema" in schema_json:
        data = schema_json
    elif "data" in schema_json and "__schema" in schema_json["data"]:
        data = schema_json["data"]
    else:
        data = schema_json

    return build_client_schema(data)


def parse_query(source: str):
    """
    Parse GraphQL query string into AST.

    Args:
        source: GraphQL query string

    Returns:
        DocumentNode AST

    Raises:
        GraphQLError: If query is syntactically invalid
    """
    return parse(source)


def validate_query(doc, schema: GraphQLSchema) -> list[GraphQLError]:
    """
    Validate query against schema.

    Args:
        doc: Parsed query document
        schema: GraphQL schema

    Returns:
        List of validation errors (empty if valid)
    """
    return validate(schema, doc)
