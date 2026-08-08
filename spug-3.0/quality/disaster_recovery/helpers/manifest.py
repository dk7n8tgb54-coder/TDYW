"""
Backup Manifest Parser

Parses backup_inventory.yml and validates its structure.
Also parses individual backup manifest.json files from backup sets.
"""

import json
import os
import yaml
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


# ---- Required fields for each backup object ----
REQUIRED_OBJECT_FIELDS = [
    "id", "name", "component", "backup_systems", "method",
    "frequency", "retention", "storage_type", "encrypted",
    "risk_level",
]

# ---- Required fields for each backup system ----
REQUIRED_SYSTEM_FIELDS = ["name", "type", "description"]


@dataclass
class ValidationResult:
    """Result of manifest validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    object_count: int = 0
    system_count: int = 0


@dataclass
class BackupObject:
    """A single backup object from the inventory."""
    id: str
    name: str
    component: str
    backup_systems: List[str]
    method: str
    frequency: str
    retention: str
    storage_type: str
    encrypted: bool
    offsite: bool
    risk_level: str
    last_known_success: str
    restore_documented: bool
    restore_verified: bool
    notes: str = ""
    excludes: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BackupSystem:
    """A backup system definition."""
    name: str
    type: str
    description: str
    create_script: str = ""
    restore_script: str = ""
    config_file: str = ""
    schema_version: str = ""
    encryption: str = ""
    compression: str = ""


@dataclass
class BackupInventory:
    """Parsed backup inventory."""
    version: str
    last_updated: str
    project: str
    systems: List[BackupSystem] = field(default_factory=list)
    objects: List[BackupObject] = field(default_factory=list)


def load_inventory(inventory_path: str) -> BackupInventory:
    """Load and parse backup_inventory.yml."""
    with open(inventory_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    inventory = BackupInventory(
        version=str(data.get("inventory_version", "")),
        last_updated=data.get("last_updated", ""),
        project=data.get("project", ""),
    )

    # Parse systems
    for sys_data in data.get("backup_systems", []):
        inventory.systems.append(BackupSystem(
            name=sys_data.get("name", ""),
            type=sys_data.get("type", ""),
            description=sys_data.get("description", ""),
            create_script=sys_data.get("create_script", ""),
            restore_script=sys_data.get("restore_script", ""),
            config_file=sys_data.get("config_file", ""),
            schema_version=str(sys_data.get("schema_version", "")),
            encryption=sys_data.get("encryption", ""),
            compression=sys_data.get("compression", ""),
        ))

    # Parse objects
    for obj_data in data.get("objects", []):
        inventory.objects.append(BackupObject(
            id=obj_data.get("id", ""),
            name=obj_data.get("name", ""),
            component=obj_data.get("component", ""),
            backup_systems=obj_data.get("backup_systems", []),
            method=obj_data.get("method", ""),
            frequency=obj_data.get("frequency", ""),
            retention=obj_data.get("retention", ""),
            storage_type=obj_data.get("storage_type", ""),
            encrypted=obj_data.get("encrypted", False),
            offsite=obj_data.get("offsite", False),
            risk_level=obj_data.get("risk_level", "unknown"),
            last_known_success=obj_data.get("last_known_success", "unknown"),
            restore_documented=obj_data.get("restore_documented", False),
            restore_verified=obj_data.get("restore_verified", False),
            notes=obj_data.get("notes", ""),
            excludes=obj_data.get("excludes", []),
            raw=obj_data,
        ))

    return inventory


def validate_inventory(inventory: BackupInventory) -> ValidationResult:
    """Validate the structure and completeness of a backup inventory."""
    result = ValidationResult(valid=True)

    # Check version
    if not inventory.version:
        result.errors.append("Missing inventory_version")
        result.valid = False

    # Check systems
    if not inventory.systems:
        result.warnings.append("No backup systems defined")
    else:
        for sys_obj in inventory.systems:
            for field_name in REQUIRED_SYSTEM_FIELDS:
                val = getattr(sys_obj, field_name, "")
                if not val:
                    result.errors.append(f"Backup system '{sys_obj.name}' missing required field: {field_name}")
                    result.valid = False
    result.system_count = len(inventory.systems)

    # Check objects
    if not inventory.objects:
        result.errors.append("No backup objects defined")
        result.valid = False
    else:
        for obj in inventory.objects:
            for field_name in REQUIRED_OBJECT_FIELDS:
                val = getattr(obj, field_name, None)
                if val is None or (isinstance(val, str) and not val):
                    result.errors.append(f"Backup object '{obj.id}' missing required field: {field_name}")
                    result.valid = False

            # Check risk level is valid
            if obj.risk_level not in ("critical", "high", "medium", "low", "unknown"):
                result.warnings.append(f"Object '{obj.id}' has unusual risk_level: {obj.risk_level}")

            # Check restore status
            if not obj.restore_documented:
                result.warnings.append(f"Object '{obj.id}' has no documented restore procedure")
            if not obj.restore_verified:
                result.warnings.append(f"Object '{obj.id}' restore has not been verified")

            # Check if backup_systems references exist
            for sys_ref in obj.backup_systems:
                if not any(s.name == sys_ref for s in inventory.systems):
                    result.warnings.append(
                        f"Object '{obj.id}' references unknown backup system: '{sys_ref}'"
                    )

    result.object_count = len(inventory.objects)
    return result


def parse_backup_manifest(manifest_path: str) -> dict:
    """
    Parse a manifest.json from a backup set (backup_set or borgbackup).
    Returns the raw JSON dict.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_backup_manifest(manifest: dict) -> ValidationResult:
    """Validate the structure of a backup manifest.json from a backup set."""
    result = ValidationResult(valid=True)

    required_keys = [
        "schema_version", "created_at", "backup_type",
        "database", "volumes",
    ]
    for key in required_keys:
        if key not in manifest:
            result.errors.append(f"Manifest missing required key: {key}")
            result.valid = False

    # Check database info
    db_info = manifest.get("database", {})
    if not db_info.get("name"):
        result.errors.append("Manifest database.name is missing")
        result.valid = False
    if not db_info.get("dump_file"):
        result.errors.append("Manifest database.dump_file is missing")
        result.valid = False

    # Check volumes
    volumes = manifest.get("volumes", [])
    if not volumes:
        result.warnings.append("Manifest has no volume entries")
    for i, vol in enumerate(volumes):
        if not vol.get("name"):
            result.errors.append(f"Volume #{i} missing 'name'")
            result.valid = False
        if not vol.get("archive_file"):
            result.errors.append(f"Volume '{vol.get('name', f'#{i}')}' missing 'archive_file'")
            result.valid = False

    # Check for git commit
    if not manifest.get("git_commit"):
        result.warnings.append("Manifest has no git_commit - cannot verify code version")

    # Check for checksums
    if not manifest.get("sha256sums_file") and not manifest.get("checksums"):
        result.warnings.append("Manifest has no checksum reference - cannot verify integrity")

    return result


def get_objects_by_component(inventory: BackupInventory, component: str) -> List[BackupObject]:
    """Filter backup objects by component name."""
    return [obj for obj in inventory.objects if obj.component == component]


def get_objects_by_risk(inventory: BackupInventory, risk_level: str) -> List[BackupObject]:
    """Filter backup objects by risk level."""
    return [obj for obj in inventory.objects if obj.risk_level == risk_level]


def get_unverified_objects(inventory: BackupInventory) -> List[BackupObject]:
    """Get all objects whose restore has not been verified."""
    return [obj for obj in inventory.objects if not obj.restore_verified]


def get_undocumented_objects(inventory: BackupInventory) -> List[BackupObject]:
    """Get all objects with no documented restore procedure."""
    return [obj for obj in inventory.objects if not obj.restore_documented]
