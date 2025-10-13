"""Schema loading and caching."""

from dataclasses import asdict, dataclass
from typing import Optional

import requests

from . import utils
from .config import Config


@dataclass
class SchemaProfile:
    """Schema profile with metadata."""

    url: str
    fetched_at: str
    hash: str
    schema_json: dict


def load_schema(
    url: Optional[str] = None,
    schema_file: Optional[str] = None,
    cfg: Optional[Config] = None,
    allow_cache: bool = True,
    refresh: bool = False,
    token: Optional[str] = None,
) -> SchemaProfile:
    """
    Load GraphQL schema from file or via introspection.

    Args:
        url: GraphQL endpoint URL (with /graphql/ suffix)
        schema_file: Path to cached schema JSON file
        cfg: Configuration object
        allow_cache: Whether to use cached schema
        refresh: Force refresh even if cached
        token: Optional API token for authentication

    Returns:
        SchemaProfile with loaded schema

    Raises:
        AssertionError: If neither url nor schema_file provided
    """
    # Load from file
    if schema_file:
        js = utils.read_json(schema_file)
        return SchemaProfile(
            url=f"file://{schema_file}",
            fetched_at=utils.now_iso(),
            hash=utils.sha256(js),
            schema_json=js,
        )

    # Load from URL
    assert url, "No URL or schema file provided"

    cache_path = cache_path_for(url, cfg)

    # Try cache first
    if allow_cache and utils.exists(cache_path) and not refresh:
        prof_data = utils.read_json(cache_path)
        return SchemaProfile(**prof_data)

    # Fetch from server
    js = introspect(url, token)
    prof = SchemaProfile(
        url=url,
        fetched_at=utils.now_iso(),
        hash=utils.sha256(js),
        schema_json=js,
    )

    # Save to cache
    utils.ensure_dir(utils.dirname(cache_path))
    utils.write_json(cache_path, asdict(prof))

    return prof


def introspect(graphql_url: str, token: Optional[str] = None) -> dict:
    """
    Introspect GraphQL schema via HTTP.

    Args:
        graphql_url: GraphQL endpoint URL (must end with /graphql/)
        token: Optional API token for authentication

    Returns:
        Introspection result as dict

    Raises:
        RuntimeError: If introspection fails
    """
    query = utils.INTROSPECTION_QUERY
    headers = {}
    if token:
        headers["Authorization"] = f"Token {token}"
    resp = requests.post(graphql_url, json={"query": query}, headers=headers, timeout=30)

    if resp.status_code != 200:
        raise RuntimeError(f"Introspection failed with status {resp.status_code}")

    payload = resp.json()

    if "errors" in payload:
        raise RuntimeError(f"Introspection errors: {payload['errors']}")

    return payload["data"]


def cache_path_for(url: str, cfg: Config) -> str:
    """
    Get cache path for a schema URL.

    Args:
        url: GraphQL endpoint URL
        cfg: Configuration object

    Returns:
        Path to cache file
    """
    host = utils.sanitize_host(url)
    return utils.join(cfg.schema_cache_dir, f"{host}.json")
