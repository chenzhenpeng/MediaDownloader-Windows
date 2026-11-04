import httpx

from media_downloader.official_update import OFFICIAL_API, check_official_release


def test_official_metadata_is_not_treated_as_an_installable_package(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "tag_name": "v2.4.0",
                "target_commitish": "baseline",
                "assets": [{"browser_download_url": "https://example.invalid/code.exe"}],
            },
        )

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond))
    )
    result = check_official_release("baseline")
    assert result["status"] == "current" and result["tag"] == "v2.4.0"
    assert len(requests) == 1 and str(requests[0].url) == OFFICIAL_API
    assert "cookie" not in requests[0].headers
    assert check_official_release("different")["status"] == "different"


def test_official_rate_limit_is_a_clear_retryable_result(monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(403))
        ),
    )
    result = check_official_release("baseline")
    assert result["status"] == "error" and "频率" in result["message"]
