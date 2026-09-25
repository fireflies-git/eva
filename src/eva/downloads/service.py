from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from eva.constants import DEFAULT_DM_DOWNLOAD_LIMIT_BYTES
from eva.downloads.client import DownloadClientError, MediaDownloader
from eva.downloads.schemas import DownloadedMediaAsset
from eva.security.urls import URLPolicyError, validate_url_for_request


class DownloadService:
    def __init__(
        self,
        *,
        client: MediaDownloader,
        dm_filesize_limit_bytes: int = DEFAULT_DM_DOWNLOAD_LIMIT_BYTES,
        allow_private_outbound: bool = False,
    ) -> None:
        self._client = client
        self._dm_filesize_limit_bytes = dm_filesize_limit_bytes
        self._allow_private_outbound = allow_private_outbound

    async def download_media(
        self,
        *,
        url: str,
        guild_filesize_limit: int | None,
    ) -> DownloadedMediaAsset:
        try:
            validated_url = await validate_url_for_request(
                url,
                allow_private=self._allow_private_outbound,
            )
        except URLPolicyError as exc:
            raise DownloadClientError(
                f"Please provide a valid URL (public URL required): {exc}"
            ) from exc

        max_size = guild_filesize_limit or self._dm_filesize_limit_bytes
        max_size_mb = max_size / (1024 * 1024)

        with TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            downloaded_file = await self._client.download(
                url=validated_url.value,
                max_filesize_mb=max_size_mb,
                temp_dir=temp_dir,
            )

            if not downloaded_file.path.exists():
                raise DownloadClientError(
                    f"Failed to download the video - file must be under {max_size_mb:.1f}MB"
                )

            filesize = downloaded_file.path.stat().st_size
            if filesize > max_size:
                raise DownloadClientError(
                    "Video file is too large to upload "
                    f"({filesize / 1024 / 1024:.1f}MB > {max_size_mb:.1f}MB)"
                )

            return DownloadedMediaAsset(
                filename=_build_attachment_filename(downloaded_file.path),
                data=downloaded_file.path.read_bytes(),
            )
def _build_attachment_filename(path: Path) -> str:
    filename = path.name.strip()
    return filename or "downloaded-media.mp4"
