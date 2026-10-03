from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence

from eva.ai.schemas import VisionImage
from eva.constants import (
    MAX_VISION_CACHE_BYTES,
    MAX_VISION_GROUPS_PER_CHANNEL,
    MAX_VISION_IMAGE_BYTES,
    MAX_VISION_IMAGES_PER_MESSAGE,
    MAX_VISION_REQUEST_BYTES,
)


class VisionImageStore:
    """Bounded, process-local storage for recently received image attachments."""

    def __init__(
        self,
        *,
        max_groups_per_channel: int = MAX_VISION_GROUPS_PER_CHANNEL,
        max_bytes: int = MAX_VISION_CACHE_BYTES,
    ) -> None:
        if max_groups_per_channel <= 0:
            raise ValueError("max_groups_per_channel must be positive")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")

        self._max_groups_per_channel = max_groups_per_channel
        self._max_bytes = max_bytes
        self._groups: OrderedDict[tuple[int, int], tuple[VisionImage, ...]] = OrderedDict()
        self._total_bytes = 0

    def put(
        self,
        channel_id: int,
        message_id: int,
        images: Sequence[VisionImage],
    ) -> None:
        normalized = self._normalize_images(images)
        if not normalized:
            return

        key = (channel_id, message_id)
        self._remove(key)
        self._groups[key] = normalized
        self._total_bytes += self._group_size(normalized)

        self._evict_channel_groups(channel_id)
        self._evict_global_bytes()

    def get_for_message(self, channel_id: int, message_id: int) -> tuple[VisionImage, ...]:
        return self._groups.get((channel_id, message_id), ())

    def get_latest(self, channel_id: int) -> tuple[VisionImage, ...]:
        for key in reversed(self._groups):
            if key[0] == channel_id:
                return self._groups[key]
        return ()

    def clear(self, channel_id: int) -> None:
        for key in tuple(self._groups):
            if key[0] == channel_id:
                self._remove(key)

    def _normalize_images(self, images: Sequence[VisionImage]) -> tuple[VisionImage, ...]:
        normalized: list[VisionImage] = []
        total_bytes = 0
        for image in images:
            image_size = len(image.data)
            if not image.data or image_size > MAX_VISION_IMAGE_BYTES:
                continue
            if len(normalized) >= MAX_VISION_IMAGES_PER_MESSAGE:
                break
            if total_bytes + image_size > MAX_VISION_REQUEST_BYTES:
                continue
            normalized.append(image)
            total_bytes += image_size
        return tuple(normalized)

    def _evict_channel_groups(self, channel_id: int) -> None:
        while self._count_channel_groups(channel_id) > self._max_groups_per_channel:
            oldest_key = next(key for key in self._groups if key[0] == channel_id)
            self._remove(oldest_key)

    def _evict_global_bytes(self) -> None:
        while self._total_bytes > self._max_bytes and self._groups:
            oldest_key = next(iter(self._groups))
            self._remove(oldest_key)

    def _count_channel_groups(self, channel_id: int) -> int:
        return sum(1 for stored_channel_id, _ in self._groups if stored_channel_id == channel_id)

    def _remove(self, key: tuple[int, int]) -> None:
        images = self._groups.pop(key, None)
        if images is not None:
            self._total_bytes -= self._group_size(images)

    @staticmethod
    def _group_size(images: Sequence[VisionImage]) -> int:
        return sum(len(image.data) for image in images)
