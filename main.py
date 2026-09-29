# main.py

import asyncio
import re

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import At, Image, Json, Plain, Reply
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .core.arbiter import ArbiterContext, EmojiLikeArbiter
from .core.clean import CacheCleaner
from .core.config import PluginConfig
from .core.debounce import Debouncer
from .core.download import Downloader
from .core.exception import ParseException, TipException
from .core.parsers import BaseParser, BilibiliParser
from .core.render import Renderer
from .core.sender import MessageSender
from .core.utils import extract_json_url


class ParserPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config, context=context)

        self.renderer = Renderer(self.cfg)
        self.downloader = Downloader(self.cfg)
        self.debouncer = Debouncer(self.cfg)
        self.arbiter = EmojiLikeArbiter(logger=logger)
        self.sender = MessageSender(self.cfg, self.renderer)
        self.cleaner = CacheCleaner(self.cfg)

        self.parser_map: dict[str, BaseParser] = {}
        self.key_pattern_list: list[tuple[str, re.Pattern[str]]] = []

    def _get_debounce_session_key(self, event: AstrMessageEvent) -> str:
        """Get a stable debounce key per chat session."""
        if isinstance(event, AiocqhttpMessageEvent):
            raw = event.message_obj.raw_message
            if isinstance(raw, dict):
                group_id = raw.get("group_id")
                if group_id is not None:
                    return f"group:{group_id}"
                channel_id = raw.get("channel_id")
                if channel_id is not None:
                    return f"group:{channel_id}"
                guild_id = raw.get("guild_id")
                if guild_id is not None:
                    return f"group:{guild_id}"
                user_id = raw.get("user_id")
                if user_id is not None:
                    return f"private:{user_id}"

        # Fallback for other adapters: try to infer chat scope from origin text.
        origin = str(event.unified_msg_origin)
        lower = origin.lower()

        if m := re.search(r"(?:group|guild|channel|room)[^0-9]*(\d+)", lower):
            return f"group:{m.group(1)}"
        if m := re.search(r"(?:private|friend|dm|user)[^0-9]*(\d+)", lower):
            return f"private:{m.group(1)}"

        # Heuristic fallback: many origins end with sender id in group chats.
        nums = re.findall(r"\d+", origin)
        is_private_chat = None
        checker = getattr(event, "is_private_chat", None)
        if callable(checker):
            try:
                is_private_chat = bool(checker())
            except Exception:
                is_private_chat = None
        if is_private_chat is False and len(nums) >= 2:
            return f"group:{nums[-2]}"
        if is_private_chat is True and nums:
            return f"private:{nums[-1]}"

        return origin

    async def initialize(self):
        """Called when plugin loads/reloads."""
        await asyncio.to_thread(Renderer.load_resources)
        self._register_parser()

    async def terminate(self):
        """Called when plugin unloads."""
        await self.downloader.close()

        unique_parsers = set(self.parser_map.values())
        for parser in unique_parsers:
            await parser.close_session()

        await self.cleaner.stop()

    def _register_parser(self):
        """Register parsers enabled by parser.enable."""
        all_subclass = BaseParser.get_all_subclass()
        enabled_platforms = set(self.cfg.parser.enabled_platforms())

        enabled_classes: list[type[BaseParser]] = []
        enabled_names: list[str] = []

        for cls in all_subclass:
            platform_name = cls.platform.name
            if platform_name not in enabled_platforms:
                logger.debug(f"[parser] 平台未启用或未配置: {platform_name}")
                continue

            enabled_classes.append(cls)
            enabled_names.append(platform_name)

            parser = cls(self.cfg, self.downloader)
            for keyword, _ in cls._key_patterns:
                self.parser_map[keyword] = parser

        logger.debug(f"启用平台: {'、'.join(enabled_names) if enabled_names else '无'}")

        patterns: list[tuple[str, re.Pattern[str]]] = []
        for cls in enabled_classes:
            for kw, pat in cls._key_patterns:
                patterns.append((kw, re.compile(pat) if isinstance(pat, str) else pat))

        patterns.sort(key=lambda x: -len(x[0]))
        self.key_pattern_list = patterns

        logger.debug(f"[parser] 关键字正则对已生成: {[kw for kw, _ in patterns]}")

    def _get_parser_by_type(self, parser_type):
        for parser in self.parser_map.values():
            if isinstance(parser, parser_type):
                return parser
        raise ValueError(f"未找到类型为 {parser_type} 的 parser 实例")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """Unified message entry."""
        umo = event.unified_msg_origin
        debounce_session = self._get_debounce_session_key(event)

        # Ignore self-sent messages to avoid recursive re-parsing.
        if isinstance(event, AiocqhttpMessageEvent):
            raw = event.message_obj.raw_message
            if isinstance(raw, dict):
                sender_id = raw.get("user_id")
                if sender_id is not None and str(sender_id) == str(event.get_self_id()):
                    return

        if self.cfg.whitelist and umo not in self.cfg.whitelist:
            return
        if self.cfg.blacklist and umo in self.cfg.blacklist:
            return

        chain = event.get_messages()
        if not chain:
            return

        seg1 = chain[0]
        text = event.message_str

        # 指定机制：专门@其他bot的消息不解析
        self_id = event.get_self_id()
        mentioned_ids: set[str] = set()
        for seg in chain:
            if isinstance(seg, At):
                mentioned_ids.add(str(seg.qq))
            elif isinstance(seg, Plain):
                mentioned_ids.update(re.findall(r"<@!?([^>\s]+)>", seg.text))
        if (
            self.cfg.require_at_in_group
            and not isinstance(event, AiocqhttpMessageEvent)
            and event.get_message_type() == MessageType.GROUP_MESSAGE
            and self_id not in mentioned_ids
        ):
            return
        if mentioned_ids and self_id not in mentioned_ids:
            return

        # 卡片解析：扫描整条消息链，兼容 @ + JSON 卡片等组合消息。
        for seg in chain:
            if not isinstance(seg, Json):
                continue
            parsed_url = extract_json_url(seg.data)
            logger.debug(f"解析Json组件: {parsed_url}")
            if parsed_url:
                text = parsed_url
                break

        # 引用解析
        reply_seg = next((seg for seg in chain if isinstance(seg, Reply)), None)
        if self.cfg.enable_reply_parse and reply_seg and reply_seg.chain:
            reply_texts = []
            for seg in reply_seg.chain:
                if isinstance(seg, Plain):
                    reply_texts.append(seg.text)
                elif isinstance(seg, Json):
                    reply_texts.append(extract_json_url(seg.data))
            if reply_texts:
                text = "".join(reply_texts)

        if not text:
            return

        keyword: str = ""
        searched: re.Match[str] | None = None
        for kw, pat in self.key_pattern_list:
            if kw not in text:
                continue
            if m := pat.search(text):
                keyword, searched = kw, m
                break

        if searched is None:
            return
        logger.debug(f"匹配结果: {keyword}, {searched}")

        # Remember observed links even when another Bot wins arbitration.
        link = searched.group(0)
        if self.debouncer.hit_link(debounce_session, link):
            logger.warning(f"[链接防抖] 链接 {link} 在防抖时间内，跳过解析")
            return

        if isinstance(event, AiocqhttpMessageEvent) and not event.is_private_chat():
            raw = event.message_obj.raw_message
            if not isinstance(raw, dict):
                logger.warning(f"Unexpected raw_message type: {type(raw)}")
                return

            is_win = await self.arbiter.compete(
                bot=event.bot,
                ctx=ArbiterContext(
                    message_id=int(raw["message_id"]),
                    msg_time=int(raw["time"]),
                    self_id=int(raw["self_id"]),
                ),
            )
            if not is_win:
                logger.debug("Bot 在仲裁中未获胜，跳过解析")
                return
            logger.debug("Bot 在仲裁中获胜，开始解析")

        try:
            parse_res = await self.parser_map[keyword].parse(keyword, searched)
        except TipException as exc:
            msg = exc.message or "可能含有成人/敏感内容，已按配置不予解析"
            await event.send(event.chain_result([Plain(msg)]))
            return
        except ParseException as exc:
            logger.warning(f"解析失败: {exc.message}")
            return

        resource_id = parse_res.get_resource_id()
        if self.debouncer.hit_resource(debounce_session, resource_id):
            logger.warning(f"[资源防抖] 资源 {resource_id} 在防抖时间内，跳过发送")
            return

        await self.sender.send_parse_result(event, parse_res)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("开启解析")
    async def open_parser(self, event: AstrMessageEvent):
        """Enable parsing for current session."""
        umo = event.unified_msg_origin
        self.cfg.remove_blacklist(umo)
        yield event.plain_result("当前会话的解析已开启")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("关闭解析")
    async def close_parser(self, event: AstrMessageEvent):
        """Disable parsing for current session."""
        umo = event.unified_msg_origin
        self.cfg.add_blacklist(umo)
        yield event.plain_result("当前会话的解析已关闭")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("登录B站", alias={"blogin", "登录b站"})
    async def login_bilibili(self, event: AstrMessageEvent):
        """Login bilibili with QR code."""
        parser: BilibiliParser = self._get_parser_by_type(BilibiliParser)  # type: ignore
        qrcode = await parser.login.login_with_qrcode()
        yield event.chain_result([Image.fromBytes(qrcode)])
        async for msg in parser.login.check_qr_state():
            yield event.plain_result(msg)
