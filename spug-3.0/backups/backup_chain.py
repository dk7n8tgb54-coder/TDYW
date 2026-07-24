"""Validation helpers shared by backup-set restore and restore tests."""

import hashlib
import json
import re
from pathlib import Path


BACKUP_SET_PATTERN = re.compile(r"^backup_set_[0-9]{8}_[0-9]{6}$")
CHECKSUM_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def verify_checksums(backup_set_dir):
    checksum_path = backup_set_dir / "SHA256SUMS"
    if not checksum_path.is_file():
        raise RuntimeError(f"SHA256SUMS is missing: {backup_set_dir}")
    verified = {}
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not CHECKSUM_PATTERN.fullmatch(parts[0]):
            raise RuntimeError(f"invalid SHA256SUMS line in {backup_set_dir}")
        name = parts[1].lstrip("* ")
        if not name or name in verified or Path(name).name != name:
            raise RuntimeError(f"unsafe or duplicate checksum artifact: {name!r}")
        artifact = backup_set_dir / name
        if not artifact.is_file():
            raise RuntimeError(f"checksummed artifact is missing: {artifact}")
        if sha256_file(artifact) != parts[0]:
            raise RuntimeError(f"SHA-256 mismatch: {artifact}")
        verified[name] = parts[0]
    return verified


def validate_member(path):
    verified = verify_checksums(path)
    required = {
        "database.sql.gz",
        "documents.tar.gz",
        "documents.manifest.json",
        "documents.delta.json",
        "media.tar.gz",
        "media.manifest.json",
        "media.delta.json",
        "manifest.json",
    }
    if not required.issubset(verified):
        missing = ", ".join(sorted(required - verified))
        raise RuntimeError(f"backup set checksum coverage is incomplete: {missing}")

    manifest = load_json(path / "manifest.json")
    if manifest.get("schema_version") != 4 or manifest.get("status") != "SUCCESS":
        raise RuntimeError(f"backup set is not a successful schema-v4 set: {path}")
    if manifest.get("backup_set_id") != path.name:
        raise RuntimeError(f"backup_set_id does not match directory: {path}")

    artifacts = manifest.get("database", {}).get("artifacts", [])
    logical = [item for item in artifacts if item.get("type") == "logical"]
    physical = [item for item in artifacts if item.get("type") == "physical"]
    if len(logical) != 1 or logical[0].get("format") != "mariadb-dump-gzip":
        raise RuntimeError(f"exactly one logical mariadb-dump artifact is required: {path}")
    if len(physical) > 1:
        raise RuntimeError(f"multiple physical database artifacts are not allowed: {path}")
    if physical and physical[0].get("format") != "mariabackup-tar-gzip":
        raise RuntimeError(f"unsupported physical database format: {path}")
    for artifact in logical + physical:
        name = artifact.get("artifact", "")
        if Path(name).name != name or name not in verified:
            raise RuntimeError(f"database artifact is unsafe or not checksummed: {name!r}")
        actual = path / name
        if artifact.get("sha256") != verified[name]:
            raise RuntimeError(f"manifest database hash mismatch: {actual}")

    for name in ("documents", "media"):
        snapshot_manifest = load_json(path / f"{name}.manifest.json")
        delta_manifest = load_json(path / f"{name}.delta.json")
        if snapshot_manifest != manifest.get("filesets", {}).get(name):
            raise RuntimeError(f"root manifest {name} snapshot does not match sidecar")
        if snapshot_manifest.get("schema_version") != 2:
            raise RuntimeError(f"unsupported {name} snapshot manifest schema")
        if delta_manifest.get("schema_version") != 1:
            raise RuntimeError(f"unsupported {name} delta manifest schema")
        for payload in (snapshot_manifest, delta_manifest):
            if payload.get("backup_set_id") != path.name:
                raise RuntimeError(f"{name} manifest backup_set_id does not match")
            if payload.get("fileset") != name:
                raise RuntimeError(f"{name} manifest fileset does not match")
        if snapshot_manifest.get("archive_sha256") != verified[f"{name}.tar.gz"]:
            raise RuntimeError(f"{name} archive hash does not match snapshot manifest")
        if delta_manifest.get("archive_sha256") != snapshot_manifest.get("archive_sha256"):
            raise RuntimeError(f"{name} delta and snapshot archive hashes differ")
    return manifest


def resolve_chain(target_dir):
    target = Path(target_dir).resolve()
    root = target.parent
    if not BACKUP_SET_PATTERN.fullmatch(target.name):
        raise RuntimeError("target backup set directory name is invalid")

    reverse_chain = []
    seen = set()
    current = target
    expected_base = None
    while True:
        if current.name in seen:
            raise RuntimeError("fileset backup chain contains a cycle")
        if current.parent != root or not BACKUP_SET_PATTERN.fullmatch(current.name):
            raise RuntimeError("fileset parent escaped the selected backup root")
        seen.add(current.name)
        manifest = validate_member(current)
        chain = manifest.get("fileset_chain", {})
        base_id = chain.get("base_backup_set_id")
        if expected_base is None:
            expected_base = base_id
        if not base_id or base_id != expected_base:
            raise RuntimeError("fileset chain base_backup_set_id is inconsistent")
        reverse_chain.append((current, manifest))
        mode = chain.get("mode")
        parent_id = chain.get("parent_backup_set_id")
        if mode == "full":
            if current.name != expected_base or parent_id:
                raise RuntimeError("fileset full baseline metadata is inconsistent")
            break
        if mode != "incremental" or not parent_id or not BACKUP_SET_PATTERN.fullmatch(parent_id):
            raise RuntimeError("fileset incremental parent metadata is invalid")
        current = root / parent_id

    chain_members = list(reversed(reverse_chain))
    previous_id = None
    for path, manifest in chain_members:
        chain = manifest["fileset_chain"]
        if chain.get("parent_backup_set_id") != previous_id:
            raise RuntimeError("fileset chain is not contiguous")
        for name in ("documents", "media"):
            snapshot_manifest = manifest["filesets"][name]
            delta_manifest = load_json(path / f"{name}.delta.json")
            if snapshot_manifest.get("backup_mode") != chain["mode"]:
                raise RuntimeError(f"{name} snapshot mode does not match root chain")
            if delta_manifest.get("backup_mode") != chain["mode"]:
                raise RuntimeError(f"{name} delta mode does not match root chain")
            if snapshot_manifest.get("base_backup_set_id") != expected_base:
                raise RuntimeError(f"{name} snapshot base does not match root chain")
            if snapshot_manifest.get("parent_backup_set_id") != previous_id:
                raise RuntimeError(f"{name} snapshot parent does not match root chain")
            if delta_manifest.get("parent_backup_set_id") != previous_id:
                raise RuntimeError(f"{name} delta parent does not match root chain")
        previous_id = path.name
    return chain_members
