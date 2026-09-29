"""Conservative emoji arbitration; delayed/inconsistent views can still race.

Keep upstream emoji IDs and ordering. Prefer silence over an uncertain winner;
there is deliberately no timeout-based promotion of another candidate.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArbiterContext:
    message_id: int
    msg_time: int
    self_id: int


class EmojiLikeArbiter:
    _EMOJI_ID = 289
    _FEEDBACK_EMOJI_ID = 124
    _WAIT_SEC = 1.0
    _SAMPLE_SEC = 0.7
    _FEEDBACK_WAIT_SEC = 0.2
    _API_TIMEOUT_SEC = 3.0
    _TIME_SLICE = 60
    _FETCH_LIMIT = 20
    _SEEN_TTL_SEC = 120.0
    _SEEN_LIMIT = 4096

    def __init__(self, logger: Any = None):
        self._logger = logger or logging.getLogger(__name__)
        self._seen: dict[tuple[int, int], float] = {}

    async def compete(self, bot: Any, ctx: ArbiterContext) -> bool:
        """Require stable membership and exclusive self feedback, even when alone."""
        label = f"[arbiter] mid={ctx.message_id} self={ctx.self_id} time={ctx.msg_time}"

        def finish(reason: str, win: bool = False) -> bool:
            self._logger.info(f"{label} win={win} reason={reason}")
            return win

        if ctx.self_id <= 0 or ctx.msg_time <= 0:
            return finish("invalid_context")
        now = time.monotonic()
        self._seen = {key: expiry for key, expiry in self._seen.items() if expiry > now}
        key = (ctx.self_id, ctx.message_id)
        if key in self._seen:
            return finish("duplicate_event")
        if len(self._seen) >= self._SEEN_LIMIT:
            return finish("local_capacity_reached")
        # Reserve before the first await to suppress concurrent duplicate events.
        self._seen[key] = now + self._SEEN_TTL_SEC

        async def read(emoji: int) -> set[int] | None:
            users = await self._fetch_users(bot, ctx.message_id, emoji)
            self._logger.debug(
                f"{label} emoji={emoji} users={sorted(users) if users is not None else None}"
            )
            return users

        users = await read(self._EMOJI_ID)
        if users is None or users:
            return finish("registration_unavailable_or_already_started")
        feedback = await read(self._FEEDBACK_EMOJI_ID)
        if feedback is None or feedback:
            return finish("existing_or_unknown_feedback")
        if not await self._mark(bot, ctx.message_id, self._EMOJI_ID):
            return finish("registration_failed")

        window_start = time.monotonic()
        await asyncio.sleep(self._SAMPLE_SEC)
        participants = await read(self._EMOJI_ID)
        if not participants or ctx.self_id not in participants:
            return finish("missing_registration")
        # Sample inside the original registration window rather than after it.
        await asyncio.sleep(max(0.0, window_start + self._WAIT_SEC - time.monotonic()))
        if await read(self._EMOJI_ID) != participants:
            return finish("membership_changed_before_election")
        order = self._decide_order(list(participants), ctx.msg_time)
        self._logger.debug(f"{label} order={order}")
        if order[0] != ctx.self_id:
            return finish("not_first_candidate")

        feedback = await read(self._FEEDBACK_EMOJI_ID)
        if feedback is None or feedback:
            return finish("feedback_present_before_claim")
        if not await self._mark(bot, ctx.message_id, self._FEEDBACK_EMOJI_ID):
            return finish("claim_failed")
        for _ in range(2):
            await asyncio.sleep(self._FEEDBACK_WAIT_SEC)
            current_users, current_feedback = await asyncio.gather(
                read(self._EMOJI_ID), read(self._FEEDBACK_EMOJI_ID)
            )
            if current_users != participants:
                return finish("membership_changed_after_claim")
            if current_feedback != {ctx.self_id}:
                return finish("feedback_not_exclusively_self")
        return finish("confirmed", True)

    @staticmethod
    def _action_failed(resp: Any) -> bool:
        return isinstance(resp, dict) and (
            resp.get("status", "ok") != "ok" or resp.get("retcode", 0) != 0
        )

    async def _mark(self, bot: Any, mid: int, emoji: int) -> bool:
        try:
            resp = await asyncio.wait_for(
                bot.set_msg_emoji_like(
                    message_id=mid, emoji_id=emoji, emoji_type="1", set=True
                ), timeout=self._API_TIMEOUT_SEC,
            )
            if self._action_failed(resp):
                raise ValueError("unsuccessful action status")
            return True
        except Exception as exc:
            self._logger.warning(
                f"[arbiter] mid={mid} emoji={emoji} mark_failed={type(exc).__name__}: {exc}"
            )
            return False

    async def _fetch_users(self, bot: Any, mid: int, emoji: int) -> set[int] | None:
        """None means unknown; an empty set means a successful empty response."""
        try:
            resp = await asyncio.wait_for(
                bot.fetch_emoji_like(
                    message_id=mid, emoji_id=str(emoji), emojiId=str(emoji),
                    emojiType="1", count=self._FETCH_LIMIT,
                ), timeout=self._API_TIMEOUT_SEC,
            )
            if not isinstance(resp, dict) or self._action_failed(resp):
                raise ValueError("invalid action response")
            likes = resp.get("emojiLikesList")
            if not isinstance(likes, list) or len(likes) >= self._FETCH_LIMIT:
                raise ValueError("missing or potentially truncated user list")
            users = {int(item["tinyId"]) for item in likes}
            if any(uid <= 0 for uid in users):
                raise ValueError("invalid user ID")
            return users
        except Exception as exc:
            self._logger.warning(
                f"[arbiter] mid={mid} emoji={emoji} query_failed={type(exc).__name__}: {exc}"
            )
            return None

    def _decide_order(self, users: list[int], msg_time: int) -> list[int]:
        participants = sorted(set(users))
        if not participants:
            return []
        base = (msg_time // self._TIME_SLICE) % len(participants)
        return participants[base:] + participants[:base]
