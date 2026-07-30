from __future__ import annotations

import re
from asyncio import Task
from itertools import chain
from pathlib import Path

from astrbot.api import logger
from astrbot.core.message.components import (
    BaseMessageComponent,
    File,
    Image,
    Node,
    Nodes,
    Plain,
    Record,
    Video,
)
from astrbot.core.platform.astr_message_event import AstrMessageEvent

from .config import PluginConfig
from .data import (
    AudioContent,
    DynamicContent,
    FileContent,
    GraphicsContent,
    ImageContent,
    ParseResult,
    SendGroup,
    TextContent,
    VideoContent,
)
from .exception import (
    DownloadException,
    DownloadLimitException,
    SizeLimitException,
    ZeroSizeException,
)
from .render import Renderer


class MessageSender:
    def __init__(self, config: PluginConfig, renderer: Renderer):
        self.cfg = config
        self.renderer = renderer

    def _to_file_uri(self, path: Path) -> str:
        if not path.is_absolute():
            path = path.resolve()
        posix_path = path.as_posix()
        if posix_path.startswith("/"):
            return f"file:////{posix_path.lstrip('/')}"
        return path.as_uri()

    @staticmethod
    def _image_from_path(path: Path) -> Image:
        return Image.fromFileSystem(str(path))

    @staticmethod
    def _video_from_path(path: Path) -> Video:
        return Video.fromFileSystem(str(path))

    @staticmethod
    def _record_from_path(path: Path) -> Record:
        return Record.fromFileSystem(str(path))

    @staticmethod
    def _iter_contents(result: ParseResult):
        return chain(result.contents, result.repost.contents if result.repost else ())

    def _build_send_plan(
        self,
        result: ParseResult,
        contents: list | tuple | None = None,
        *,
        force_merge_override: bool | None = None,
        render_card_override: bool | None = None,
    ) -> dict:
        """
        根据解析结果生成发送计划（plan）

        plan 只做“策略决策”，不做任何 IO 或发送动作。
        后续发送流程严格按 plan 执行，避免逻辑分散。
        """
        light: list = []
        heavy: list = []
        links: list[VideoContent | AudioContent | DynamicContent] = []

        # 合并主内容 + 转发内容，统一参与发送策略计算
        iterable = contents if contents is not None else self._iter_contents(result)
        for cont in iterable:
            match cont:
                case ImageContent() | GraphicsContent() | TextContent():
                    light.append(cont)
                case VideoContent() | AudioContent() | DynamicContent():
                    if self._has_ready_media_path(cont):
                        heavy.append(cont)
                    else:
                        self._cancel_pending_media_download(cont)
                        links.append(cont)
                case FileContent():
                    heavy.append(cont)
                case _:
                    light.append(cont)

        summary_text = self._build_text_summary(result)

        is_single_heavy = len(heavy) == 1 and not light and not links
        render_card = is_single_heavy and self.cfg.single_heavy_render_card
        
        if render_card_override is not None:
            render_card = render_card_override

        seg_count = len(light) + len(heavy) + len(links) + (1 if render_card else 0)
        if summary_text:
            seg_count += 1

        force_merge = seg_count >= self.cfg.forward_threshold
        if force_merge_override is not None:
            force_merge = force_merge_override

        return {
            "light": light,
            "heavy": heavy,
            "links": links,
            "summary_text": summary_text,
            "render_card": render_card,
            "preview_card": render_card and not force_merge,
            "force_merge": force_merge,
        }

    @staticmethod
    def _has_ready_media_path(
        cont: VideoContent | AudioContent | DynamicContent,
    ) -> bool:
        if isinstance(cont.path_task, Path):
            return True
        return cont.path_task.done() and not cont.path_task.cancelled()

    @staticmethod
    def _cancel_pending_media_download(
        cont: VideoContent | AudioContent | DynamicContent,
    ) -> None:
        if isinstance(cont.path_task, Task) and not cont.path_task.done():
            cont.path_task.cancel()

    @staticmethod
    def _extract_media_url(path_task: Path | Task[Path]) -> str | None:
        if not isinstance(path_task, Task):
            return None

        name = path_task.get_name().strip()
        if "|" in name:
            name = name.split("|", 1)[1].strip()

        m = re.search(r"https?://\S+", name)
        if not m:
            return None
        return m.group(0).rstrip("),]")

    def _build_text_summary(self, result: ParseResult) -> str | None:
        weibo_text = result.extra.get("weibo_thread_text")
        if isinstance(weibo_text, str) and weibo_text.strip():
            return weibo_text

        blocks: list[str] = []
        current: ParseResult | None = result
        while current:
            blocks.append(self._format_result_block(current))
            current = current.repost

        text = "\n======================\n".join(blocks).strip()
        return text or None

    def _format_result_block(self, result: ParseResult) -> str:
        lines: list[str] = [result.platform.display_name]

        if result.author:
            lines.append(f"@{result.author.name}")
        if timestamp := result.formatted_datetime("%Y-%m-%dT%H:%M:%S"):
            lines.append(f"时间: {timestamp}")
        if result.url:
            lines.append(f"链接: {result.url}")
        if result.title:
            lines.append(f"标题: {result.title}")
        if result.text:
            lines.append(result.text.strip())
        if result.extra_info:
            lines.append(result.extra_info)

        return "\n".join(lines)

    async def _send_preview_card(
        self,
        event: AstrMessageEvent,
        result: ParseResult,
        plan: dict,
    ):
        if not plan["preview_card"]:
            return

        if image_path := await self.renderer.render_card(result):
            await event.send(event.chain_result([self._image_from_path(image_path)]))

    async def _build_segments(
        self,
        result: ParseResult,
        plan: dict,
    ) -> list[BaseMessageComponent]:
        segs: list[BaseMessageComponent] = []

        if isinstance(plan.get("summary_text"), str) and plan["summary_text"].strip():
            segs.append(Plain(plan["summary_text"]))

        if plan["render_card"] and plan["force_merge"]:
            if image_path := await self.renderer.render_card(result):
                segs.append(self._image_from_path(image_path))

        seen_links: set[str] = set()
        for cont in plan["links"]:
            match cont:
                case VideoContent():
                    try:
                        cover_path = await cont.get_cover_path()
                        if cover_path:
                            segs.append(self._image_from_path(cover_path))
                    except (DownloadException, DownloadLimitException, ZeroSizeException):
                        pass

                    url = self._extract_media_url(cont.path_task)
                    if url and url not in seen_links:
                        segs.append(Plain(f"视频链接: {url}"))
                        seen_links.add(url)

                case AudioContent():
                    url = self._extract_media_url(cont.path_task)
                    if url and url not in seen_links:
                        segs.append(Plain(f"音频链接: {url}"))
                        seen_links.add(url)

                case DynamicContent():
                    url = self._extract_media_url(cont.path_task)
                    if url and url not in seen_links:
                        segs.append(Plain(f"动图链接: {url}"))
                        seen_links.add(url)

        for cont in plan["light"]:
            if isinstance(cont, TextContent):
                if cont.text:
                    segs.append(Plain(cont.text))
                continue

            try:
                path: Path = await cont.get_path()
            except (DownloadLimitException, ZeroSizeException):
                continue
            except DownloadException:
                if self.cfg.show_download_fail_tip:
                    segs.append(Plain("此项媒体下载失败"))
                continue

            match cont:
                case ImageContent():
                    segs.append(self._image_from_path(path))
                case GraphicsContent() as g:
                    segs.append(self._image_from_path(path))
                    # GraphicsContent 允许携带补充文本
                    if g.text:
                        segs.append(Plain(g.text))
                    if g.alt:
                        segs.append(Plain(g.alt))

        for cont in plan["heavy"]:
            if not isinstance(cont, FileContent):
                continue

            try:
                path = await cont.get_path()
            except SizeLimitException:
                segs.append(Plain("此项媒体超过大小限制"))
                continue
            except DownloadException:
                if self.cfg.show_download_fail_tip:
                    segs.append(Plain("此项媒体下载失败"))
                continue

            match cont:
                case VideoContent() | DynamicContent():
                    segs.append(self._video_from_path(path))
                case AudioContent():
                    segs.append(
                        File(name=path.name, file=self._to_file_uri(path))
                        if self.cfg.audio_to_file
                        else self._record_from_path(path)
                    )
                case FileContent():
                    segs.append(File(name=path.name, file=self._to_file_uri(path)))

        return segs

    def _merge_segments_if_needed(
        self,
        event: AstrMessageEvent,
        segs: list[BaseMessageComponent],
        force_merge: bool,
    ) -> list[BaseMessageComponent]:
        if not force_merge or not segs:
            return segs

        nodes = Nodes([])
        self_id = event.get_self_id()
        for seg in segs:
            nodes.nodes.append(Node(uin=self_id, name="解析器", content=[seg]))

        return [nodes]

    @staticmethod
    def _build_text_fallback(result: ParseResult) -> list[BaseMessageComponent]:
        lines: list[str] = []
        if result.header:
            lines.append(result.header)
        if result.text:
            lines.append(result.text)
        elif result.extra.get("info"):
            lines.append(str(result.extra["info"]))

        text = "\n".join(line for line in lines if line).strip()
        return [Plain(text)] if text else []

    def _resolve_groups(self, result: ParseResult) -> list[SendGroup]:
        if result.send_groups:
            return result.send_groups
        return [SendGroup(contents=list(MessageSender._iter_contents(result)))]

    async def _send_group(
        self,
        event: AstrMessageEvent,
        result: ParseResult,
        group: SendGroup,
    ) -> bool:
        plan = self._build_send_plan(
            result,
            group.contents,
            force_merge_override=group.force_merge,
            render_card_override=group.render_card,
        )

        await self._send_preview_card(event, result, plan)

        segs = await self._build_segments(result, plan)
        segs = self._merge_segments_if_needed(event, segs, plan["force_merge"])

        if not segs:
            return False

        try:
            await event.send(event.chain_result(segs))
            return True
        except Exception as e:
            seg_meta = self._collect_seg_meta(segs)
            logger.error(f"发送解析结果失败： error={e}, segments={seg_meta}")
            return False

    @staticmethod
    def _collect_seg_meta(segs: list[BaseMessageComponent]) -> list[dict[str, str]]:
        """提取消息段元信息，用于失败日志定位。"""
        meta: list[dict[str, str]] = []

        for seg in segs:
            item = {"type": seg.__class__.__name__}
            for attr in ("file", "path", "url"):
                value = getattr(seg, attr, None)
                if value:
                    item["media"] = str(value)
                    break
            meta.append(item)

        return meta

    async def send_parse_result(
        self,
        event: AstrMessageEvent,
        result: ParseResult,
    ):
        """
        发送解析结果的统一入口

        执行顺序固定：
        1. 构建发送计划
        2. 发送预览卡片（如有）
        3. 构建消息段
        4. 必要时合并转发
        5. 最终发送
        """
        groups = self._resolve_groups(result)

        sent = False
        for group in groups:
            sent = await self._send_group(event, result, group) or sent

        if not sent:
            segs = self._build_text_fallback(result)
            if not segs:
                logger.warning("发送结果为空，不执行发送")
                return

            try:
                await event.send(event.chain_result(segs))
            except Exception as e:
                seg_meta = self._collect_seg_meta(segs)
                logger.error(f"发送解析结果失败： error={e}, segments={seg_meta}")
            return
