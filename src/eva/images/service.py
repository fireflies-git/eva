from __future__ import annotations

from collections.abc import Sequence

from eva.ai.schemas import ChatMessage
from eva.constants import MAX_IMAGE_UPLOAD_BYTES, MAX_IMAGE_URLS
from eva.images.client import ImageClient, ImageClientError
from eva.images.detector import ImageDetector
from eva.images.schemas import GeneratedImageAsset, ImageResultBundle
from eva.prompts import build_image_generation_prompt


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

        prompt = build_image_generation_prompt(
            user_message=user_message,
            reply_context=reply_context,
        )
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

        assets: list[GeneratedImageAsset] = []
        for index, image in enumerate(result.images[:MAX_IMAGE_URLS], start=1):
            download_url = (image.download_url or image.url).strip()
            try:
                raw, content_type, filename = await self._client.download_asset(
                    url=download_url,
                    filename_hint=f"eva-image-{index}",
                    max_bytes=MAX_IMAGE_UPLOAD_BYTES,
                )
            except ImageClientError:
                continue

            assets.append(
                GeneratedImageAsset(
                    filename=filename,
                    data=raw,
                    mime_type=content_type,
                )
            )

        if not assets:
            return result

        return ImageResultBundle(
            id=result.id,
            model=result.model,
            prompt=result.prompt,
            image_generation=result.image_generation,
            images=result.images,
            assets=assets,
            answer=result.answer,
        )
