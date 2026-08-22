import asyncio

from eva.discord.watermark_commands import handle_watermark_command


class FakeWatermarkController:
    def __init__(self, *, enabled: bool = True) -> None:
        self.watermark_enabled = enabled
        self.set_calls: list[bool] = []

    def set_watermark_enabled(self, enabled: bool) -> None:
        self.watermark_enabled = enabled
        self.set_calls.append(enabled)


def test_watermark_on_enables_watermark_for_owner() -> None:
    controller = FakeWatermarkController(enabled=False)

    result = asyncio.run(
        handle_watermark_command(
            content="eva watermark on",
            user_id=1,
            is_owner=True,
            trigger_prefix="eva ",
            controller=controller,
        )
    )

    assert result.handled is True
    assert "Watermark enabled" in result.content
    assert controller.watermark_enabled is True
    assert controller.set_calls == [True]


def test_watermark_off_disables_watermark_for_admin() -> None:
    controller = FakeWatermarkController()

    result = asyncio.run(
        handle_watermark_command(
            content="eva watermark disable",
            user_id=213766338005434370,
            is_owner=False,
            trigger_prefix="eva ",
            controller=controller,
        )
    )

    assert result.handled is True
    assert "Watermark disabled" in result.content
    assert controller.watermark_enabled is False
    assert controller.set_calls == [False]


def test_watermark_status_reports_current_state() -> None:
    controller = FakeWatermarkController(enabled=False)

    result = asyncio.run(
        handle_watermark_command(
            content="eva watermark status",
            user_id=1,
            is_owner=True,
            trigger_prefix="eva ",
            controller=controller,
        )
    )

    assert result.handled is True
    assert "Watermark is disabled" in result.content
    assert controller.set_calls == []


def test_watermark_command_rejects_non_admin() -> None:
    controller = FakeWatermarkController()

    result = asyncio.run(
        handle_watermark_command(
            content="eva watermark off",
            user_id=999,
            is_owner=False,
            trigger_prefix="eva ",
            controller=controller,
        )
    )

    assert result.handled is True
    assert "permission" in result.content
    assert controller.set_calls == []


def test_watermark_command_ignores_other_messages() -> None:
    result = asyncio.run(
        handle_watermark_command(
            content="eva hello",
            user_id=1,
            is_owner=True,
            trigger_prefix="eva ",
            controller=FakeWatermarkController(),
        )
    )

    assert result.handled is False


def test_watermark_command_rejects_unknown_action() -> None:
    result = asyncio.run(
        handle_watermark_command(
            content="eva watermark maybe",
            user_id=1,
            is_owner=True,
            trigger_prefix="eva ",
            controller=FakeWatermarkController(),
        )
    )

    assert result.handled is True
    assert "Usage" in result.content
