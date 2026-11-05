from dataclasses import replace

from PySide6.QtCore import QCoreApplication
from test_official_install import environment, wheel_file
from test_worker_integration import wait_for

from media_downloader.repository import Store
from media_downloader.scheduler import TaskService
from media_downloader.update_manager import UpdateManager


def test_direct_upstream_update_uses_idle_switch_without_signed_parser_feed(tmp_path, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    engines = environment(tmp_path)
    archive, wheel = wheel_file(tmp_path)
    store = Store(tmp_path / "tasks.sqlite3")
    service = TaskService(store, engine=engines.bundled, max_workers=1)
    manager = UpdateManager(service, engines)
    monkeypatch.setattr("media_downloader.official_packages.check_latest", lambda **_: wheel)

    def download(_, target, **__):
        target.write_bytes(archive.read_bytes())

    def switch(engine):
        service.engine = engine
        service.engine_activated.emit(engine)

    monkeypatch.setattr("media_downloader.official_packages.download_wheel", download)
    monkeypatch.setattr(service, "switch_engine", switch)
    # No release-signing key or catalog is involved in upstream package acquisition.
    assert not engines.trust.configured
    try:
        manager.check("parsehub")
        wait_for(app, lambda: manager.status == "available")
        assert manager.manifest["official"] and manager.manifest["engine_version"] == "2.5.0"
        service.running["busy"] = {}
        manager.install()
        wait_for(app, lambda: manager.status == "waiting")
        assert engines.state()["current"] == "bundled" and service.dispatch_paused
        service.running.clear()
        wait_for(app, lambda: manager.status == "updated")
        # A restart happens after background pruning releases the update lock.
        manager.executor.submit(lambda: None).result(timeout=5)
        assert service.engine.parser_version == "2.5.0"
        assert engines.recover() == service.engine
        manager.rollback()
        wait_for(app, lambda: manager.status == "rolled_back")
        assert service.engine == engines.bundled
    finally:
        manager.shutdown()
        service.shutdown()
        store.close()


def test_official_check_does_not_offer_upstream_downgrade(tmp_path, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    engines = environment(tmp_path)
    engines.bundled = replace(engines.bundled, parser_version="2.6.0", parser_component_version="2.6.0")
    _, wheel = wheel_file(tmp_path)
    store = Store(tmp_path / "tasks.sqlite3")
    service = TaskService(store, engine=engines.bundled, max_workers=1)
    manager = UpdateManager(service, engines)
    monkeypatch.setattr("media_downloader.official_packages.check_latest", lambda **_: wheel)
    try:
        manager.check("parsehub")
        wait_for(app, lambda: not manager.busy)
        assert manager.status == "idle" and manager.manifest is None
        assert engines.recover() == engines.bundled
    finally:
        manager.shutdown()
        service.shutdown()
        store.close()
