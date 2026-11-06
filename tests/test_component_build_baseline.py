import json

import httpx
import pytest
from scripts.build_official_runtime import pinned_wheel
from test_official_packages import artifact, metadata


def test_worker_build_uses_pinned_official_version_not_latest(monkeypatch):
    _, wheel = artifact()
    seen = []
    client_class = httpx.Client

    def respond(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=json.dumps(metadata(wheel)).encode())

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client_class(**kwargs, transport=httpx.MockTransport(respond))
    )
    assert pinned_wheel("2.4.0") == wheel
    assert seen == ["https://pypi.org/pypi/parsehub/2.4.0/json"]


@pytest.mark.parametrize("version", ["../../other", "2.4.0?token=x", "2.5.0.dev1"])
def test_invalid_build_baseline_never_requests_pypi(version):
    with pytest.raises(ValueError, match="Invalid locked"):
        pinned_wheel(version)
