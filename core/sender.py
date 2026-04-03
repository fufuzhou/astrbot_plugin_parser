from __future__ import annotations

import re
from asyncio import Task
from itertools import chain
from pathlib import Path

from astrbot.core.message.components import (
    BaseMessageComponent,
    File,
    Image,
    Node,
    Nodes,
    Plain,
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

    def _build_send_plan(self, result: ParseResult) -> dict:
        light: list = []
        heavy: list = []
        links: list[VideoContent | AudioContent | DynamicContent] = []

        for cont in chain(result.contents, result.repost.contents if result.repost else ()):  # type: ignore[arg-type]
            match cont:
                case ImageContent() | GraphicsContent():
                    light.append(cont)
                case VideoContent() | AudioContent() | DynamicContent():
                    self._cancel_pending_media_download(cont)
                    links.append(cont)
                case FileContent():
                    heavy.append(cont)
                case _:
                    light.append(cont)

        summary_text = self._build_text_summary(result)

        is_single_heavy = len(heavy) == 1 and not light and not links
        render_card = is_single_heavy and self.cfg.single_heavy_render_card

        seg_count = len(light) + len(heavy) + len(links) + (1 if render_card else 0)
        if summary_text:
            seg_count += 1

        force_merge = seg_count >= self.cfg.forward_threshold

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
            await event.send(event.chain_result([Image(str(image_path))]))

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
                segs.append(Image(str(image_path)))

        seen_links: set[str] = set()
        for cont in plan["links"]:
            match cont:
                case VideoContent():
                    try:
                        cover_path = await cont.get_cover_path()
                        if cover_path:
                            segs.append(Image(str(cover_path)))
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
                    segs.append(Image(str(path)))
                case GraphicsContent() as g:
                    segs.append(Image(str(path)))
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

            segs.append(File(name=path.name, file=str(path)))

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

    async def send_parse_result(
        self,
        event: AstrMessageEvent,
        result: ParseResult,
    ):
        plan = self._build_send_plan(result)

        await self._send_preview_card(event, result, plan)

        segs = await self._build_segments(result, plan)
        segs = self._merge_segments_if_needed(event, segs, plan["force_merge"])

        if segs:
            await event.send(event.chain_result(segs))
