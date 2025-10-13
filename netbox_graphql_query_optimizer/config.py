"""Configuration management for netbox-gqo."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from . import utils


@dataclass
class Config:
    """Configuration for netbox-gqo."""

    default_url: Optional[str] = None
    max_depth: int = 5
    max_aliases: int = 10
    breadth_warn: int = 15
    leaf_warn: int = 20
    pagination_default: int = 100
    schema_cache_dir: str = "~/.netbox-gqo/schemas"
    calibration_cache_dir: str = "~/.netbox-gqo/calibration"
    type_weights: dict[str, int] = field(default_factory=dict)
    type_mappings: dict[str, str] = field(default_factory=dict)
    profiles: list[dict] = field(default_factory=list)

    def __post_init__(self):
        """Expand paths after initialization."""
        self.schema_cache_dir = utils.expand_path(self.schema_cache_dir)
        self.calibration_cache_dir = utils.expand_path(self.calibration_cache_dir)


def get_default_config_path() -> str:
    """Get default config file path."""
    return utils.expand_path("~/.netbox-gqo/config.yaml")


def load(config_path: Optional[str] = None) -> Config:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses default location.

    Returns:
        Config object with defaults for missing values.
    """
    if config_path is None:
        config_path = get_default_config_path()

    # Return defaults if config doesn't exist
    if not utils.exists(config_path):
        return Config(
            type_weights={
                "Device": 3,
                "Interface": 2,
                "IPAddress": 1,
            },
            type_mappings={
                "Device": "/api/dcim/devices/",
                "Interface": "/api/dcim/interfaces/",
                "IPAddress": "/api/ipam/ip-addresses/",
                "VirtualMachine": "/api/virtualization/virtual-machines/",
                "Cable": "/api/dcim/cables/",
                "Circuit": "/api/circuits/circuits/",
                "Contact": "/api/tenancy/contacts/",
                "Prefix": "/api/ipam/prefixes/",
                "Rack": "/api/dcim/racks/",
                "Site": "/api/dcim/sites/",
                "VLAN": "/api/ipam/vlans/",
            },
        )

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    # Merge with defaults
    return Config(
        default_url=data.get("default_url"),
        max_depth=data.get("max_depth", 5),
        max_aliases=data.get("max_aliases", 10),
        breadth_warn=data.get("breadth_warn", 15),
        leaf_warn=data.get("leaf_warn", 20),
        pagination_default=data.get("pagination_default", 100),
        schema_cache_dir=data.get("schema_cache_dir", "~/.netbox-gqo/schemas"),
        calibration_cache_dir=data.get("calibration_cache_dir", "~/.netbox-gqo/calibration"),
        type_weights=data.get("type_weights", {}),
        type_mappings=data.get(
            "type_mappings",
            {
                "Device": "/api/dcim/devices/",
                "Interface": "/api/dcim/interfaces/",
                "IPAddress": "/api/ipam/ip-addresses/",
                "VirtualMachine": "/api/virtualization/virtual-machines/",
                "Cable": "/api/dcim/cables/",
                "Circuit": "/api/circuits/circuits/",
                "Contact": "/api/tenancy/contacts/",
                "Prefix": "/api/ipam/prefixes/",
                "Rack": "/api/dcim/racks/",
                "Site": "/api/dcim/sites/",
                "VLAN": "/api/ipam/vlans/",
            },
        ),
        profiles=data.get("profiles", []),
    )


def create_example_config(path: Optional[str] = None) -> None:
    """Create an example config file."""
    if path is None:
        path = get_default_config_path()

    utils.ensure_dir(utils.dirname(path))

    example = {
        "default_url": "https://netbox.local/",
        "max_depth": 5,
        "max_aliases": 10,
        "breadth_warn": 15,
        "leaf_warn": 20,
        "pagination_default": 100,
        "schema_cache_dir": "~/.netbox-gqo/schemas",
        "calibration_cache_dir": "~/.netbox-gqo/calibration",
        "type_weights": {
            "Device": 3,
            "Interface": 2,
            "IPAddress": 1,
        },
        "type_mappings": {
            "Device": "/api/dcim/devices/",
            "Interface": "/api/dcim/interfaces/",
            "IPAddress": "/api/ipam/ip-addresses/",
            "VirtualMachine": "/api/virtualization/virtual-machines/",
            "Cable": "/api/dcim/cables/",
            "Circuit": "/api/circuits/circuits/",
            "Contact": "/api/tenancy/contacts/",
            "Prefix": "/api/ipam/prefixes/",
            "Rack": "/api/dcim/racks/",
            "Site": "/api/dcim/sites/",
            "VLAN": "/api/ipam/vlans/",
        },
        "profiles": [
            {"name": "prod", "url": "https://prod.netbox/"},
            {"name": "dev", "url": "https://dev.netbox/"},
        ],
    }

    with open(path, "w") as f:
        yaml.dump(example, f, default_flow_style=False, sort_keys=False)
