from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol, cast

from eva.downloads.schemas import DownloadedMediaFile
from eva.security.urls import URLPolicyError, validate_url


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
    def __init__(self, *, allow_private_outbound: bool = False) -> None:
        self._allow_private_outbound = allow_private_outbound

    async def download(
        self,
        *,
        url: str,
        max_filesize_mb: float,
        temp_dir: Path,
    ) -> DownloadedMediaFile:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._download_sync,
            url,
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
            validated_url = validate_url(url, allow_private=self._allow_private_outbound)
        except URLPolicyError as exc:
            raise DownloadClientError(
                f"Download URL blocked by outbound URL policy: {exc}"
            ) from exc

        try:
            import yt_dlp
        except ImportError as exc:
            raise DownloadClientError("yt-dlp is not installed.") from exc

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
            "max_filesize": int(max_filesize_mb * 1024 * 1024),
            "restrictfilenames": True,
            "retries": 1,
            "fragment_retries": 1,
            "socket_timeout": 30,
            "merge_output_format": "mp4",
            "postprocessors": [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }
            ],
        }

        try:
            with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
                info = cast(dict[str, Any], ydl.extract_info(validated_url.value, download=True))
                path = _resolve_download_path(ydl=ydl, info=info, temp_dir=temp_dir)
        except Exception as exc:
            raise DownloadClientError(f"An error occurred while downloading: {exc}") from exc

        return DownloadedMediaFile(path=path)


def _resolve_download_path(*, ydl: Any, info: dict[str, Any], temp_dir: Path) -> Path:
    prepared = Path(str(ydl.prepare_filename(info)))
    candidates = [prepared]

    if prepared.suffix.lower() != ".mp4":
        candidates.append(prepared.with_suffix(".mp4"))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    files = sorted(path for path in temp_dir.iterdir() if path.is_file())
    if len(files) == 1:
        return files[0]

    return candidates[-1]
