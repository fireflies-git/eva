from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Protocol

import discord

from eva.account_updates import (
    AccountUpdatePlan,
    PendingAccountUpdateStore,
    format_account_update_applied,
    format_account_update_cancelled,
    format_account_update_confirmation,
)
from eva.ai import (
    AIClientError,
    ReplyGenerationService,
    ResponseSplitService,
    SummarizationService,
)
from eva.ai.orchestrator import ReplyOutput
from eva.ai.sanitize import strip_response_watermark
from eva.config import Settings
from eva.constants import (
    FOLLOWUP_TYPING_AVERAGE_WORD_LENGTH,
    FOLLOWUP_TYPING_MIN_SECONDS,
    FOLLOWUP_TYPING_WPM_MAX,
    FOLLOWUP_TYPING_WPM_MIN,
    WARNING_MARK,
    X_MARK,
)
from eva.discord.account_updates import AccountUpdateApplyError, apply_account_update
from eva.discord.clear_commands import handle_clear_command
from eva.discord.command_outcome import CommandOutcome
from eva.discord.commands import handle_whitelist_command, is_admin_user
from eva.discord.context import fetch_channel_context, fetch_reply_context
from eva.discord.delivery import (
    DeliveryResult,
    close_application_group,
    deliver_owner_response,
    deliver_reply_response,
    safe_edit,
    safe_reply,
    safe_reply_or_edit,
    safe_send,
    wait_before_followup,
)
from eva.discord.download_commands import handle_download_command
from eva.discord.formatting import build_loading_text, build_plain_response_chunks
from eva.discord.friend_requests import FriendRequestHandler
from eva.discord.memory_commands import format_memories_for_prompt, handle_memory_command
from eva.discord.reminder_commands import handle_reminder_command
from eva.discord.social_commands import handle_social_command
from eva.discord.summarize_commands import handle_summarize_command, is_summarize_command
from eva.discord.terminal_commands import handle_terminal_command
from eva.discord.triggers import TriggerDecision as TriggerDecision
from eva.discord.triggers import (
    decide_standalone_trigger,
    is_tracked_reply_trigger,
    parse_trigger,
)
from eva.discord.user_metadata import build_requester_context
from eva.discord.watermark_commands import handle_watermark_command
from eva.downloads import DownloadService
from eva.state import (
    ChannelHistoryStore,
    RateLimiter,
    ReminderStore,
    TrackedMessageStore,
    UserMemoryStore,
    WhitelistStore,
)
from eva.terminal import TerminalService

logger = logging.getLogger(__name__)
interaction_logger = logging.getLogger("eva.interaction")

__all__ = ["SelfbotMessageHandler", "TriggerDecision", "parse_trigger"]


class AccountUpdatePlanner(Protocol):
    async def plan_update(self, user_message: str) -> AccountUpdatePlan | None: ...


