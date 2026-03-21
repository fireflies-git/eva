from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import aiohttp

from eva.images.schemas import GeneratedImage, ImageResultBundle


class ImageClientError(RuntimeError):
    pass


_TRANSIENT_HTTP_STATUS_CODES = frozenset({502, 503, 504})


class ImageClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
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

        try:
            async with self._session.get(url) as response:
                if response.status != 200:
                    text = await response.text()
                    raise ImageClientError(
                        self._format_http_error(
                            prefix="Image download error",
                            status=response.status,
                            body=text,
                        )
                    )

                content_type = response.headers.get("Content-Type")
                raw = await response.read()
        except TimeoutError as exc:
            raise ImageClientError("Image download request timed out") from exc
        except aiohttp.ClientError as exc:
            raise ImageClientError(f"Image download network error: {exc}") from exc

        if len(raw) > max_bytes:
            raise ImageClientError(
                f"Image download exceeds max size ({len(raw)} bytes > {max_bytes} bytes)"
            )

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
            async with self._session.post(url, headers=headers, json=payload) as response:
                text = await response.text()
                if response.status != 200:
                    raise ImageClientError(
                        self._format_http_error(
                            prefix="Image API error",
                            status=response.status,
                            body=text,
                        )
                    )
                try:
                    data = await response.json()
                except Exception as exc:
                    excerpt = self._compact_error_body(text)
                    raise ImageClientError(f"Invalid image JSON response: {excerpt}") from exc
                if not isinstance(data, dict):
                    raise ImageClientError("Invalid image API response type")
                return data
        except TimeoutError as exc:
            raise ImageClientError("Image API request timed out") from exc
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
