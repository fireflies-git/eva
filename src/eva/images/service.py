from __future__ import annotations

from collections.abc import Sequence

from eva.ai.schemas import ChatMessage
from eva.constants import MAX_IMAGE_UPLOAD_BYTES
from eva.images.client import ImageClient, ImageClientError
from eva.images.detector import ImageDetector
from eva.images.schemas import GeneratedImageAsset, ImageResultBundle


class ImageGenerationService:
    def __init__(
        self,
        *,
        client: ImageClient,
        detector: ImageDetector,
        model_name: str,
        language: str,
        incognito: bool,
    ) -> None:
        self._client = client
        self._detector = detector
        self._model_name = model_name
        self._language = language
        self._incognito = incognito

    async def generate_if_needed(
        self,
        *,
        user_message: str,
        recent_context: Sequence[ChatMessage],
        reply_context: str | None,
    ) -> ImageResultBundle | None:
        decision = await self._detector.should_generate(
            user_message,
            recent_context=recent_context,
            reply_context=reply_context,
        )
        if not decision.should_generate:
            return None

        prompt = user_message.strip()
        if not prompt:
            raise ImageClientError("Image prompt is empty")

        result = await self._client.generate(
            prompt=prompt,
            model=self._model_name,
            language=self._language,
            incognito=self._incognito,
        )
        if not result.images:
            raise ImageClientError("Image generation returned no usable images")

        primary = result.images[0]
        download_url = (primary.download_url or primary.url).strip()
        try:
            raw, content_type, filename = await self._client.download_asset(
                url=download_url,
                filename_hint="eva-image",
                max_bytes=MAX_IMAGE_UPLOAD_BYTES,
            )
        except ImageClientError:
            return result

        asset = GeneratedImageAsset(filename=filename, data=raw, mime_type=content_type)
        return ImageResultBundle(
            id=result.id,
            model=result.model,
            prompt=result.prompt,
            images=result.images,
            assets=[asset],
            answer=result.answer,
        )
