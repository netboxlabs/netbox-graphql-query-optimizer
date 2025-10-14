"""Cardinality calibration via NetBox REST API."""

from typing import Optional

import requests

from . import utils
from .config import Config


def calibrate(
    base_url: str, token: Optional[str], types_to_probe: Optional[set[str]], cfg: Config
) -> dict:
    """
    Probe NetBox REST API for cardinality counts.

    Args:
        base_url: NetBox base URL (e.g., https://netbox.local/)
        token: Optional API token
        types_to_probe: Optional set of GraphQL type names to probe (from query analysis)
                        If None, probes all types in cfg.type_mappings
        cfg: Config object with type_mappings

    Returns:
        Dict mapping GraphQL type name -> count
    """
    headers = {"Authorization": f"Token {token}"} if token else {}

    # Determine which types to probe
    if types_to_probe:
        # Filter type_mappings to only include types used in query
        endpoints = {k: v for k, v in cfg.type_mappings.items() if k in types_to_probe}
    else:
        # Probe all configured types
        endpoints = cfg.type_mappings

    out = {}
    for graphql_type, rest_path in endpoints.items():
        url = f"{base_url.rstrip('/')}{rest_path}?limit=1"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.ok:
                data = utils.safe_json_response(r, context=f"REST API calibration ({graphql_type})")
                out[graphql_type] = data.get("count")
            else:
                out[graphql_type] = None
        except Exception:
            out[graphql_type] = None

    return out


def cache_path_for(url: str, cfg: Config) -> str:
    """
    Generate cache path for calibration data based on base URL.

    Args:
        url: Base URL
        cfg: Configuration

    Returns:
        Path to calibration cache file
    """
    host = utils.sanitize_host(url)
    return utils.join(cfg.calibration_cache_dir, f"{host}.json")


def load_calibration(path: Optional[str]) -> Optional[dict]:
    """
    Load calibration from file.

    Args:
        path: Path to calibration file

    Returns:
        Calibration dict or None
    """
    if not path:
        return None
    if not utils.exists(path):
        return None
    return utils.read_json(path)


def load_cached_for(base_url: str, cfg: Config) -> Optional[dict]:
    """
    Load cached calibration for a base URL.

    Args:
        base_url: NetBox base URL
        cfg: Configuration

    Returns:
        Calibration dict or None
    """
    p = cache_path_for(base_url, cfg)
    if utils.exists(p):
        return utils.read_json(p)
    return None
