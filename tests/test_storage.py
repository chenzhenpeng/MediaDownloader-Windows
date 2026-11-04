from pathlib import PureWindowsPath

import pytest

from media_downloader.storage import Store, extract_links, safe_name
from media_downloader.windows import protect, unprotect


@pytest.mark.parametrize("platform,folder", [("xhs", "小红书"), ("douyin", "抖音"), ("bilibili", "哔哩哔哩")])
def test_post_directory_layout_and_legacy_compatibility(tmp_path, platform, folder):
    from media_downloader.storage import output_directory, valid_output_directory

    path = output_directory(tmp_path, platform, "帖子:标题/图集", "a" * 32, "b" * 32)
    assert path.parent == tmp_path.resolve() / folder
    assert path.name == "帖子_标题_图集_aaaaaaaa_bbbbbb"
    assert valid_output_directory(tmp_path, path, "a" * 32, "b" * 32)
    assert valid_output_directory(tmp_path, tmp_path / path.name, "a" * 32, "b" * 32)
    assert not valid_output_directory(tmp_path, tmp_path / "任意目录" / path.name, "a" * 32, "b" * 32)
    assert not valid_output_directory(tmp_path, tmp_path.parent / path.name, "a" * 32, "b" * 32)
    assert output_directory(tmp_path, platform, "same", "a" * 32, "c" * 32) != path


def test_platform_directory_commit_verification_and_no_overwrite(tmp_path):
    from media_downloader.storage import output_directory
    from media_downloader.task_files import atomic_json, build_manifest, verify_output, work_directory

    task, attempt, token = "a" * 32, "b" * 32, "c" * 32
    work = work_directory(tmp_path, task, attempt) / "payload"
    work.mkdir(parents=True)
    (work / "001_帖子.jpg").write_bytes(b"image one")
    (work / "002_帖子.jpg").write_bytes(b"image two")
    command = {"task_id": task, "attempt_id": attempt, "output_root": str(tmp_path)}
    manifest = build_manifest(work, command, {}, "test", "test")
    manifest["commit_token"] = token
    atomic_json(work / "manifest.json", manifest)
    final = output_directory(tmp_path, "xhs", "帖子", task, attempt)
    final.parent.mkdir()
    work.rename(final)
    assert len(verify_output(tmp_path, str(final), task, attempt, token)["files"]) == 2
    work.mkdir()
    with pytest.raises(OSError):
        work.rename(final)
    assert (final / "001_帖子.jpg").read_bytes() == b"image one"


def test_post_directory_long_title_budget(tmp_path):
    from media_downloader.storage import output_directory

    path = output_directory(tmp_path, "xhs", "很长标题" * 100, "a" * 32, "b" * 32)
    stem = path.name.rsplit("_", 2)[0]
    assert len(str(path / f"001_{stem}.jpg")) <= 240
    with pytest.raises(Exception) as error:
        output_directory(tmp_path / ("x" * 200), "xhs", "帖子", "a" * 32, "b" * 32)
    assert error.value.code == "PATH_TOO_LONG"


def test_links_reject_lookalike_hosts_and_preserve_signed_queries():
    text = (
        "分享 https://www.douyin.com/video/123。 https://evil-douyin.com/video/456 "
        "https://www.xiaohongshu.com/explore/abc?xsec_token=secret "
        "https://www.douyin.com/video/123"
    )
    assert extract_links(text) == [
        "https://www.douyin.com/video/123",
        "https://www.xiaohongshu.com/explore/abc?xsec_token=secret",
    ]


@pytest.mark.parametrize(
    "name", ["CON.mp4", "nul", "LPT1", "COM9.txt", "a/../b", "a\x00b", "x. ", "CONIN$", "COM¹.mp4"]
)
def test_windows_file_names(name):
    assert not PureWindowsPath(safe_name(name)).is_reserved()


def test_dpapi_and_recovery_keep_source_encrypted(tmp_path):
    secret = "https://www.xiaohongshu.com/explore/abc?xsec_token=private-token"
    assert unprotect(protect(secret)) == secret
    store = Store(tmp_path / "tasks.db")
    task_id = store.create(secret, str(tmp_path))
    assert secret.encode() not in store.get(task_id)["source"]
    store.update(task_id, state="downloading")
    store.close()
    store = Store(tmp_path / "tasks.db")
    assert store.get(task_id)["state"] == "interrupted"
    assert store.source(task_id) == secret
    store.close()
