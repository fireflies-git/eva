from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from eva.images.schemas import GeneratedImage, ImageResultBundle
from eva.security.urls import URLPolicyError, validate_url_for_request


class ImageClientError(RuntimeError):
    pass


_TRANSIENT_HTTP_STATUS_CODES = frozenset({502, 503, 504})
_DOWNLOAD_CHUNK_BYTES = 65_536
_ERROR_BODY_MAX_BYTES = 8_192
_MAX_REDIRECTS = 3
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


def _parse_content_length(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


async def _read_capped(response: aiohttp.ClientResponse, *, max_bytes: int) -> bytes:
    """Read the body in chunks, aborting as soon as it exceeds ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK_BYTES):
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise ImageClientError(
                f"Image download exceeds max size ({total} bytes > {max_bytes} bytes)"
            )
    return b"".join(chunks)


class ImageClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        allow_private_outbound: bool = False,
        allowed_hosts: frozenset[str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._allow_private_outbound = allow_private_outbound
        self._allowed_hosts = allowed_hosts
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        language: str,
        incognito: bool,
    ) -> ImageResultBundle:
        data = await self._request(
            prompt=prompt, model=model, language=language, incognito=incognito
        )
        return ImageResultBundle(
            id=self._string_or_empty(data.get("id")),
            model=self._string_or_empty(data.get("model")),
            prompt=self._string_or_empty(data.get("prompt")),
            image_generation=self._bool_or_false(data.get("image_generation")),
            answer=self._string_or_empty(data.get("answer")),
            images=self._build_images(data),
        )

    async def download_asset(
        self,
        *,
        url: str,
        filename_hint: str = "eva-image",
        max_bytes: int,
    ) -> tuple[bytes, str | None, str]:
        if self._session is None:
            raise ImageClientError("Image client is not started")

        current_url = url
        try:
            for redirect_count in range(_MAX_REDIRECTS + 1):
                validated = await validate_url_for_request(
                    current_url,
                    allow_private=self._allow_private_outbound,
                    allowed_hosts=self._allowed_hosts,
                )
                response_context = _session_get_no_redirects(
                    self._session,
                    validated.value,
                )
                async with response_context as response:
                    if response.status in _REDIRECT_STATUS_CODES:
                        location = response.headers.get("Location")
                        if not location:
                            raise ImageClientError("Image download redirect has no Location header")
                        if redirect_count >= _MAX_REDIRECTS:
                            raise ImageClientError("Image download followed too many redirects")
                        current_url = urljoin(validated.value, location)
                        continue

                    if response.status != 200:
                        text = await _read_error_body(response)
                        raise ImageClientError(
                            self._format_http_error(
                                prefix="Image download error",
                                status=response.status,
                                body=text,
                            )
                        )

                    content_type = response.headers.get("Content-Type")
                    content_length = _parse_content_length(
                        response.headers.get("Content-Length")
                    )
                    if content_length is not None and content_length > max_bytes:
                        raise ImageClientError(
                            "Image download exceeds max size "
                            f"({content_length} bytes > {max_bytes} bytes)"
                        )
                    raw = await _read_capped(response, max_bytes=max_bytes)
                    break
            else:  # pragma: no cover - loop always returns or raises
                raise ImageClientError("Image download failed")
        except TimeoutError as exc:
            raise ImageClientError("Image download request timed out") from exc
        except URLPolicyError as exc:
            raise ImageClientError(
                f"Image download URL blocked by outbound URL policy: {exc}"
            ) from exc
        except aiohttp.ClientError as exc:
            raise ImageClientError(f"Image download network error: {exc}") from exc

        filename = self._pick_filename(
            url=url,
            content_type=content_type,
            filename_hint=filename_hint,
        )
        return raw, content_type, filename

    async def _request(
        self,
        *,
        prompt: str,
        model: str,
        language: str,
        incognito: bool,
    ) -> dict[str, Any]:
        if self._session is None:
            raise ImageClientError("Image client is not started")

        url = f"{self._base_url}/images"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "prompt": prompt,
            "model": model,
            "language": language,
            "incognito": incognito,
        }

        try:
            await validate_url_for_request(
                self._base_url,
                allow_private=self._allow_private_outbound,
                allowed_hosts=self._allowed_hosts,
            )
            async with self._session.post(
                url,
                headers=headers,
                json=payload,
                allow_redirects=False,
            ) as response:
                body = await _read_capped(response, max_bytes=_ERROR_BODY_MAX_BYTES)
                text = body.decode(response.charset or "utf-8", errors="replace")
                if response.status != 200:
                    raise ImageClientError(
                        self._format_http_error(
                            prefix="Image API error",
                            status=response.status,
                            body=text,
                        )
                    )
                try:
                    import json

                    data = json.loads(text)
                except Exception as exc:
                    excerpt = self._compact_error_body(text)
                    raise ImageClientError(f"Invalid image JSON response: {excerpt}") from exc
                if not isinstance(data, dict):
                    raise ImageClientError("Invalid image API response type")
                return data
        except TimeoutError as exc:
            raise ImageClientError("Image API request timed out") from exc
        except URLPolicyError as exc:
            raise ImageClientError(f"Image API URL blocked by outbound URL policy: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise ImageClientError(f"Image API network error: {exc}") from exc

    def _build_images(self, data: dict[str, Any]) -> list[GeneratedImage]:
        raw = data.get("images")
        if not isinstance(raw, list):
            return []

        images: list[GeneratedImage] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = self._string_or_none(item.get("url"))
            if not url:
                continue
            image = GeneratedImage(
                url=url,
                thumbnail_url=self._string_or_none(item.get("thumbnail_url")),
                download_url=self._string_or_none(item.get("download_url")),
                mime_type=self._string_or_none(item.get("mime_type")),
                source=self._string_or_none(item.get("source")),
                generation_model=self._string_or_none(item.get("generation_model")),
                prompt=self._string_or_none(item.get("prompt")),
            )
            if self._looks_like_generated_image(image):
                images.append(image)

        if raw and not images:
            raise ImageClientError("Image API returned non-generated image results")
        return images

    def _string_or_none(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _string_or_empty(self, value: Any) -> str:
        return self._string_or_none(value) or ""

    def _bool_or_false(self, value: Any) -> bool:
        return value is True

    def _pick_filename(
        self,
        *,
        url: str,
        content_type: str | None,
        filename_hint: str,
    ) -> str:
        ext = self._extension_for_content_type(content_type) or self._extension_from_url(url)
        safe_hint = re.sub(r"[^a-zA-Z0-9_-]+", "-", filename_hint).strip("-") or "eva-image"
        if ext and not ext.startswith("."):
            ext = f".{ext}"
        return f"{safe_hint}{ext or '.png'}"

    def _extension_for_content_type(self, content_type: str | None) -> str | None:
        if not content_type:
            return None
        lowered = content_type.split(";")[0].strip().lower()
        mapping = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        return mapping.get(lowered)

    def _extension_from_url(self, url: str) -> str | None:
        try:
            path = urlparse(url).path
        except Exception:
            return None
        if not path:
            return None
        last = path.rsplit("/", 1)[-1]
        if "." not in last:
            return None
        ext = last.rsplit(".", 1)[-1].lower()
        if ext in {"png", "jpg", "jpeg", "webp", "gif"}:
            return "jpg" if ext == "jpeg" else ext
        return None

    def _looks_like_generated_image(self, image: GeneratedImage) -> bool:
        if image.generation_model:
            return True
        if image.source and image.source.endswith("-router"):
            return True

        try:
            parsed = urlparse(image.url)
        except Exception:
            return False

        host = parsed.netloc.lower()
        path = parsed.path.lower()
        return "user-gen-media-assets" in host or "seedream_images" in path

    def _format_http_error(self, *, prefix: str, status: int, body: str) -> str:
        if status in _TRANSIENT_HTTP_STATUS_CODES:
            return f"{prefix} HTTP {status}: upstream service temporarily unavailable"
        excerpt = self._compact_error_body(body)
        return f"{prefix} HTTP {status}: {excerpt}"

    def _compact_error_body(self, body: str) -> str:
        compact = " ".join(body.split())
        if not compact:
            return "empty response body"
        return compact[:300]


def _session_get_no_redirects(session: Any, url: str) -> Any:
    """Call ``session.get`` with redirects disabled.

    The fallback keeps lightweight test doubles and older aiohttp-compatible
    adapters working; the real aiohttp client always accepts the keyword.
    """
    try:
        return session.get(url, allow_redirects=False)
    except TypeError as exc:
        if "allow_redirects" not in str(exc):
            raise
        return session.get(url)


async def _read_error_body(response: Any) -> str:
    """Read a bounded response excerpt for an HTTP error."""
    content = getattr(response, "content", None)
    if content is not None and hasattr(content, "iter_chunked"):
        chunks: list[bytes] = []
        total = 0
        async for chunk in content.iter_chunked(_DOWNLOAD_CHUNK_BYTES):
            remaining = _ERROR_BODY_MAX_BYTES - total
            if remaining <= 0:
                break
            chunks.append(chunk[:remaining])
            total += min(len(chunk), remaining)
            if total >= _ERROR_BODY_MAX_BYTES:
                break
        charset = getattr(response, "charset", None) or "utf-8"
        return b"".join(chunks).decode(charset, errors="replace")
    text = await response.text()
    return text[:_ERROR_BODY_MAX_BYTES]
