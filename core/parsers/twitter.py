import base64
import json
import re
from itertools import chain
from math import pi
from typing import Any, ClassVar
from urllib.parse import parse_qs, urljoin, urlparse

from aiohttp import ClientError
from bs4 import BeautifulSoup, Tag

from ..config import PluginConfig
from ..cookie import CookieJar
from ..data import ParseResult, Platform
from ..download import Downloader
from ..exception import ParseException, TipException
from .base import BaseParser, handle


class TwitterParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name="twitter", display_name="推特")

    def __init__(self, config: PluginConfig, downloader: Downloader):
        super().__init__(config, downloader)
        self.mycfg = config.parser.twitter
        self.block_sensitive = bool(self.mycfg.raw_data().get("block_sensitive", False))
        self.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://xdown.app",
                "Referer": "https://xdown.app/",
            }
        )
        self.xdown_url = "https://xdown.app/api/ajaxSearch"
        self.syndication_url = "https://cdn.syndication.twimg.com/tweet-result"
        self.cookiejar = CookieJar(config, self.mycfg, domain="xdown.app")
        if self.cookiejar.cookies_str:
            self.headers["cookie"] = self.cookiejar.cookies_str

    async def _req_xdown_api(self, url: str) -> dict[str, Any]:
        async with self.session.post(
            url=self.xdown_url,
            data={"q": url, "lang": "zh-cn"},
            headers=self.headers,
        ) as resp:
            if resp.status >= 400:
                raise ClientError(f"xdown API {resp.status} {resp.reason}")
            return await resp.json()

    async def _req_syndication_api(self, status_id: str) -> dict[str, Any] | None:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://x.com/",
        }
        params_list = [
            {
                "id": status_id,
                "token": self._build_syndication_token(status_id),
                "lang": "en",
            },
            {"id": status_id, "lang": "en"},
        ]

        last_payload: dict[str, Any] | None = None
        for params in params_list:
            try:
                async with self.session.get(
                    self.syndication_url,
                    params=params,
                    headers=headers,
                ) as resp:
                    if resp.status >= 400:
                        continue
                    payload = await resp.json(content_type=None)
                    if isinstance(payload, dict):
                        last_payload = payload
                        if payload:
                            return payload
            except Exception:
                continue
        return last_payload

    @staticmethod
    def _build_syndication_token(status_id: str) -> str:
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        x = (int(status_id) / 1e15) * pi
        int_part = int(x)
        frac = x - int_part

        if int_part == 0:
            int_str = "0"
        else:
            parts: list[str] = []
            while int_part > 0:
                int_part, r = divmod(int_part, 36)
                parts.append(digits[r])
            int_str = "".join(reversed(parts))

        frac_chars: list[str] = []
        for _ in range(20):
            if frac <= 0:
                break
            frac *= 36
            d = int(frac)
            frac_chars.append(digits[d])
            frac -= d

        token = int_str + ("." + "".join(frac_chars) if frac_chars else "")
        return re.sub(r"(0+|[.])", "", token)

    def _html_has_sensitive_hint(self, html_content: str) -> bool:
        return bool(
            re.search(
                (
                    r"(?i)(sensitive content|potentially sensitive|adult content|"
                    r"nsfw|age[- ]?restricted|18\+|explicit content|"
                    r"敏感内容|成人内容|限制级)"
                ),
                html_content,
            )
        )

    def _payload_has_sensitive_flag(self, payload: Any) -> bool:
        if isinstance(payload, dict):
            for key, value in payload.items():
                k = str(key).lower()
                if k in {
                    "possibly_sensitive",
                    "sensitive",
                    "nsfw",
                    "is_nsfw",
                    "adult_content",
                    "is_sensitive",
                }:
                    if self._is_truthy_sensitive(value):
                        return True
                if "sensitive" in k and self._is_truthy_sensitive(value):
                    return True
                if self._payload_has_sensitive_flag(value):
                    return True
        elif isinstance(payload, list):
            return any(self._payload_has_sensitive_flag(x) for x in payload)
        return False

    @staticmethod
    def _payload_is_tombstone(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        typename = str(payload.get("__typename", "")).lower()
        if typename == "tweettombstone":
            return True
        return "tombstone" in payload

    @staticmethod
    def _is_truthy_sensitive(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            v = value.strip().lower()
            return v in {"1", "true", "yes", "on", "adult", "nsfw", "sensitive"}
        return False

    async def _is_sensitive_tweet(
        self,
        status_id: str | None,
        html_content: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        if self._html_has_sensitive_hint(html_content):
            return True

        if not status_id:
            return False

        payload = payload or await self._req_syndication_api(status_id)
        if not payload:
            return False

        if self._payload_is_tombstone(payload):
            return True

        return self._payload_has_sensitive_flag(payload)

    @staticmethod
    def _extract_snapcdn_source_url(href: str) -> str | None:
        try:
            parsed = urlparse(href)
            if "dl.snapcdn.app" not in (parsed.netloc or ""):
                return None
            token = parse_qs(parsed.query).get("token", [None])[0]
            if not token or "." not in token:
                return None
            payload_part = token.split(".")[1]
            padding = "=" * (-len(payload_part) % 4)
            data = base64.urlsafe_b64decode(payload_part + padding)
            payload = json.loads(data.decode("utf-8"))
            url = payload.get("url")
            return str(url).strip() if isinstance(url, str) else None
        except Exception:
            return None

    @handle(
        "x.com",
        r"https?://(?:www\.)?x\.com/(?P<username>[0-9A-Za-z_]{1,20})/status/(?P<status_id>\d+)(?:\?.*)?",
    )
    @handle(
        "twitter.com",
        r"https?://(?:www\.)?twitter\.com/(?P<username>[0-9A-Za-z_]{1,20})/status/(?P<status_id>\d+)(?:\?.*)?",
    )
    async def _parse(self, searched: re.Match[str]) -> ParseResult:
        url = searched.group(0)
        username = searched.groupdict().get("username")
        status_id = searched.groupdict().get("status_id")

        resp = await self._req_xdown_api(url)
        if resp.get("status") != "ok":
            raise ParseException("解析失败")

        html_content = resp.get("data")
        if html_content is None:
            raise ParseException("解析失败, 数据为空")

        syndication_payload = (
            await self._req_syndication_api(status_id) if status_id else None
        )

        if self.block_sensitive and await self._is_sensitive_tweet(
            status_id,
            html_content,
            syndication_payload,
        ):
            raise TipException("可能含有成人/敏感内容，已按配置不予解析")

        return self.parse_twitter_html(
            html_content=html_content,
            source_url=url,
            fallback_username=username,
            syndication_payload=syndication_payload,
        )

    def parse_twitter_html(
        self,
        *,
        html_content: str,
        source_url: str,
        fallback_username: str | None = None,
        syndication_payload: dict[str, Any] | None = None,
    ) -> ParseResult:
        soup = BeautifulSoup(html_content, "html.parser")

        title: str | None = None
        cover_url: str | None = None
        video_url: str | None = None
        images_urls: list[str] = []
        dynamic_urls: list[str] = []

        def normalize_href(href: str) -> str:
            href = href.strip()
            if href.startswith("//"):
                return "https:" + href
            return urljoin("https://xdown.app", href)

        def is_placeholder_url(url: str) -> bool:
            parsed = urlparse(url)
            host = parsed.netloc.lower().split(":")[0]
            path = (parsed.path or "").strip()
            return host in {"xdown.app", "www.xdown.app"} and path in {"", "/"}

        def is_probable_video_url(url: str) -> bool:
            if is_placeholder_url(url):
                return False
            parsed = urlparse(url)
            host = parsed.netloc.lower().split(":")[0]
            path = (parsed.path or "").lower()
            query = (parsed.query or "").lower()
            if path.endswith((".mp4", ".m3u8", ".mov", ".webm")):
                return True
            if host.endswith("video.twimg.com"):
                return True
            if "mime=video" in query or "video" in query:
                return True
            return False

        def classify_href(href: str, text: str) -> str | None:
            low_text = text.lower()
            path = urlparse(href).path.lower()
            if path.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                return "image"
            if path.endswith(".gif"):
                return "dynamic"
            if path.endswith(".mp4"):
                return "video"
            if "pbs.twimg.com/media/" in href:
                return "image"
            if re.search(r"(mp4|video|视频)", low_text):
                return "video"
            if re.search(r"(gif)", low_text):
                return "dynamic"
            if re.search(r"(image|photo|图片|照片)", low_text):
                return "image"
            return None

        syndication_user: str | None = None
        syndication_text: str | None = None
        quoted_user: str | None = None
        if isinstance(syndication_payload, dict):
            user_obj = syndication_payload.get("user")
            if isinstance(user_obj, dict):
                syndication_user = user_obj.get("screen_name") or user_obj.get("name")
            text_obj = syndication_payload.get("text")
            if isinstance(text_obj, str):
                syndication_text = text_obj.strip()
            quoted = syndication_payload.get("quoted_tweet")
            if isinstance(quoted, dict):
                quoted_user_obj = quoted.get("user")
                if isinstance(quoted_user_obj, dict):
                    quoted_user = (
                        quoted_user_obj.get("screen_name") or quoted_user_obj.get("name")
                    )

        thumb_tag = soup.find("img")
        if isinstance(thumb_tag, Tag):
            if cover := thumb_tag.get("src"):
                cover_url = normalize_href(str(cover))

        all_anchor_tags = soup.find_all("a")
        tw_button_tags = soup.find_all("a", class_="tw-button-dl")
        abutton_tags = soup.find_all("a", class_="abutton")

        for tag in chain(tw_button_tags, abutton_tags, all_anchor_tags):
            if not isinstance(tag, Tag):
                continue
            href = tag.get("href")
            if href is None:
                continue

            href = normalize_href(str(href))
            text = tag.get_text(strip=True)
            source_href = self._extract_snapcdn_source_url(href) or href
            if is_placeholder_url(source_href):
                continue
            media_type = classify_href(href, text)

            if media_type == "video":
                if not is_probable_video_url(source_href):
                    continue
                video_url = video_url or source_href
            elif media_type == "image":
                if source_href not in images_urls:
                    images_urls.append(source_href)
            elif media_type == "dynamic":
                if source_href not in dynamic_urls:
                    dynamic_urls.append(source_href)

        for img in soup.find_all("img"):
            if not isinstance(img, Tag):
                continue
            src = img.get("src")
            if not isinstance(src, str):
                continue
            src = normalize_href(src)
            if "pbs.twimg.com/media/" in src and src not in images_urls:
                images_urls.append(src)

        title_tag = soup.find("h3")
        if title_tag:
            title = title_tag.get_text(strip=True)
        if not title:
            p_tag = soup.find("p")
            if isinstance(p_tag, Tag):
                txt = p_tag.get_text(strip=True)
                if txt and "xdown" not in txt.lower():
                    title = txt

        contents = []
        if video_url:
            contents.append(self.create_video_content(video_url, cover_url))
        if images_urls:
            contents.extend(self.create_image_contents(images_urls))
        if dynamic_urls:
            contents.extend(self.create_dynamic_contents(dynamic_urls))

        author_name: str | None = None
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "a", "span", "p", "strong"]):
            if not isinstance(tag, Tag):
                continue
            txt = tag.get_text(" ", strip=True)
            if not txt:
                continue
            m = re.search(r"@([0-9A-Za-z_]{1,20})", txt)
            if m:
                author_name = m.group(1)
                break

        if not author_name:
            author_name = syndication_user
        if not author_name:
            author_name = fallback_username
        if not author_name:
            author_name = "未知用户"

        text_content: str | None = syndication_text
        if quoted_user:
            text_content = (
                f"{text_content}\n\n转推自: @{quoted_user}"
                if text_content
                else f"转推自: @{quoted_user}"
            )

        return self.result(
            title=title,
            text=text_content,
            author=self.create_author(author_name),
            contents=contents,
            url=source_url,
        )
