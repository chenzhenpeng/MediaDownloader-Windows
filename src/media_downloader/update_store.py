"""Verified immutable engine installations and crash-safe pointer transitions."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from .component_catalog import verify_catalog
from .engine import resolve_engine
from .engine_health import probe_engine
from .task_files import atomic_json
from .update_archive import extract_archive, no_reparse, verify_inventory
from .update_contracts import UpdateError, digest_file, fail, release_id, strict_json, verify_manifest


@contextmanager
def update_lock(root, *, name="update.lock"):
    no_reparse(root)
    root.mkdir(parents=True, exist_ok=True)
    if name not in {"update.lock", "update-session.lock"}:
        raise ValueError("Invalid update lock name")
    path = root / name
    no_reparse(path)
    with path.open("a+b") as stream:
        stream.write(b"\0") if path.stat().st_size == 0 else None
        stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise UpdateError("UPDATE_BUSY", "另一个内核更新操作正在进行。") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class EngineStore:
    def __init__(self, root, trust, bundled, *, probe=probe_engine):
        self.root, self.trust, self.bundled, self.probe = Path(root), trust, bundled, probe
        self.state_path = self.root / "engine-state.json"
        no_reparse(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.recovery_message = ""

    def state(self):
        default = {
            "schema": 1,
            "generation": 0,
            "current": "bundled",
            "last_good": "bundled",
            "pending": None,
        }
        if not self.state_path.exists():
            return default
        try:
            no_reparse(self.state_path)
            if self.state_path.stat().st_size > 32768:
                raise ValueError("Oversize state")
            data = strict_json(self.state_path.read_bytes())
            if (
                data["schema"] != 1
                or type(data["generation"]) is not int
                or not isinstance(data["current"], str)
                or not isinstance(data["last_good"], str)
                or data["pending"] is not None
                and not isinstance(data["pending"], dict)
            ):
                raise ValueError("Invalid state")
            return data
        except (OSError, ValueError, TypeError, KeyError):
            self.recovery_message = "内核状态记录损坏，已回到随客户端提供的内核。"
            return default

    def write_state(self, value):
        no_reparse(self.state_path)
        atomic_json(self.state_path, value)

    def accept(self, raw, signature):
        manifest = verify_manifest(raw, signature, self.trust)
        if manifest.get("component") == "parsehub":
            _, runtime = self.active_runtime()
            if not runtime.runtime_id or runtime.runtime_id != manifest.get("requires_runtime_id"):
                fail("UPDATE_RUNTIME", "此解析组件需要先更新执行运行环境。")
        path = self.root / (
            "parser-update-policy.json" if manifest.get("component") == "parsehub" else "update-policy.json"
        )
        with update_lock(self.root):
            try:
                no_reparse(path)
                policy = strict_json(path.read_bytes()) if path.exists() else {"sequence": 0, "versions": {}}
                sequence, versions = policy["sequence"], policy["versions"]
                if type(sequence) is not int or not isinstance(versions, dict):
                    raise ValueError("Invalid replay policy")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise UpdateError(
                    "UPDATE_POLICY", "更新防重放记录损坏，请修复客户端；当前内核仍可使用。"
                ) from exc
            raw_hash = hashlib.sha256(raw).hexdigest()
            if manifest["sequence"] < sequence or (
                manifest["sequence"] == sequence and policy.get("manifest_hash") != raw_hash
            ):
                fail("UPDATE_REPLAY", "更新清单序号过旧或与已接受的清单冲突。")
            version, digest = manifest["engine_version"], manifest["sha256"]
            if version in versions and versions[version] != digest:
                fail("UPDATE_IMMUTABLE", "相同内核版本对应了不同文件，已拒绝更新。")
            versions[version] = digest
            atomic_json(
                path, {"sequence": manifest["sequence"], "manifest_hash": raw_hash, "versions": versions}
            )
        return manifest

    def accept_catalog(self, raw, signature):
        data, releases = verify_catalog(raw, signature, self.trust)
        path = self.root / "catalog-policy.json"
        with update_lock(self.root):
            no_reparse(path)
            try:
                if path.exists() and path.stat().st_size > 4096:
                    raise ValueError("Oversize catalog policy")
                policy = strict_json(path.read_bytes()) if path.exists() else {"sequence": 0}
                sequence = policy["sequence"]
                if type(sequence) is not int:
                    raise ValueError("Invalid sequence")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise UpdateError("UPDATE_POLICY", "组件目录防重放记录无效。") from exc
            digest = hashlib.sha256(raw).hexdigest()
            if data["sequence"] < sequence or data["sequence"] == sequence and policy.get("sha256") != digest:
                fail("UPDATE_REPLAY", "组件更新目录过旧或与已接受目录冲突。")
            atomic_json(path, {"sequence": data["sequence"], "sha256": digest})
        return releases

    def runtime_reference(self, identity):
        path = self.root / "engines" / identity / "runtime-reference.json"
        no_reparse(path)
        if not path.exists():
            return "bundled"  # Before composition records, parser packages used the bundled runtime.
        if path.stat().st_size > 4096:
            fail("UPDATE_STATE", "运行环境引用无效。")
        try:
            reference = strict_json(path.read_bytes())["runtime"]
            if reference != "bundled" and not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}-[0-9a-f]{12}", reference
            ):
                raise ValueError("Invalid runtime identity")
            return reference
        except (ValueError, KeyError, TypeError) as exc:
            raise UpdateError("UPDATE_STATE", "运行环境引用无效。") from exc

    def active_runtime(self):
        identity = self.state()["current"]
        if identity == "bundled":
            return identity, self.bundled
        selected = self.installed(identity)
        if selected.component == "parsehub":
            identity = self.runtime_reference(identity)
            selected = self.installed(identity, runtime_only=True)
        return identity, selected

    def installed(self, identity, *, require_healthy=True, runtime_only=False):
        if identity == "bundled":
            return self.bundled
        if not isinstance(identity, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}-[0-9a-f]{12}", identity
        ):
            fail("UPDATE_STATE", "内核版本指针无效。")
        directory = self.root / "engines" / identity
        no_reparse(directory)
        no_reparse(directory / "release.json")
        no_reparse(directory / "release.sig")
        if (directory / "release.json").stat().st_size > 131072 or (
            directory / "release.sig"
        ).stat().st_size != 64:
            fail("UPDATE_SIGNATURE", "已安装内核的签名记录大小无效。")
        manifest = verify_manifest(
            (directory / "release.json").read_bytes(),
            (directory / "release.sig").read_bytes(),
            self.trust,
            installed=True,
        )
        if release_id(manifest) != identity:
            fail("UPDATE_STATE", "已安装内核与版本指针不一致。")
        if require_healthy:
            marker = directory / "healthy.json"
            no_reparse(marker)
            if not marker.is_file() or marker.stat().st_size > 4096:
                fail("UPDATE_HEALTH", "候选内核尚未完成自检，不能作为当前内核。")
            health = strict_json(marker.read_bytes())
            if not isinstance(health, dict) or health.get("manifest_sha256") != digest_file(
                directory / "release.json"
            ):
                fail("UPDATE_HEALTH", "候选内核尚未完成自检，不能作为当前内核。")
        verify_inventory(directory / "payload", manifest)
        runtime = self.bundled
        if manifest.get("component") == "parsehub":
            if runtime_only:
                fail("UPDATE_STATE", "解析组件不能用作执行运行环境。")
            runtime = self.installed(self.runtime_reference(identity), runtime_only=True)
        engine = resolve_engine(directory / "payload", runtime=runtime)
        if engine.version != manifest["engine_version"] or engine.upstream_sha != manifest["upstream_sha"]:
            fail("UPDATE_INVENTORY", "内核描述与签名发布清单不一致。")
        return engine

    def recover(self):
        with update_lock(self.root):
            state = self.state()
            preferred = state["last_good"] if state["pending"] else state["current"]
            for identity in dict.fromkeys((preferred, state["last_good"], "bundled")):
                try:
                    engine = self.installed(identity)
                    if identity != state["current"] or state["pending"] or self.recovery_message:
                        self.write_state(
                            {
                                **state,
                                "current": identity,
                                "pending": None,
                                "generation": state["generation"] + 1,
                            }
                        )
                        self.recovery_message = (
                            self.recovery_message or "上次内核切换未完成，已恢复可用版本。"
                        )
                    return engine
                except (OSError, ValueError, KeyError, UpdateError):
                    continue
            fail("UPDATE_RECOVERY", "无法恢复可用内核，请修复安装。")

    def install(self, archive, raw, signature, *, cancelled=lambda: False):
        manifest = self.accept(raw, signature)
        runtime_identity, runtime = (
            self.active_runtime() if manifest.get("component") == "parsehub" else ("bundled", self.bundled)
        )
        identity = release_id(manifest)
        with update_lock(self.root):
            target = self.root / "engines" / identity
            no_reparse(target)
            if target.exists():
                engine = self.installed(identity, require_healthy=False)
                if not (target / "healthy.json").exists():
                    self.probe(engine, cancelled=cancelled)
                    verify_inventory(target / "payload", manifest)
                    if cancelled():
                        fail("UPDATE_CANCELLED", "更新已取消。")
                    atomic_json(target / "healthy.json", {"manifest_sha256": hashlib.sha256(raw).hexdigest()})
                return identity, self.installed(identity)
            if (
                Path(archive).stat().st_size != manifest["size_bytes"]
                or digest_file(archive) != manifest["sha256"]
            ):
                fail("UPDATE_HASH", "更新包不完整或哈希校验失败。")
            stage = self.root / "updates" / "staging" / uuid.uuid4().hex
            no_reparse(stage)
            stage.mkdir(parents=True)
            # Failed staging remains quarantined; it is never selected by recovery.
            extract_archive(Path(archive), stage / "payload", manifest, cancelled=cancelled)
            (stage / "release.json").write_bytes(raw)
            (stage / "release.sig").write_bytes(signature)
            if manifest.get("component") == "parsehub":
                atomic_json(stage / "runtime-reference.json", {"runtime": runtime_identity})
            engine = resolve_engine(stage / "payload", runtime=runtime)
            if (
                engine.version != manifest["engine_version"]
                or engine.upstream_sha != manifest["upstream_sha"]
            ):
                fail("UPDATE_HEALTH", "候选内核描述与签名清单不一致。")
            if cancelled():
                fail("UPDATE_CANCELLED", "更新已取消。")
            target.parent.mkdir(parents=True, exist_ok=True)
            no_reparse(target.parent)
            # Place verified bytes before execution. On Windows a probe can leave DLL
            # mappings briefly locked; never rename a directory after loading its code.
            # Recovery requires healthy.json, so this remains an inactive candidate.
            os.rename(stage, target)
            engine = self.installed(identity, require_healthy=False)
            self.probe(engine, cancelled=cancelled)
            verify_inventory(target / "payload", manifest)
            if cancelled():
                fail("UPDATE_CANCELLED", "更新已取消。")
            atomic_json(target / "healthy.json", {"manifest_sha256": hashlib.sha256(raw).hexdigest()})
            return identity, self.installed(identity)

    def begin(self, identity):
        with update_lock(self.root):
            state = self.state()
            if state["pending"]:
                fail("UPDATE_BUSY", "内核切换尚未完成。")
            state["pending"] = {"from": state["current"], "to": identity}
            state["last_good"] = state["current"]
            state["generation"] += 1
            self.write_state(state)

    def confirm(self, identity):
        with update_lock(self.root):
            state = self.state()
            if not state["pending"] or state["pending"].get("to") != identity:
                fail("UPDATE_STATE", "内核切换记录不匹配。")
            self.write_state(
                {**state, "current": identity, "pending": None, "generation": state["generation"] + 1}
            )

    def abort(self):
        with update_lock(self.root):
            state = self.state()
            self.write_state(
                {
                    **state,
                    "current": state["last_good"],
                    "pending": None,
                    "generation": state["generation"] + 1,
                }
            )

    def discard_staging(self):
        # Called only while holding the update lock and with no active update job.
        parent = self.root / "updates" / "staging"
        no_reparse(parent)
        if parent.exists():
            for directory in parent.iterdir():
                if re.fullmatch(r"[0-9a-f]{32}", directory.name):
                    no_reparse(directory)
                    for child in directory.rglob("*"):
                        no_reparse(child)
                    if directory.resolve().parent != parent.resolve():
                        fail("UPDATE_PATH", "临时更新目录超出预期范围。")
                    shutil.rmtree(directory)

    def prune(self):
        with update_lock(self.root):
            state = self.state()
            if state["pending"]:
                return
            keep = {state["current"], state["last_good"]}
            for identity in tuple(keep):
                if (
                    identity != "bundled"
                    and (self.root / "engines" / identity / "runtime-reference.json").exists()
                ):
                    keep.add(self.runtime_reference(identity))
            parent = self.root / "engines"
            no_reparse(parent)
            if not parent.exists():
                return
            for directory in parent.iterdir():
                if directory.name in keep or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}-[0-9a-f]{12}", directory.name
                ):
                    continue
                no_reparse(directory)
                for child in directory.rglob("*"):
                    no_reparse(child)
                if directory.resolve().parent != parent.resolve():
                    fail("UPDATE_PATH", "旧内核目录超出预期范围。")
                shutil.rmtree(directory)
