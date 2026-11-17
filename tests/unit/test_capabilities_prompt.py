from eva.constants import (
    TOOL_FETCH_WEB_PAGE,
    TOOL_INSPECT_ATTACHED_IMAGES,
    TOOL_LOOKUP_DOCUMENTATION,
    TOOL_RUN_TERMINAL_COMMAND,
    TOOL_WEB_SEARCH,
)
from eva.prompts.capabilities import build_capabilities_section

ALL_TOOLS = frozenset(
    {
        TOOL_RUN_TERMINAL_COMMAND,
        TOOL_FETCH_WEB_PAGE,
        TOOL_LOOKUP_DOCUMENTATION,
        TOOL_WEB_SEARCH,
        TOOL_INSPECT_ATTACHED_IMAGES,
    }
)


def test_each_tool_appears_only_when_available() -> None:
    for tool_name in ALL_TOOLS:
        section = build_capabilities_section(available_tools={tool_name})
        assert f"`{tool_name}`" in section
        for other in ALL_TOOLS - {tool_name}:
            assert other not in section


def test_no_tools_branch_admits_no_live_access() -> None:
    section = build_capabilities_section(available_tools=frozenset())

    assert "can't check live information" in section
    assert "instead of guessing" in section
    for tool_name in ALL_TOOLS:
        assert tool_name not in section


def test_unauthorized_tools_are_absent_but_vision_can_remain() -> None:
    section = build_capabilities_section(available_tools={TOOL_INSPECT_ATTACHED_IMAGES})

    assert TOOL_INSPECT_ATTACHED_IMAGES in section
    assert TOOL_RUN_TERMINAL_COMMAND not in section
    assert TOOL_WEB_SEARCH not in section
    assert "Error:" not in section


def test_all_tools_section_has_failure_and_budget_guidance() -> None:
    section = build_capabilities_section(available_tools=ALL_TOOLS)

    assert '"Tool error:"' in section
    assert "never invent the result" in section
    assert "identical arguments" in section
    assert "3 rounds" in section
    assert "up to 5 calls per round" in section
    assert "wrapped in <>" in section
    assert "never print tool-call syntax" in section


def test_terminal_guidance_mentions_read_only_allowlist() -> None:
    section = build_capabilities_section(available_tools={TOOL_RUN_TERMINAL_COMMAND})

    assert "read-only" in section
    assert "allowlisted" in section


def test_account_update_flow_is_not_advertised() -> None:
    for tools in (frozenset(), ALL_TOOLS):
        assert "confirmation flow" not in build_capabilities_section(available_tools=tools)
