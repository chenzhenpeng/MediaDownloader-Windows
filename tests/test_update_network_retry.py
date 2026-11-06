import httpx
import pytest

from media_downloader.update_contracts import Trust, UpdateError
from media_downloader.update_feed import UpdateFeed


def feed(handler):
    trust = Trust("stable", {}, ("updates.example",))
    return UpdateFeed(trust, transport=httpx.MockTransport(handler))


def test_transient_connection_failure_retries_bounded_metadata():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectTimeout("not exposed", request=request)
        return httpx.Response(200, stream=httpx.ByteStream(b"verified later"))

    assert feed(handler).bounded("https://updates.example/catalog", 100) == b"verified later"
    assert len(calls) == 3


def test_partial_metadata_is_discarded_before_retry():
    calls = []

    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b"p" * 65536
            raise httpx.ReadError("interrupted")

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(200, stream=Interrupted())
            if len(calls) == 1
            else httpx.Response(200, stream=httpx.ByteStream(b"new"))
        )

    assert feed(handler).bounded("https://updates.example/catalog", 100000) == b"new"
    assert len(calls) == 2


@pytest.mark.parametrize("status", [403, 404])
def test_permanent_http_failure_is_not_retried(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    with pytest.raises(UpdateError) as error:
        feed(handler).bounded("https://updates.example/catalog", 100)
    assert len(calls) == 1
    assert "not exposed" not in error.value.message


def test_retry_stops_when_cancelled():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectTimeout("interrupted", request=request)

    with pytest.raises(UpdateError) as error:
        feed(handler).bounded("https://updates.example/catalog", 100, cancelled=lambda: bool(calls))
    assert error.value.code == "UPDATE_CANCELLED"
    assert len(calls) == 1
