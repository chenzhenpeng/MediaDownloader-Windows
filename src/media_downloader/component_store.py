"""Independent component storage with one atomic, probed execution-profile pointer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from .engine_health import probe_engine
from .execution_profile import KINDS, component_id, compose, descriptor
from .task_files import atomic_json
from .update_archive import extract_archive, no_reparse, verify_inventory
from .update_contracts import UpdateError, digest_file, fail, strict_json, verify_manifest
from .update_store import update_lock


class ComponentStore:
    def __init__(self, root, trust, bundled, *, probe=probe_engine):
        if not bundled.components:
            raise ValueError("A split component bundle is required; old layouts are not supported")
        self.root, self.trust, self.bundled, self.probe = Path(root), trust, bundled, probe
        no_reparse(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "execution-state.json"
        self.recovery_message = ""

    def state(self):
        default = {
            "schema": 2,
            "generation": 0,
            "current": "bundled",
            "last_good": "bundled",
            "pending": None,
        }
        if not self.state_path.exists():
            return default
        try:
            data = self.read(self.state_path, 32768)
            if (
                data["schema"] != 2
                or type(data["generation"]) is not int
                or not all(self.valid_profile(data[k]) for k in ("current", "last_good"))
                or data["pending"] is not None
                and (
                    not isinstance(data["pending"], dict)
                    or not all(self.valid_profile(data["pending"].get(k)) for k in ("from", "to"))
                )
            ):
                raise ValueError("Invalid profile state")
            return data
        except (OSError, ValueError, KeyError, TypeError):
            self.recovery_message = "执行组合状态损坏，已恢复随应用提供的组合。"
            return default

    @staticmethod
    def valid_profile(value):
        return isinstance(value, str) and (
            value == "bundled" or bool(re.fullmatch(r"profile-[0-9a-f]{24}", value))
        )

    @staticmethod
    def read(path, limit):
        no_reparse(path)
        if path.stat().st_size > limit:
            raise ValueError("Oversize component record")
        return strict_json(path.read_bytes())

    def write_state(self, state):
        no_reparse(self.state_path)
        atomic_json(self.state_path, state)

    def refs(self, identity=None):
        identity = identity or self.state()["current"]
        if identity == "bundled":
            return {kind: "bundled" for kind in KINDS}
        if not self.valid_profile(identity):
            raise ValueError("Invalid profile identity")
        record = self.read(self.root / "profiles" / identity / "profile.json", 32768)
        if (
            record.get("schema") != 1
            or set(record["components"]) != set(KINDS)
            or self.profile_id(record["components"]) != identity
        ):
            raise ValueError("Profile identity mismatch")
        return record["components"]

    @staticmethod
    def profile_id(refs):
        return "profile-" + hashlib.sha256(json.dumps(refs, sort_keys=True).encode()).hexdigest()[:24]

    def component_path(self, kind, identity):
        if kind not in KINDS:
            raise ValueError("Unknown component")
        if identity == "bundled":
            return Path(self.bundled.components[kind])
        if kind == "media-tools" and re.fullmatch(r"media-tools-local-[0-9a-f]{12}", identity):
            directory = self.root / "local-tools" / identity
            data = descriptor(directory, kind)
            expected = (
                "media-tools-local-"
                + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
            )
            if identity != expected or not data.get("external_directory"):
                raise ValueError("Local tool receipt mismatch")
            return directory
        if not isinstance(identity, str) or not re.fullmatch(
            re.escape(kind) + r"-[A-Za-z0-9][A-Za-z0-9._-]{0,47}-[0-9a-f]{12}", identity
        ):
            raise ValueError("Invalid component pointer")
        directory = self.root / "components" / identity
        no_reparse(directory)
        payload = directory / "payload"
        if kind == "parsehub":
            from .official_install import checked_receipt

            receipt = self.read(directory / "official-wheel.json", 8192)
            wheel = checked_receipt(receipt)
            if component_id(kind, wheel.version, wheel.sha256) != identity:
                raise ValueError("Official package identity mismatch")
            data = descriptor(payload, kind)
            if data["wheel"] != receipt["wheel"]:
                raise ValueError("Official receipt mismatch")
        else:
            manifest = verify_manifest(
                (directory / "release.json").read_bytes(),
                (directory / "release.sig").read_bytes(),
                self.trust,
                installed=True,
            )
            if (
                manifest["component"] != kind
                or component_id(kind, manifest["engine_version"], manifest["sha256"]) != identity
            ):
                raise ValueError("Signed component identity mismatch")
            verify_inventory(payload, manifest)
        return payload

    def installed(self, identity, *, require_healthy=True, **_):
        refs = self.refs(identity)
        if identity != "bundled" and require_healthy:
            directory = self.root / "profiles" / identity
            marker = self.read(directory / "healthy.json", 4096)
            if marker.get("profile_sha256") != digest_file(directory / "profile.json"):
                fail("UPDATE_HEALTH", "执行组合尚未完成自检。")
        return compose({kind: self.component_path(kind, value) for kind, value in refs.items()})

    def active_runtime(self):
        identity = self.state()["current"]
        return identity, self.installed(identity)

    def accept(self, raw, signature):
        manifest = verify_manifest(raw, signature, self.trust)
        kind = manifest["component"]
        if kind not in {"worker", "python-runtime", "media-tools"}:
            fail("UPDATE_INCOMPATIBLE", "签名组件类型不适用于当前执行组合。")
        path = self.root / (kind + "-policy.json")
        with update_lock(self.root):
            policy = self.read(path, 1024**2) if path.exists() else {"sequence": 0, "versions": {}}
            digest = hashlib.sha256(raw).hexdigest()
            if (
                manifest["sequence"] < policy["sequence"]
                or manifest["sequence"] == policy["sequence"]
                and policy.get("manifest_hash") != digest
            ):
                fail("UPDATE_REPLAY", "组件清单过旧或冲突。")
            versions = policy["versions"]
            version = manifest["engine_version"]
            if version in versions and versions[version] != manifest["sha256"]:
                fail("UPDATE_IMMUTABLE", "相同组件版本对应不同内容。")
            versions[version] = manifest["sha256"]
            atomic_json(
                path, {"sequence": manifest["sequence"], "manifest_hash": digest, "versions": versions}
            )
        return manifest

    def accept_catalog(self, raw, signature):
        from .component_catalog import verify_catalog

        data, releases = verify_catalog(raw, signature, self.trust)
        path = self.root / "catalog-policy.json"
        with update_lock(self.root):
            policy = self.read(path, 4096) if path.exists() else {"sequence": 0}
            digest = hashlib.sha256(raw).hexdigest()
            if (
                data["sequence"] < policy["sequence"]
                or data["sequence"] == policy["sequence"]
                and policy.get("sha256") != digest
            ):
                fail("UPDATE_REPLAY", "执行组件目录过旧或冲突。")
            atomic_json(path, {"sequence": data["sequence"], "sha256": digest})
        return releases

    def stage_component(self, archive, raw, signature, *, cancelled=lambda: False):
        manifest = self.accept(raw, signature)
        kind = manifest["component"]
        identity = component_id(kind, manifest["engine_version"], manifest["sha256"])
        target = self.root / "components" / identity
        no_reparse(target)
        if target.exists():
            self.component_path(kind, identity)
            return identity
        if (
            Path(archive).stat().st_size != manifest["size_bytes"]
            or digest_file(archive) != manifest["sha256"]
        ):
            fail("UPDATE_HASH", "组件包不完整或摘要不符。")
        stage = self.root / "updates/staging" / uuid.uuid4().hex
        no_reparse(stage)
        stage.mkdir(parents=True)
        extract_archive(archive, stage / "payload", manifest, cancelled=cancelled)
        data = descriptor(stage / "payload", kind)
        if data["version"] != manifest["engine_version"]:
            raise ValueError("Descriptor and signed version differ")
        (stage / "release.json").write_bytes(raw)
        (stage / "release.sig").write_bytes(signature)
        if cancelled():
            fail("UPDATE_CANCELLED", "更新已取消。")
        with update_lock(self.root):
            target.parent.mkdir(parents=True, exist_ok=True)
            os.rename(stage, target)
        self.component_path(kind, identity)
        return identity

    def prepare(self, refs, *, cancelled=lambda: False):
        identity = self.profile_id(refs)
        directory = self.root / "profiles" / identity
        no_reparse(directory)
        with update_lock(self.root):
            directory.mkdir(parents=True, exist_ok=True)
            atomic_json(directory / "profile.json", {"schema": 1, "components": refs})
        engine = self.installed(identity, require_healthy=False)
        self.probe(engine, cancelled=cancelled)
        self.installed(identity, require_healthy=False)  # Recheck bytes after execution.
        if cancelled():
            fail("UPDATE_CANCELLED", "更新已取消。")
        atomic_json(directory / "healthy.json", {"profile_sha256": digest_file(directory / "profile.json")})
        return identity, engine

    def install(self, archive, raw, signature, *, cancelled=lambda: False):
        identity = self.stage_component(archive, raw, signature, cancelled=cancelled)
        refs = self.refs()
        refs[verify_manifest(raw, signature, self.trust)["component"]] = identity
        return self.prepare(refs, cancelled=cancelled)

    def install_official(self, wheel, archive, *, cancelled=lambda: False):
        from dataclasses import asdict

        from .official_packages import extract_wheel

        _, current = self.active_runtime()
        contract = descriptor(current.components["python-runtime"], "python-runtime")["contract"]
        identity = component_id("parsehub", wheel.version, wheel.sha256)
        target = self.root / "components" / identity
        no_reparse(target)
        if not target.exists():
            stage = self.root / "updates/staging" / uuid.uuid4().hex
            no_reparse(stage)
            (stage / "payload").mkdir(parents=True)
            extract_wheel(archive, wheel, contract, stage / "payload/python", cancelled=cancelled)
            shutil.copy2(archive, stage / "payload" / wheel.filename)
            atomic_json(
                stage / "payload/component.json",
                {
                    "schema": 1,
                    "kind": "parsehub",
                    "version": wheel.version,
                    "target": "windows-x86_64",
                    "wheel": asdict(wheel),
                },
            )
            atomic_json(stage / "official-wheel.json", {"schema": 1, "wheel": asdict(wheel)})
            with update_lock(self.root):
                target.parent.mkdir(parents=True, exist_ok=True)
                os.rename(stage, target)
        refs = self.refs()
        refs["parsehub"] = identity
        return self.prepare(refs, cancelled=cancelled)

    def configure_tools(self, directory=None, *, cancelled=lambda: False):
        refs = self.refs()
        if directory:
            from .local_media_tools import inspect_local_tools

            identity, data = inspect_local_tools(directory)
            target = self.root / "local-tools" / identity
            no_reparse(target)
            target.mkdir(parents=True, exist_ok=True)
            atomic_json(target / "component.json", data)
            refs["media-tools"] = identity
        else:
            refs["media-tools"] = "bundled"
        return self.prepare(refs, cancelled=cancelled)

    def begin(self, identity):
        if not self.valid_profile(identity):
            raise ValueError("Invalid candidate profile")
        with update_lock(self.root):
            state = self.state()
            if state["pending"]:
                fail("UPDATE_BUSY", "上次组合切换尚未完成。")
            self.write_state(
                {
                    **state,
                    "last_good": state["current"],
                    "generation": state["generation"] + 1,
                    "pending": {"from": state["current"], "to": identity},
                }
            )

    def confirm(self, identity):
        with update_lock(self.root):
            state = self.state()
            if not state["pending"] or state["pending"]["to"] != identity:
                fail("UPDATE_STATE", "组合切换记录不匹配。")
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

    def recover(self):
        state = self.state()
        for identity in dict.fromkeys(
            (state["last_good"] if state["pending"] else state["current"], state["last_good"], "bundled")
        ):
            try:
                engine = self.installed(identity)
                if identity != state["current"] or state["pending"]:
                    self.write_state(
                        {**state, "current": identity, "pending": None, "generation": state["generation"] + 1}
                    )
                    self.recovery_message = "未完成的执行组合切换已回滚。"
                return engine
            except (OSError, ValueError, KeyError, RuntimeError, UpdateError):
                continue
        fail("UPDATE_RECOVERY", "无法恢复执行组合，请修复安装。")

    def discard_staging(self):
        parent = self.root / "updates/staging"
        no_reparse(parent)
        if parent.exists():
            for directory in parent.iterdir():
                if re.fullmatch(r"[0-9a-f]{32}", directory.name):
                    self.remove_owned(directory, parent)

    @staticmethod
    def remove_owned(directory, parent):
        no_reparse(directory)
        if directory.resolve().parent != parent.resolve():
            raise ValueError("Cleanup escaped owned directory")
        for child in directory.rglob("*"):
            no_reparse(child)
        shutil.rmtree(directory)

    def prune(self):
        with update_lock(self.root):
            state = self.state()
            if state["pending"]:
                return
            keep = {state["current"], state["last_good"]}
            components = {reference for identity in keep for reference in self.refs(identity).values()}
            for category, retained, pattern in (
                ("profiles", keep, r"profile-[0-9a-f]{24}"),
                ("components", components, r"(?:worker|python-runtime|parsehub|media-tools)-.+-[0-9a-f]{12}"),
            ):
                parent = self.root / category
                no_reparse(parent)
                if parent.exists():
                    for directory in parent.iterdir():
                        if directory.name not in retained and re.fullmatch(pattern, directory.name):
                            self.remove_owned(directory, parent)