class SelfbotMessageHandler:
    def __init__(
        self,
        *,
        settings: Settings,
        reply_generation_service: ReplyGenerationService,
        history_store: ChannelHistoryStore,
        tracked_messages: TrackedMessageStore,
        whitelist: WhitelistStore,
        user_memory: UserMemoryStore,
        reminder_store: ReminderStore,
        rate_limiter: RateLimiter,
        summarization_service: SummarizationService | None,
        terminal_service: TerminalService | None,
        download_service: DownloadService | None,
        response_split_service: ResponseSplitService | None = None,
        account_update_planner: AccountUpdatePlanner | None = None,
        pending_account_updates: PendingAccountUpdateStore | None = None,
        friend_request_handler: FriendRequestHandler | None = None,
    ) -> None:
        self._settings = settings
        self._reply_generation_service = reply_generation_service
        self._history_store = history_store
        self._tracked_messages = tracked_messages
        self._whitelist = whitelist
        self._user_memory = user_memory
        self._reminder_store = reminder_store
        self._rate_limiter = rate_limiter
        self._summarization_service = summarization_service
        self._terminal_service = terminal_service
        self._download_service = download_service
        self._response_split_service = response_split_service
        self._account_update_planner = account_update_planner
        self._pending_account_updates = pending_account_updates
        self._friend_request_handler = friend_request_handler
        self._pending_recovery_notified = False

    async def handle_ready(self, client: discord.Client) -> None:
        if self._pending_recovery_notified:
            return
        self._pending_recovery_notified = True
        if self._friend_request_handler is None:
            return
        await self._friend_request_handler.notify_pending_requests(client=client)

    async def on_message(self, client: discord.Client, message: discord.Message) -> None:
        user = client.user
        if user is None:
            return

        is_owner = message.author.id == user.id
        is_standalone = self._is_standalone_mode()

        original_content = message.content
        channel_id = getattr(message.channel, "id", None)
        if channel_id is None:
            return

        if not is_standalone:
            is_admin = is_admin_user(user_id=message.author.id, is_owner=is_owner)
            if is_admin and getattr(message.channel, "guild", object()) is None:
                if await self._handle_friend_request_confirmation(
                    client=client,
                    message=message,
                    is_owner=is_owner,
                    original_content=original_content,
                ):
                    return
            if not is_admin and not self._whitelist.contains(message.author.id):
                return

        if (
            self._friend_request_handler is not None
            and self._friend_request_handler.is_requester_pending(
                requester_id=message.author.id
            )
        ):
            interaction_logger.info(
                "ignored pending friend-request user_id=%s channel_id=%s",
                message.author.id,
                channel_id,
            )
            return

        if await self._handle_account_update_confirmation(
            client=client,
            message=message,
            is_owner=is_owner,
            is_standalone=is_standalone,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return

        if await self._dispatch_commands(
            client=client,
            message=message,
            is_owner=is_owner,
            is_standalone=is_standalone,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return

        # In standalone mode the bot account *is* the owner — own messages stop here
        # unless they were a command (handled above).
        if is_standalone and is_owner:
            return

        is_reply_trigger = is_tracked_reply_trigger(
            message=message,
            tracked_messages=self._tracked_messages,
        )

        decision = self._decide_trigger(
            message=message,
            content=original_content,
            is_reply_trigger=is_reply_trigger,
            mention_user_id=user.id,
            bot_username=getattr(user, "name", None),
        )

        if not decision.should_process:
            return

        if not self._consume_rate_limit(user_id=message.author.id, is_owner=is_owner):
            interaction_logger.info(
                "rate_limited channel_id=%s message_id=%s author_id=%s",
                channel_id,
                message.id,
                message.author.id,
            )
            return

        if await self._handle_account_update_request(
            message=message,
            user_query=decision.user_query,
            is_owner=is_owner,
            is_standalone=is_standalone,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return

        reply_context = await fetch_reply_context(message)
        requester_context = self._build_requester_context_with_memory(message)
        interaction_logger.info(
            (
                "incoming channel_id=%s message_id=%s author_id=%s "
                "reply_trigger=%s query=%r requester=%r"
            ),
            channel_id,
            message.id,
            message.author.id,
            decision.is_reply_trigger,
            decision.user_query,
            requester_context,
        )
        interaction_logger.info(
            "AI | %s: %s",
            getattr(message.author, "display_name", "unknown"),
            original_content,
        )

        await self._process_reply_flow(
            client=client,
            message=message,
            original_content=original_content,
            channel_id=channel_id,
            user_query=decision.user_query,
            reply_context=reply_context,
            allow_image_generation=not decision.is_reply_trigger,
            requester_context=requester_context,
            is_owner=is_owner,
            is_standalone=is_standalone,
        )

    async def on_relationship_add(
        self,
        client: discord.Client,
        relationship: discord.Relationship,
    ) -> None:
        if self._friend_request_handler is None:
            return
        try:
            await self._friend_request_handler.handle_incoming_request(
                client=client,
                relationship=relationship,
            )
        except Exception:
            logger.exception(
                "Friend request handling failed for user %s",
                getattr(relationship, "user", None),
            )

    async def _handle_friend_request_confirmation(
        self,
        *,
        client: discord.Client,
        message: discord.Message,
        is_owner: bool,
        original_content: str,
    ) -> bool:
        if self._friend_request_handler is None:
            return False
        confirmation = await self._friend_request_handler.handle_confirmation(
            client=client,
            admin_user_id=message.author.id,
            content=original_content,
        )
        if confirmation is None:
            return False
        await self._deliver_command_response(
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            content=confirmation,
        )
        return True

    async def _dispatch_commands(
        self,
        *,
        client: discord.Client,
        message: discord.Message,
        is_owner: bool,
        is_standalone: bool,
        original_content: str,
        channel_id: int,
    ) -> bool:
        clear_outcome = await handle_clear_command(
            content=original_content,
            user_id=message.author.id,
            is_owner=is_owner,
            trigger_prefix=self._settings.trigger_prefix,
        )
        if await self._handle_command_outcome(
            outcome=clear_outcome,
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return True

        if not is_standalone and await handle_whitelist_command(
            message=message,
            content=original_content,
            is_owner=is_owner,
            trigger_prefix=self._settings.trigger_prefix,
            whitelist=self._whitelist,
            reply_or_edit=safe_reply_or_edit,
        ):
            return True

        terminal_outcome = await handle_terminal_command(
            content=original_content,
            user_id=message.author.id,
            is_owner=is_owner,
            trigger_prefix=self._settings.trigger_prefix,
            terminal_service=self._terminal_service,
        )
        if await self._handle_command_outcome(
            outcome=terminal_outcome,
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return True

        social_outcome = await handle_social_command(
            content=original_content,
            user_id=message.author.id,
            is_owner=is_owner,
            trigger_prefix=self._settings.trigger_prefix,
            client=client,
            friend_request_handler=self._friend_request_handler,
            channel=message.channel,
        )
        if await self._handle_command_outcome(
            outcome=social_outcome,
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return True

        watermark_outcome = await handle_watermark_command(
            content=original_content,
            user_id=message.author.id,
            is_owner=is_owner,
            trigger_prefix=self._settings.trigger_prefix,
            controller=self._reply_generation_service,
        )
        if await self._handle_command_outcome(
            outcome=watermark_outcome,
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return True

        download_outcome = await handle_download_command(
            message=message,
            content=original_content,
            is_owner=is_owner,
            trigger_prefix=self._settings.trigger_prefix,
            whitelist=self._whitelist,
            download_service=self._download_service,
        )
        if await self._handle_command_outcome(
            outcome=download_outcome,
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return True

        reminder_outcome = await handle_reminder_command(
            message=message,
            content=original_content,
            trigger_prefix=self._settings.trigger_prefix,
            reminder_store=self._reminder_store,
        )
        if await self._handle_command_outcome(
            outcome=reminder_outcome,
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return True

        memory_outcome = await handle_memory_command(
            content=original_content,
            user_id=message.author.id,
            trigger_prefix=self._settings.trigger_prefix,
            memory_store=self._user_memory,
        )
        if await self._handle_command_outcome(
            outcome=memory_outcome,
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            channel_id=channel_id,
        ):
            return True

        return await self._dispatch_summarize_command(
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            channel_id=channel_id,
        )

    async def _dispatch_summarize_command(
        self,
        *,
        message: discord.Message,
        is_owner: bool,
        original_content: str,
        channel_id: int,
    ) -> bool:
        if not is_summarize_command(
            content=original_content,
            trigger_prefix=self._settings.trigger_prefix,
        ):
            return False

        # Don't charge quota when summarization isn't even configured.
        if self._summarization_service is not None and not self._consume_rate_limit(
            user_id=message.author.id, is_owner=is_owner
        ):
            interaction_logger.info(
                "rate_limited summarize channel_id=%s author_id=%s",
                channel_id,
                message.author.id,
            )
            return True

        outcome = await handle_summarize_command(
            message=message,
            content=original_content,
            trigger_prefix=self._settings.trigger_prefix,
            summarization_service=self._summarization_service,
            requester_context=self._build_requester_context_with_memory(message),
        )
        return await self._handle_command_outcome(
            outcome=outcome,
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            channel_id=channel_id,
        )

    async def _handle_command_outcome(
        self,
        *,
        outcome: CommandOutcome,
        message: discord.Message,
        is_owner: bool,
        original_content: str,
        channel_id: int,
    ) -> bool:
        if not outcome.handled:
            return False
        if outcome.should_clear:
            self._clear_channel_memory(channel_id)
        await self._deliver_command_response(
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            content=outcome.content,
            attachments=outcome.attachments,
        )
        if outcome.close_application:
            await close_application_group(message.channel)
        return True

    def _decide_trigger(
        self,
        *,
        message: discord.Message,
        content: str,
        is_reply_trigger: bool,
        mention_user_id: int,
        bot_username: str | None = None,
    ) -> TriggerDecision:
        if self._is_standalone_mode():
            return decide_standalone_trigger(
                message=message,
                content=content,
                trigger_prefix=self._settings.trigger_prefix,
                is_reply_trigger=is_reply_trigger,
                mention_user_id=mention_user_id,
                bot_username=bot_username,
            )
        return parse_trigger(
            content=content,
            trigger_prefix=self._settings.trigger_prefix,
            is_reply_trigger=is_reply_trigger,
            mention_user_id=mention_user_id,
        )

    def _is_standalone_mode(self) -> bool:
        return getattr(self._settings, "account_mode", "assistant") == "standalone"

    def _consume_rate_limit(self, *, user_id: int, is_owner: bool) -> bool:
        if is_owner or is_admin_user(user_id=user_id, is_owner=is_owner):
            return True
        return self._rate_limiter.check_and_consume(user_id)

    def _build_requester_context_with_memory(self, message: discord.Message) -> str:
        base = build_requester_context(message)
        memories = format_memories_for_prompt(self._user_memory.get(message.author.id))
        if not memories:
            return base
        return f"{base}\n\n{memories}"

    async def _handle_account_update_confirmation(
        self,
        *,
        client: discord.Client,
        message: discord.Message,
        is_owner: bool,
        is_standalone: bool,
        original_content: str,
        channel_id: int,
    ) -> bool:
        decision = _parse_account_update_confirmation(original_content)
        if decision is None or self._pending_account_updates is None:
            return False

        pending = self._pending_account_updates.get(
            user_id=message.author.id,
            channel_id=channel_id,
        )
        if pending is None:
            return False

        if not self._can_manage_account_updates(
            user_id=message.author.id,
            is_owner=is_owner,
            is_standalone=is_standalone,
        ):
            await self._deliver_command_response(
                message=message,
                is_owner=is_owner,
                original_content=original_content,
                content=f"{X_MARK} You don't have permission to change Eva's account.",
            )
            return True

        if not decision:
            self._pending_account_updates.pop(user_id=message.author.id, channel_id=channel_id)
            await self._deliver_command_response(
                message=message,
                is_owner=is_owner,
                original_content=original_content,
                content=format_account_update_cancelled(),
            )
            return True

        # Pop before applying: a duplicate "y" arriving mid-apply must not
        # find the entry and apply it twice. Re-set on failure to allow retry.
        self._pending_account_updates.pop(user_id=message.author.id, channel_id=channel_id)
        try:
            await apply_account_update(client=client, draft=pending.draft)
        except AccountUpdateApplyError as exc:
            self._pending_account_updates.set(
                user_id=message.author.id,
                channel_id=channel_id,
                draft=pending.draft,
            )
            await self._deliver_command_response(
                message=message,
                is_owner=is_owner,
                original_content=original_content,
                content=f"{X_MARK} Account update failed: {exc}",
            )
            return True

        await self._deliver_command_response(
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            content=format_account_update_applied(pending.draft),
        )
        return True

    async def _handle_account_update_request(
        self,
        *,
        message: discord.Message,
        user_query: str,
        is_owner: bool,
        is_standalone: bool,
        original_content: str,
        channel_id: int,
    ) -> bool:
        if self._account_update_planner is None or self._pending_account_updates is None:
            return False

        try:
            plan = await self._account_update_planner.plan_update(user_query)
        except Exception:
            # Planner failures must not swallow the message; fail open to a reply.
            logger.exception("Account update planning failed")
            return False
        if plan is None:
            return False

        if not self._can_manage_account_updates(
            user_id=message.author.id,
            is_owner=is_owner,
            is_standalone=is_standalone,
        ):
            await self._deliver_command_response(
                message=message,
                is_owner=is_owner,
                original_content=original_content,
                content=f"{X_MARK} You don't have permission to change Eva's account.",
            )
            return True

        if plan.error is not None:
            await self._deliver_command_response(
                message=message,
                is_owner=is_owner,
                original_content=original_content,
                content=f"{X_MARK} Account update rejected: {plan.error}",
            )
            return True

        if plan.draft is None:
            return False

        self._pending_account_updates.set(
            user_id=message.author.id,
            channel_id=channel_id,
            draft=plan.draft,
        )
        await self._deliver_command_response(
            message=message,
            is_owner=is_owner,
            original_content=original_content,
            content=format_account_update_confirmation(plan.draft),
        )
        return True

    def _can_manage_account_updates(
        self,
        *,
        user_id: int,
        is_owner: bool,
        is_standalone: bool,
    ) -> bool:
        if is_standalone:
            return is_admin_user(user_id=user_id, is_owner=is_owner)
        return is_owner

    async def _process_reply_flow(
        self,
        *,
        client: discord.Client,
        message: discord.Message,
        original_content: str,
        channel_id: int,
        user_query: str,
        reply_context: str | None,
        allow_image_generation: bool,
        requester_context: str,
        is_owner: bool,
        is_standalone: bool,
    ) -> None:
        bot_user_id = client.user.id if client.user else None
        response_context = await fetch_channel_context(
            message.channel,
            limit=self._settings.response_context_messages,
            exclude_message_id=message.id,
            bot_user_id=bot_user_id,
            account_mode="standalone" if is_standalone else "assistant",
            is_tracked_message=self._tracked_messages.contains,
        )
        history_messages = self._history_store.get(channel_id)

        use_owner_edit = is_owner and not is_standalone
        edit_started = time.monotonic() if use_owner_edit else None
        if use_owner_edit:
            await safe_edit(message, build_loading_text(original_content))

        try:
            async with message.channel.typing():
                ai_reply = await self._reply_generation_service.generate_reply(
                    channel=message.channel,
                    client=client,
                    context_messages=response_context,
                    history_messages=history_messages,
                    user_message=user_query,
                    reply_context=reply_context,
                    allow_image_generation=allow_image_generation,
                    requester_context=requester_context,
                    user_id=message.author.id,
                    channel_id=channel_id,
                )
        except AIClientError as exc:
            logger.exception("AI response generation failed")
            ai_reply = ReplyOutput(content=f"{WARNING_MARK} AI error: {exc}", attachments=[])

        if edit_started is not None:
            elapsed = time.monotonic() - edit_started
            min_loading_seconds = getattr(self._settings, "min_loading_seconds", 1.0)
            if elapsed < min_loading_seconds:
                await asyncio.sleep(min_loading_seconds - elapsed)

        delivery_result = await self._deliver_ai_reply(
            message=message,
            original_content=original_content,
            ai_reply=ai_reply,
            is_owner=is_owner,
            is_standalone=is_standalone,
        )
        for message_id in delivery_result.tracked_message_ids:
            self._tracked_messages.add(message_id)

        if delivery_result.primary_delivered:
            stored_user_message = _build_stored_user_message(
                user_query,
                reply_context,
                requester_context,
            )
            # History feeds back into the model prompt; store the reply without
            # the watermark so the model doesn't learn to regurgitate it.
            self._history_store.append_exchange(
                channel_id,
                stored_user_message,
                strip_response_watermark(ai_reply.content),
            )

        interaction_logger.info(
            "outgoing channel_id=%s message_id=%s delivered=%s tracked=%s response=%r",
            channel_id,
            message.id,
            delivery_result.primary_delivered,
            len(delivery_result.tracked_message_ids),
            ai_reply.content,
        )

    async def _deliver_ai_reply(
        self,
        *,
        message: discord.Message,
        original_content: str,
        ai_reply: ReplyOutput,
        is_owner: bool,
        is_standalone: bool,
    ) -> DeliveryResult:
        suppress_embeds = not ai_reply.allow_embeds
        if is_owner and not is_standalone:
            return await deliver_owner_response(
                message=message,
                original_content=original_content,
                reply_content=ai_reply.content,
                reply_attachments=ai_reply.attachments,
                suppress_embeds=suppress_embeds,
                followup_delay_seconds=self._calculate_followup_delay_seconds,
            )
        if is_standalone:
            return await self._deliver_standalone_reply_response(
                message=message,
                reply=ai_reply,
            )
        return await deliver_reply_response(
            message=message,
            reply_content=ai_reply.content,
            reply_attachments=ai_reply.attachments,
            suppress_embeds=suppress_embeds,
            followup_delay_seconds=self._calculate_followup_delay_seconds,
        )

    async def _deliver_standalone_reply_response(
        self,
        *,
        message: discord.Message,
        reply: ReplyOutput,
    ) -> DeliveryResult:
        chunks = await self._build_plain_response_chunks(reply.content)
        first = await safe_reply(
            message,
            chunks[0],
            attachments=reply.attachments,
            suppress_embeds=not reply.allow_embeds,
        )
        if first is None:
            return DeliveryResult(primary_delivered=False)

        continuation_ids, had_continuation_failures = await self._send_followup_messages(
            message.channel,
            chunks[1:],
        )
        return DeliveryResult(
            primary_delivered=True,
            tracked_message_ids=[first.id, *continuation_ids],
            had_continuation_failures=had_continuation_failures,
        )

    async def _deliver_command_response(
        self,
        *,
        message: discord.Message,
        is_owner: bool,
        original_content: str,
        content: str,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> None:
        if is_owner and not self._is_standalone_mode():
            await deliver_owner_response(
                message=message,
                original_content=original_content,
                reply_content=content,
                reply_attachments=attachments,
            )
            return

        await deliver_reply_response(
            message=message,
            reply_content=content,
            reply_attachments=attachments,
        )

    def _clear_channel_memory(self, channel_id: int) -> None:
        self._history_store.clear(channel_id)

    async def _build_plain_response_chunks(self, ai_reply: str) -> list[str]:
        local_chunks = build_plain_response_chunks(ai_reply)
        if not self._is_standalone_mode() or self._response_split_service is None:
            return local_chunks

        # Keep the optional planner for standalone accounts, but enforce the local
        # sentence boundary policy after it returns. The model must not decide how
        # many sentences Discord receives in one message.
        planned_chunks = await self._response_split_service.split_reply(
            reply_content=ai_reply,
            first_limit=2000,
            continuation_limit=2000,
        )
        if planned_chunks is None:
            return local_chunks
        return build_plain_response_chunks("\n\n".join(planned_chunks))

    async def _send_followup_messages(
        self,
        channel: discord.abc.Messageable,
        chunks: list[str],
    ) -> tuple[list[int], bool]:
        sent_ids: list[int] = []
        had_failures = False

        for continuation in chunks:
            if self._is_standalone_mode():
                await wait_before_followup(
                    channel,
                    content=continuation,
                    delay_seconds=self._calculate_followup_delay_seconds,
                )
            sent = await safe_send(channel, continuation)
            if sent is None:
                had_failures = True
                continue
            # IDs are tracked by the caller from the DeliveryResult; adding them
            # here too would just double the store's disk writes.
            sent_ids.append(sent.id)

        return sent_ids, had_failures

    def _calculate_followup_delay_seconds(self, content: str) -> float:
        character_count = len(content.strip())
        if character_count == 0:
            return 0.0

        words_per_minute = random.uniform(
            FOLLOWUP_TYPING_WPM_MIN,
            FOLLOWUP_TYPING_WPM_MAX,
        )
        estimated_word_count = character_count / FOLLOWUP_TYPING_AVERAGE_WORD_LENGTH
        typing_seconds = (estimated_word_count / words_per_minute) * 60.0
        return max(typing_seconds, FOLLOWUP_TYPING_MIN_SECONDS)


def _build_stored_user_message(
    user_query: str,
    reply_context: str | None,
    requester_context: str,
) -> str:
    sections = [f"[Current requester]\n{requester_context}"]
    if reply_context:
        sections.append(f'[Replying to message: "{reply_context}"]')
    sections.append(user_query)
    return "\n\n".join(sections)


def _parse_account_update_confirmation(content: str) -> bool | None:
    normalized = content.strip().lower()
    if normalized == "y":
        return True
    if normalized == "n":
        return False
    return None
