"""Build a native x64 Windows Installer package; no x86 bootstrapper is used."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "0.2.0-preview.13"
MSI_VERSION = "0.2.9"  # Third field is the monotonically increasing release sequence.
UPGRADE = uuid.UUID("8f5574cb-a715-4ba1-ad07-4212a70d460b")
NS = "http://wixtoolset.org/schemas/v4/wxs"
UI = "http://wixtoolset.org/schemas/v4/wxs/ui"
ET.register_namespace("", NS)
ET.register_namespace("ui", UI)


def element(parent, kind, **attrs):
    return ET.SubElement(parent, f"{{{NS}}}{kind}", attrs)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identifier(prefix, value):
    return prefix + hashlib.sha256(value.encode()).hexdigest()[:24]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa", action="store_true")
    args = parser.parse_args()
    payload = ROOT / "dist/native/MediaDownloader"
    work = ROOT / "build/msi" / ("qa" if args.qa else "release")
    output = ROOT / ("build/msi-qa" if args.qa else "dist/release")
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    upgrade = uuid.uuid5(UPGRADE, "msi-qa") if args.qa else UPGRADE
    product = uuid.uuid5(upgrade, MSI_VERSION)
    app_key = r"Software\MediaDownloaderMSIQA" if args.qa else r"Software\MediaDownloader"
    name = "Media Downloader MSI QA" if args.qa else "Media Downloader"
    root = ET.Element(f"{{{NS}}}Wix")
    package = element(
        root,
        "Package",
        Name=name,
        Manufacturer="Media Downloader Project",
        Version=MSI_VERSION,
        Language="2052",
        Scope="perMachine",
        UpgradeCode=str(upgrade),
        ProductCode=str(product),
    )
    element(
        package,
        "SummaryInformation",
        Description=f"{name} {RELEASE} x64",
        Manufacturer="Media Downloader Project",
    )
    element(package, "MajorUpgrade", DowngradeErrorMessage="已安装更新版本，不能降级安装。")
    element(package, "MediaTemplate", EmbedCab="yes", CompressionLevel="high")
    element(package, "Launch", Condition="Installed OR VersionNT64", Message="此安装包需要 64 位 Windows。")
    if not args.qa:
        # Windows Installer cannot major-upgrade between per-user and
        # per-machine contexts. Detect earlier previews before copying files.
        for sequence in (5, 6):
            previous = str(uuid.uuid5(UPGRADE, f"0.2.{sequence}")).upper()
            prop = f"OLD_PER_USER_{sequence}"
            search = element(package, "Property", Id=prop, Secure="yes")
            element(
                search,
                "RegistrySearch",
                Id=f"FindOldPerUser{sequence}",
                Root="HKCU",
                Bitness="always64",
                Key=rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{previous}}}",
                Name="DisplayName",
                Type="raw",
            )
            element(
                package,
                "Launch",
                Condition=f"Installed OR NOT {prop}",
                Message=(
                    "请先在 Windows 设置中卸载旧版当前用户安装包，再安装新版。任务、Cookie 和下载文件会保留。"
                ),
            )
    if not args.qa:
        legacy = element(package, "Property", Id="LEGACY_INNO", Secure="yes")
        element(
            legacy,
            "RegistrySearch",
            Id="FindLegacyInstaller",
            Root="HKCU",
            Bitness="always64",
            Key=r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{8F5574CB-A715-4BA1-AD07-4212A70D460B}_is1",
            Name="UninstallString",
            Type="raw",
        )
        element(
            package,
            "Launch",
            Condition="Installed OR NOT LEGACY_INNO",
            Message=(
                "请先在 Windows 设置中卸载旧版 EXE 安装包，再安装此 x64 MSI。任务、设置和下载文件会保留。"
            ),
        )
    element(package, "Property", Id="MSIRESTARTMANAGERCONTROL", Value="DisableShutdown")
    remembered = element(package, "Property", Id="INSTALLFOLDER", Secure="yes")
    element(
        remembered,
        "RegistrySearch",
        Id="FindInstalledRoot",
        Root="HKLM",
        Bitness="always64",
        Key=app_key + r"\Installer",
        Name="InstallRoot",
        Type="raw",
    )
    element(package, "Icon", Id="ProductIcon", SourceFile=str(payload / "Assets/AppIcon.ico"))
    element(package, "Property", Id="ARPPRODUCTICON", Value="ProductIcon")
    programs = element(package, "StandardDirectory", Id="ProgramFiles64Folder")
    install = element(
        programs,
        "Directory",
        Id="INSTALLFOLDER",
        Name="MediaDownloaderMSIQA" if args.qa else "MediaDownloader",
    )
    versions = element(install, "Directory", Id="Versions", Name="versions")
    version = element(versions, "Directory", Id="Payload", Name=RELEASE)
    element(package, "StandardDirectory", Id="ProgramMenuFolder")
    feature = element(package, "Feature", Id="Complete", Title="Media Downloader", Level="1")
    root_component = element(
        install,
        "Component",
        Id="RememberInstallRoot",
        Guid=str(uuid.uuid5(upgrade, "install-root-machine")),
        Bitness="always64",
    )
    element(
        root_component,
        "RegistryValue",
        Root="HKLM",
        Key=app_key + r"\Installer",
        Name="InstallRoot",
        Type="string",
        Value="[INSTALLFOLDER]",
        KeyPath="yes",
    )
    element(feature, "ComponentRef", Id="RememberInstallRoot")
    directories = {".": version}
    files = sorted(path for path in payload.rglob("*") if path.is_file())
    if any(path.suffix in {".sqlite3", ".db", ".lock"} for path in files):
        raise RuntimeError("User data in payload")
    for path in files:
        relative = path.relative_to(payload)
        current = Path()
        for part in relative.parts[:-1]:
            parent = current.as_posix()
            current /= part
            if current.as_posix() not in directories:
                directories[current.as_posix()] = element(
                    directories[parent], "Directory", Id=identifier("D", current.as_posix()), Name=part
                )
        component_id = identifier("C", relative.as_posix())
        component = element(
            directories[relative.parent.as_posix()],
            "Component",
            Id=component_id,
            Guid=str(uuid.uuid5(upgrade, RELEASE + "/" + relative.as_posix())),
            Bitness="always64",
        )
        file_id = identifier("F", relative.as_posix())
        element(component, "File", Id=file_id, Source=str(path), KeyPath="no")
        element(
            component,
            "RegistryValue",
            Root="HKLM",
            Key=app_key + r"\Installer\Files",
            Name=component_id,
            Type="string",
            Value=RELEASE,
            KeyPath="yes",
        )
        if relative.as_posix() == "MediaDownloader.exe":
            element(
                component,
                "Shortcut",
                Id="StartMenuShortcut",
                Directory="ProgramMenuFolder",
                Name=name,
                Target=f"[#{file_id}]",
                WorkingDirectory="Payload",
                Icon="ProductIcon",
            )
        element(feature, "ComponentRef", Id=component_id)
    for relative, directory in directories.items():
        component_id = identifier("Cleanup", relative)
        component = element(
            directory,
            "Component",
            Id=component_id,
            Guid=str(uuid.uuid5(upgrade, RELEASE + "/cleanup/" + relative)),
            Bitness="always64",
        )
        element(component, "RemoveFolder", Id=identifier("Remove", relative), On="uninstall")
        element(
            component,
            "RegistryValue",
            Root="HKLM",
            Key=app_key + r"\Installer\Directories",
            Name=component_id,
            Value=RELEASE,
            Type="string",
            KeyPath="yes",
        )
        element(feature, "ComponentRef", Id=component_id)
    ET.SubElement(package, f"{{{UI}}}WixUI", {"Id": "WixUI_InstallDir", "InstallDirectory": "INSTALLFOLDER"})
    # The welcome flow skips the library's generic license page; third-party
    # licenses remain in the payload and are not replaced with invented terms.
    ui = element(package, "UI")
    element(
        ui,
        "Publish",
        Dialog="WelcomeDlg",
        Control="Next",
        Event="NewDialog",
        Value="InstallDirDlg",
        Order="10",
        Condition="NOT Installed",
    )
    element(
        ui,
        "Publish",
        Dialog="InstallDirDlg",
        Control="Back",
        Event="NewDialog",
        Value="WelcomeDlg",
        Order="10",
        Condition="1",
    )
    source = work / "Product.wxs"
    ET.indent(root)
    ET.ElementTree(root).write(source, encoding="utf-8", xml_declaration=True)
    target = output / f"MediaDownloader-{RELEASE}-win-x64{'-QA' if args.qa else ''}.msi"
    env = dict(
        os.environ, DOTNET_ROOT=str(ROOT / ".cache/dotnet"), DOTNET_CLI_HOME=str(ROOT / ".cache/dotnet-home")
    )
    command = [
        str(ROOT / ".cache/installer-tools/wix/wix.exe"),
        "build",
        str(source),
        "-arch",
        "x64",
        "-ext",
        "WixToolset.UI.wixext",
        "-culture",
        "zh-CN",
        "-pdbtype",
        "none",
        "-intermediatefolder",
        str(work / "obj"),
        "-out",
        str(target),
    ]
    with (work / "build.log").open("w", encoding="utf-8") as log:
        subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    report = {
        "release": RELEASE,
        "msi_version": MSI_VERSION,
        "product_code": str(product),
        "installer": str(target.relative_to(ROOT)),
        "architecture": "x64",
        "bytes": target.stat().st_size,
        "sha256": digest(target),
        "files": len(files),
        "qa": args.qa,
        "scope": "perMachine",
        "signed": False,
    }
    (output / "msi-release.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "MSI-SHA256SUMS.txt").write_text(f"{report['sha256']}  {target.name}\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
