from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Protocol, cast

from eva.downloads.schemas import DownloadedMediaFile
from eva.security.urls import (
    URLPolicyError,
    validate_url,
    validate_url_for_request,
    validate_url_for_request_sync,
)


class DownloadClientError(RuntimeError):
    pass


class MediaDownloader(Protocol):
    async def download(
        self,
        *,
        url: str,
        max_filesize_mb: float,
        temp_dir: Path,
    ) -> DownloadedMediaFile: ...


class YtDLPDownloadClient:
    def __init__(
        self,
        *,
        allow_private_outbound: bool = False,
        allowed_hosts: frozenset[str] | None = None,
        max_runtime_seconds: float = 300.0,
    ) -> None:
        self._allow_private_outbound = allow_private_outbound
        self._allowed_hosts = allowed_hosts
        self._max_runtime_seconds = max(1.0, max_runtime_seconds)

    async def download(
        self,
        *,
        url: str,
        max_filesize_mb: float,
        temp_dir: Path,
    ) -> DownloadedMediaFile:
        try:
            validated_url = await validate_url_for_request(
                url,
                allow_private=self._allow_private_outbound,
                allowed_hosts=self._allowed_hosts,
            )
        except URLPolicyError as exc:
            raise DownloadClientError(
                f"Download URL blocked by outbound URL policy: {exc}"
            ) from exc

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._download_sync,
            validated_url.value,
            max_filesize_mb,
            temp_dir,
        )

    def _download_sync(
        self,
        url: str,
        max_filesize_mb: float,
        temp_dir: Path,
    ) -> DownloadedMediaFile:
        try:
            # DownloadService performs the asynchronous DNS check.  Keep a
            # synchronous defense here for callers that use this client
            # directly, such as maintenance scripts.
            validated_url = validate_url(
                url,
                allow_private=self._allow_private_outbound,
                allowed_hosts=self._allowed_hosts,
            )
        except URLPolicyError as exc:
            raise DownloadClientError(
                f"Download URL blocked by outbound URL policy: {exc}"
            ) from exc

        try:
            import yt_dlp
        except ImportError as exc:
            raise DownloadClientError("yt-dlp is not installed.") from exc

        policy = self
        deadline = time.monotonic() + self._max_runtime_seconds

        def enforce_deadline(_status: dict[str, Any]) -> None:
            if time.monotonic() >= deadline:
                raise DownloadClientError("Media download exceeded its runtime limit")

        class PolicyYoutubeDL(yt_dlp.YoutubeDL):  # type: ignore[misc, valid-type]
            """Re-validate every manifest, redirect, and segment request."""

            def urlopen(self, req: Any) -> Any:
                if time.monotonic() >= deadline:
                    raise DownloadClientError("Media download exceeded its runtime limit")
                request_url = req if isinstance(req, str) else req.url
                try:
                    validate_url_for_request_sync(
                        request_url,
                        allow_private=policy._allow_private_outbound,
                        allowed_hosts=policy._allowed_hosts,
                    )
                except URLPolicyError as exc:
                    raise DownloadClientError(
                        "Download subrequest blocked by outbound URL policy"
                    ) from exc
                return super().urlopen(req)

        ydl_opts = {
            "format": (
                f"best[filesize<={max_filesize_mb}M]/"
                f"bestvideo[filesize<={max_filesize_mb}M]+bestaudio[filesize<={max_filesize_mb}M]/"
                "best"
            ),
            "outtmpl": str(temp_dir / "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "playlistend": 1,
            "allowed_protocols": (
                "http",
                "https",
                "m3u8_native",
                "http_dash_segments",
            ),
            "hls_prefer_native": True,
            "enable_file_urls": False,
            "max_filesize": int(max_filesize_mb * 1024 * 1024),
            "restrictfilenames": True,
            "retries": 1,
            "fragment_retries": 1,
            "socket_timeout": 30,
            "match_filter": _reject_long_media,
            "progress_hooks": [enforce_deadline],
            "merge_output_format": "mp4",
            "postprocessors": [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }
            ],
        }

        try:
            with PolicyYoutubeDL(cast(Any, ydl_opts)) as ydl:
                info = cast(dict[str, Any], ydl.extract_info(validated_url.value, download=True))
                path = _resolve_download_path(ydl=ydl, info=info, temp_dir=temp_dir)
        except Exception as exc:
            raise DownloadClientError("An error occurred while downloading media") from exc

        return DownloadedMediaFile(path=path)


def _resolve_download_path(*, ydl: Any, info: dict[str, Any], temp_dir: Path) -> Path:
    workdir = temp_dir.resolve()
    prepared = Path(str(ydl.prepare_filename(info))).resolve()
    if not _is_relative_to(prepared, workdir):
        raise DownloadClientError("Downloaded media path escaped its temporary directory")
    candidates = [prepared]

    if prepared.suffix.lower() != ".mp4":
        candidates.append(prepared.with_suffix(".mp4"))

    for candidate in candidates:
        if candidate.exists():
            resolved = candidate.resolve()
            if not _is_relative_to(resolved, workdir):
                raise DownloadClientError("Downloaded media path escaped its temporary directory")
            return resolved

    files = sorted(path for path in temp_dir.iterdir() if path.is_file())
    if len(files) == 1:
        resolved = files[0].resolve()
        if not _is_relative_to(resolved, workdir):
            raise DownloadClientError("Downloaded media path escaped its temporary directory")
        return resolved

    return candidates[-1]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _reject_long_media(info: dict[str, Any], *, max_seconds: int = 900) -> str | None:
    """Keep media parsing bounded even when a provider omits file sizes."""
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > max_seconds:
        return f"media duration exceeds {max_seconds} seconds"
    return None
