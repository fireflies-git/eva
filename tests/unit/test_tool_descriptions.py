from __future__ import annotations

from typing import Any, cast

from eva.tools.context7_service import Context7Service
from eva.tools.playwright_service import PlaywrightService
from eva.tools.vision_service import VisionInspectionTool


def _description(service: Any) -> str:
    function = cast(dict[str, Any], service.build_autonomous_tool_definition()["function"])
    return cast(str, function["description"])


def test_lookup_documentation_description_has_use_and_avoid_guidance() -> None:
    description = _description(Context7Service(api_key="key"))

    assert "instead of guessing" in description
    assert "Do not use for general web questions" in description


def test_fetch_web_page_description_has_use_and_avoid_guidance() -> None:
    description = _description(PlaywrightService())

    assert "ONE public URL" in description
    assert "Do not use it to search" in description
    assert "untrusted" in description


def test_inspect_images_description_has_use_and_avoid_guidance() -> None:
    tool = VisionInspectionTool(
        client=cast(Any, object()),
        model_name="m",
        user_request="",
        images=[],
        image_context_available=False,
    )
    description = _description(tool)

    assert "whenever the current message has images" in description
    assert "Never describe image details" in description
    assert "No image attachment context is currently available." in description
