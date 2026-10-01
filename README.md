
<div align="center">

![:name](https://count.getloli.com/@astrbot_plugin_parser?name=astrbot_plugin_parser&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_parser

_✨ 链接解析器 ✨_  

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-3.4%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-Zhalslar-blue)](https://github.com/Zhalslar)

</div>

## 📖 介绍

当前支持的平台和类型：

| 平台    | 触发的消息形态                    | 视频 | 图集 | 音频 |
| ------- | --------------------------------- | ---- | ---- | ---- |
| B 站    | av 号/BV 号/链接/短链/卡片/小程序 | ✅​  | ✅​  | ✅​  |
| 抖音    | 链接(分享链接，兼容电脑端链接)    | ✅​  | ✅​  | ❌️  |
| 微博    | 链接(博文，视频，show, 文章)      | ✅​  | ✅​  | ❌️  |
| 小红书  | 链接(含短链)/卡片                 | ✅​  | ✅​  | ❌️  |
| 小黑盒  | 链接/卡片                         | ✅​  | ✅​  | ❌️  |
| 知乎    | 链接/卡片                         | ✅​  | ✅​  | ❌️  |
| 快手    | 链接(包含标准链接和短链)          | ✅​  | ✅​  | ❌️  |
| 微信视频号 | 链接(含短链)                   | ✅​  | ✅​  | ❌️  |
| acfun   | 链接                              | ✅​  | ❌️  | ❌️  |
| youtube | 链接(含短链)                      | ✅​  | ❌️  | ✅​  |
| tiktok  | 链接                              | ✅​  | ❌️  | ❌️  |
| instagram | 链接                            | ✅​  | ✅​  | ❌️  |
| twitter | 链接                              | ✅​  | ✅​  | ❌️  |
| Iwara | 链接                              | ✅​  | ✅​  | ❌️  |
| Pixiv | 链接 / pid                         | ✅​  | ✅​  | ❌️  |
| QQ空间 | 公开分享链接/卡片                 | ✅​  | ✅​  | ❌️  |

本插件目标：凡是链接皆可解析！尽请期待更新（如果可以,请提交PR）

## 🔀 本 Fork 与上游的区别

本仓库是 [Zhalslar/astrbot_plugin_parser](https://github.com/Zhalslar/astrbot_plugin_parser) 的个人维护版，保留上游功能，并针对当前使用环境增加以下调整：

| 范围 | 本 Fork 的调整 |
| ---- | ------------- |
| X / Twitter | 支持正文中间的链接、无协议链接、`mobile` 域名和多级状态路径；查询参数不会吞掉后续正文；Xdown 无媒体数据或不可用时，可通过 Syndication 返回纯文字帖子；保留敏感内容拦截和更完整的媒体识别 |
| 微博 | 过滤微博表情及“网页链接”等链接卡片装饰图标，避免将它们作为正文媒体发送；保留短链展开、正文图片识别和图片去重 |
| 媒体发送 | 尚未完成下载的远程视频、音频和动图优先发送原始链接；本地文件或已下载完成的媒体使用 AstrBot 文件系统组件分类发送；保留本地文件 URI 兼容处理 |
| 消息防抖 | 按会话隔离；仲裁前登记链接，落选 Bot 也能拦截其他 Bot 回复中的相同链接 |
| 仲裁 | 保留上游表情与排序；失败时退出、复查参与者并核验确认者，计划等待约 1.4 秒，不做超时递补 |
| 版本标记 | `metadata.yaml` 当前为 `v9.9.13`，用于确认已安装本 Fork 的最新修复，并避免插件市场反复提示覆盖本地修改；该版本号不代表上游正式版本 |

本 Fork 地址：[fufuzhou/astrbot_plugin_parser](https://github.com/fufuzhou/astrbot_plugin_parser)。需要上游原版时，请从上游仓库安装；需要以上行为时，请使用本 Fork。

---

## 🎨 效果图

插件默认启用 PIL 实现的通用媒体卡片渲染，效果图如下

<div align="center">

<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/video.png" width="160" />
<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/9_pic.png" width="160" />
<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/4_pic.png" width="160" />
<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/repost_video.png" width="160" />
<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/repost_2_pic.png" width="160" />

</div>

---

## 💿 安装

本维护版请在 AstrBot 插件管理中使用仓库地址安装或更新：

```text
https://github.com/fufuzhou/astrbot_plugin_parser
```

安装后确认版本为 **v9.9.13**。插件市场中的原作者版本不包含本 Fork 的定制行为。更新内容见 [CHANGELOG.md](CHANGELOG.md)。

升级时安装 `requirements.txt` 中的依赖（本次新增 `json5`），然后重载插件。本次合入上游的插件数据目录修复，不自动搬移旧缓存或登录数据；升级后请检查登录状态。Metube 需要另行配置服务，未使用时不要启用。

## ⚙️ 配置

请在astrbot的插件配置面板查看并修改

### QQ空间解析器

QQ空间解析器作为可选模板提供，支持 `h5.qzone.qq.com/ugc/share`、`mobile.qzone.qq.com/l` 等公开分享链接，并优先解析动态中的原图/原视频。未配置登录态或登录态不可用时，会自动回退到公开分享页可获取的媒体。

可选登录态来源：

- **SnowLuma 自动（推荐）**：调用 SnowLuma OneBot HTTP `get_credentials`，固定请求 `domain=qzone.qq.com`，短时缓存凭证；QQ空间接口出现登录态异常时会清缓存、重新获取并自动重试一次。
- **手动 Cookies**：可直接填写 `uin/p_uin`、`skey`、`p_skey` 等 Cookie；SnowLuma 获取失败时也会作为备用登录态。
- 两种登录态都不可用时，解析器仍保留公开 H5 fallback，不要求用户必须部署 SnowLuma。

SnowLuma HTTP 地址默认为 `http://127.0.0.1:3000`。这里填写的是 **OneBot HTTP API 地址，不是 WebSocket 地址**；如果 HTTP API 配置了 `access_token`，同时填写对应的 SnowLuma Access Token。QQ 本体已掉线或需要重新登录时，需要先恢复 QQ 登录，单独刷新 `p_skey` 无法恢复失效的 QQ 会话。

> QQ空间登录态只用于回查当前公开分享动态对应的媒体详情，不用于绕过动态自身的访问权限。

## 🎉 指令

|   指令   |         权限          |        说明        |
| :------: | :-------------------: |  :---------------: |
| 开启解析 |      ADMIN            |     开启当前会话的解析功能      |
| 关闭解析 |      ADMIN            |    关闭当前会话的解析功能      |
|  blogin  |      ADMIN           |   扫码获取 B 站凭证 |

---

## 🧠 插件工作流程

当插件运行后，每一条消息的处理流程如下：

1. **消息接收**  
   监听所有消息事件，获取消息链与原始文本内容  
   - 支持普通文本、链接、卡片（Json 组件）

2. **基础过滤**  
   - 跳过已被禁用的会话  
   - 跳过空消息  
   - 忽略自身发送的消息；存在 @ 提及时，若不包含本 Bot 则不解析
   - 非 aiocqhttp 群可通过 require_at_in_group 要求明确 @ 本 Bot

3. **链接提取与匹配**  
   - 扫描消息链中的 Json 卡片提取 URL；开启 enable_reply_parse 后也可提取引用消息中的链接
   - 使用「关键词 + 正则」双重匹配，定位对应解析器  
   - 未匹配到解析规则则直接退出

4. **链接防抖（Link Debouncer）**
   - 仲裁前登记本会话识别到的链接，窗口内重复链接直接退出
   - 仲裁落选也保留登记，抑制其他 Bot 回复中的相同链接再次触发

5. **仲裁判定（Emoji Like Arbiter）**
   - 仅在 aiocqhttp 群消息生效，通过固定表情协商
   - 确认参与者稳定且确认者仅为自身后，才继续解析

6. **内容解析**  
   - 调用对应平台解析器获取媒体信息  
   - 生成统一的 `ParseResult` 数据结构，再执行资源 ID 防抖

7. **媒体下载与消息构建**  
   - 下载视频 / 图片 / 音频 / 文件  
   - 根据配置决定音频发送方式  
   - 可按配置提示下载失败项

8. **卡片渲染（可选）**  
   - 在非简洁模式或无直传媒体时生成媒体卡片  
   - 使用 PIL 渲染并缓存图片

9. **消息合并与发送**  
    - 当消息段数量超过阈值时自动合并为转发消息  
    - 最终将结果发送到对应会话

---

## 🧩 扩展

插件支持自定义解析器，通过继承 `BaseParser` 类并实现 `platform`, `handle` 即可。

示例解析器请看 [示例解析器](https://github.com/Zhalslar/astrbot_plugin_parser/blob/main/core/parsers/example.py)

---

## 🎉 致谢

本项目核心代码来自[nonebot-plugin-parser](https://github.com/fllesser/nonebot-plugin-parser)，请前往原仓库给作者点个Star!

## 仲裁防御性改进

本 Fork 保留报名表情 289、确认表情 124 和原有排序规则，但取消超时递补。查询异常、空报名列表、自身缺席、参与者集合变化、确认者不唯一或并非自身时均放弃本次解析。单参与者也必须确认；确认前复查参与者，确认后再进行两轮复查。同一实例 120 秒内抑制同一 Bot/消息的重复事件。

报名后约 0.7 秒和 1.0 秒采样，确认后两轮各等 0.2 秒，并发查询参与者和确认者。快速 API 下正常胜出等待约 1.4 秒，另加 API 耗时；这些间隔尚需双 Bot 实测调优。单次 API 超时为 3 秒。列表达到 20 人时视为可能截断并退出，不猜测未返回的参与者。接口必须返回明确的 emojiLikesList 数组，缺失或格式错误会拒绝解析。

优先避免重复发送，因此异常时可能无人回复；不接管胜出者后续解析或发送失败。所有参与 Bot 建议同步升级，旧版仍可能提前放行。持续隔离的表情视图仍可能导致双胜出，这不是严格的分布式锁；普通用户贴协议表情也可能造成拒绝服务。

日志以 [arbiter] 开头：INFO 记录消息 ID、Bot ID、消息时间和退出原因，DEBUG 记录每轮参与者/确认者及排序，WARNING 记录查询或贴表情失败。排查重复回复时应同时收集两边日志。

链接防抖在仲裁前登记：落选 Bot 也会记住本群见过的链接，因此其他 Bot 的回复再次包含同一匹配链接时，不再参与仲裁或解析。沿用 debounce_interval（默认 300 秒）；设置为 0、缓存过期/进程重启、没有收到原消息，或短链变成长链等匹配字符串变化时，不能据此拦截。窗口内用户手动重发相同链接也会跳过，原消息仲裁/解析失败后不会立即重试。此改动只能约束已升级的 Bot，不能阻止未升级的其他 Bot 解析本 Bot 的输出。

### 验证与排查

当前 114 项自动化测试通过，覆盖异常查询、确认身份、参与者变化、重复事件、1.4 秒计划等待、落选后的同链接回声及跨群隔离。尚未做真实 QQ 双 Bot 联调，实际耗时和跨实现兼容性以部署日志为准。关闭 debounce_interval 会同时关闭同链接回声防护。

排查时先记录双方版本、原消息和结果消息，再收集对应的 `[arbiter]` 日志；启用 DEBUG 可查看每轮成员列表和排序。出现 `query_failed` 应检查 API 返回格式或超时，`membership_changed_*` 表示观察窗口内成员发生变化，`feedback_not_exclusively_self` 表示确认状态缺失或存在其他确认者。

### 发送前完整文本精确判重

从收到的消息中提取顶层文本段，忽略图片、视频等非文本组件，与所有计划输出分组的文本按顺序拼接后比较。比较内容包括解析摘要（作者、时间、标题、简介及已有附加信息）、媒体链接文本、TextContent 和图文附加说明。统一 CRLF/CR 为 LF、去除整体首尾空白，不忽略中间空白和稳定字段差异。微博模板有一处例外：只忽略公开/受限标识、作者 ID、时间和微博链接后固定位置的评论/转发/点赞统计行，防止两次请求之间计数变化造成回声；主帖与转发分别处理，正文中的类似数字行仍参与比较。

文本非空且完全相同时，跳过整个回复，包括封面、视频、预览卡片、合并转发和备用文本；无需验证图片是否相同，也不要求输入已经包含输出媒体。此规则用于识别其他 Bot 的解析回声，例如 B 站短链被 A 解析后输出完整摘要和封面，B 从摘要中的长链得到相同文本就不再回复。媒体任务若已由解析阶段创建，命中后取消仍在等待的媒体/封面下载。

判重在媒体下载等待、卡片渲染和任何发送之前执行，但仍需先完成解析。只有链接相同、标题相同或摘要只出现于原消息的一部分，不会命中完整文本相等。模板差异、除微博头部统计外的动态字段或媒体直链变化仍可能导致无法拦截；不会对图片做 OCR 或跨多条输入消息拼接，也不展开输入中的合并转发节点。相同文本下即使媒体不同也会跳过，这是本 Fork 的明确发送策略。真实 QQ 环境尚未联调。
