from __future__ import annotations

from types import SimpleNamespace

import pytest

from eva.downloads.client import (
    DownloadClientError,
    _enforce_download_limits,
    _install_redirect_policy,
)


class _FakeRedirectHandler:
    def __init__(self) -> None:
        self.calls = 0

    def redirect_request(
        self,
        req: object,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> SimpleNamespace:
        del req, fp, code, msg, headers
        self.calls += 1
        return SimpleNamespace(url=newurl)


class _FakeOpener:
    def __init__(self, handler: _FakeRedirectHandler) -> None:
        self.handlers = [handler]


def test_download_redirect_policy_validates_and_tracks_hops() -> None:
    handler = _FakeRedirectHandler()
    _install_redirect_policy(
        _FakeOpener(handler),
        _FakeRedirectHandler,
        allow_private_outbound=True,
        allowed_hosts=None,
    )

    redirected = handler.redirect_request(
        SimpleNamespace(),
        None,
        302,
        "Found",
        {},
        "https://example.com/next",
    )

    assert redirected.url == "https://example.com/next"
    assert redirected._eva_redirect_count == 1
    assert handler.calls == 1


def test_download_redirect_policy_rejects_private_destination() -> None:
    handler = _FakeRedirectHandler()
    _install_redirect_policy(
        _FakeOpener(handler),
        _FakeRedirectHandler,
        allow_private_outbound=False,
        allowed_hosts=None,
    )

    with pytest.raises(DownloadClientError, match="blocked"):
        handler.redirect_request(
            SimpleNamespace(),
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1/private",
        )
    assert handler.calls == 0


def test_download_redirect_policy_caps_hops() -> None:
    handler = _FakeRedirectHandler()
    _install_redirect_policy(
        _FakeOpener(handler),
        _FakeRedirectHandler,
        allow_private_outbound=True,
        allowed_hosts=None,
    )

    with pytest.raises(DownloadClientError, match="too many"):
        handler.redirect_request(
            SimpleNamespace(_eva_redirect_count=5),
            None,
            302,
            "Found",
            {},
            "https://example.com/next",
        )
    assert handler.calls == 0


def test_download_progress_hook_rejects_oversized_stream() -> None:
    with pytest.raises(DownloadClientError, match="size limit"):
        _enforce_download_limits(
            {"downloaded_bytes": 1_001},
            deadline=float("inf"),
            max_size_bytes=1_000,
        )
