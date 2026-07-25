"""Validation helpers shared by backup-set restore and restore tests."""
"""由backup-set restore 和 restore tests的验证辅助工具。"""

import hashlib
import json
import re
from pathlib import Path


BACKUP_SET_PATTERN = re.compile(r"^backup_set_[0-9]{8}_[0-9]{6}$")
CHECKSUM_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# 计算文件 SHA256
def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

# 读取 JSON 文件
def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)

# 读取备份目录下的 `SHA256SUMS` 文件，逐条校验所有备份文件哈希，校验备份文件哈希与校验和文件内的哈希值是否一致，返回校验通过的文件名 - 哈希映射
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

# 在 verify_checksums 基础上，校验清单完整性、版本、数据库备份、文件集快照 / 增量元数据一致性
def validate_member(path):
    """
    校验单个独立备份集目录的完整合法性
    对某一个 backup_set_xxx 备份文件夹执行全套校验：文件哈希完整性、必备文件齐全、根清单规范、数据库备份规范、文档/媒体快照增量元数据自洽
    Args:
        path (Path): 待校验的备份集目录路径对象
    Returns:
        dict: 解析后的根清单 manifest.json 字典，供上层备份链解析使用
    Raises:
        RuntimeError: 任意校验项不满足时抛出异常，场景包含：
            1. SHA256SUMS 文件校验失败，文件篡改/缺失
            2. 备份集缺少规定的核心必备文件
            3. manifest.json 版本非4、备份状态非成功
            4. manifest内backup_set_id与目录名不匹配
            5. 逻辑/物理数据库备份数量、格式不符合规范
            6. 数据库文件存在路径穿越风险、未纳入哈希校验、哈希不一致
            7. documents/media附属清单与根清单内容不一致
            8. 快照/增量清单schema版本不兼容
            9. 附属清单归属备份集、文件集标识错乱
            10. 归档压缩包哈希记录不一致、快照与增量归档哈希不匹配
    """
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
    # 校验清单完整性
    manifest = load_json(path / "manifest.json")
    if manifest.get("schema_version") != 4 or manifest.get("status") != "SUCCESS":
        raise RuntimeError(f"backup set is not a successful schema-v4 set: {path}")
    if manifest.get("backup_set_id") != path.name:
        raise RuntimeError(f"backup_set_id does not match directory: {path}")

    # ########################### 数据库备份校验 ###########################
    # 校验数据库备份,遍历所有数据库备份文件（逻辑备份 + 物理备份），做三层校验：文件名安全、文件存在于校验清单、清单哈希一致，任意不匹配直接抛异常
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
            
    # ########################### 文件集快照&增量元数据校验 ###########################
    # 校验文件集快照 / 增量元数据一致性
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
    """
    解析并校验完整备份链（全量+多层增量）
    功能：传入任意一层备份目录，自动向上追溯至最底层全量基线备份，完成全链路合法性校验，返回有序备份链
    恢复逻辑顺序：全量备份 -> 增量1 -> 增量2 ... -> 目标备份
    Args:
        target_dir (str): 需要恢复的目标备份集目录路径（字符串）
    Returns:
        list[tuple[Path, dict]]: 有序备份链列表，元素格式 (备份目录Path, manifest解析字典)
    Raises:
        RuntimeError: 任意校验不通过时抛出，包含如下场景：
            1. 目标备份目录命名不符合规范
            2. 备份链存在循环依赖
            3. 父备份跑出备份根目录、命名非法
            4. 整条链基线base_backup_set_id不统一
            5. 全量备份元数据异常、增量父备份ID非法
            6. 备份链断裂不连续
            7. documents/media快照/增量清单与链条元数据不一致
    """
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
    # 反转反向链条，得到标准恢复顺序：\[全量, 增量1, 增量2, ..., 目标备份\]
    chain_members = list(reversed(reverse_chain))
    previous_id = None
    # 正向遍历完整有序备份链，校验层与层之间连续性、文件集元数据统一
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
