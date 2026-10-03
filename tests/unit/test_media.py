import asyncio
from types import SimpleNamespace

from eva.discord.media import (
    MAX_ATTACHMENTS,
    MAX_IMAGE_BYTES,
    AttachmentBudget,
    AttachmentMarker,
    attachment_to_part,
)


def test_unsupported_attachment_is_metadata_only() -> None:
    attachment = SimpleNamespace(filename="archive.zip", content_type="application/zip", size=10)
    budget = AttachmentBudget()

    result = asyncio.run(attachment_to_part(attachment, budget=budget))

    assert isinstance(result, AttachmentMarker)
    assert "unsupported type" in result.text()
    assert budget.count == 0


def test_image_size_limit_is_enforced_before_download() -> None:
    attachment = SimpleNamespace(
        filename="huge.png",
        content_type="image/png",
        size=MAX_IMAGE_BYTES + 1,
        url="https://cdn.example/huge.png",
    )

    result = asyncio.run(attachment_to_part(attachment, budget=AttachmentBudget()))

    assert isinstance(result, AttachmentMarker)
    assert "size limit" in result.text()


def test_attachment_budget_caps_count() -> None:
    budget = AttachmentBudget()
    for _ in range(MAX_ATTACHMENTS):
        assert budget.reserve(1) is None

    assert budget.reserve(1) == "attachment limit"
