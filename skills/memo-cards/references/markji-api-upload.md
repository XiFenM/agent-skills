# 官方 API 上传与密钥配置

## 来源与适配范围

核验日期：2026-09-08。[官方文档](https://open.maimemo.com/#/)页面通过
[OpenAPI 规范](https://open.maimemo.com/api_bundle.yaml)加载接口定义；[Markji 网站](https://www.markji.com/)
用于查看牌组、章节和实际卡片渲染。内容规则见[兼容面](markji-3.8-compatibility.md)。

本工具实现向**已有自建牌组的已有章节追加卡片**，保留本地 Markdown／XLSX 工作流。
牌组和章节由用户在 Markji 中建立；当前官方规范未提供其创建接口，不能猜测接口。
卡片更新和文件上传虽然有官方接口，本工具尚未实现，不能用临时脚本绕过其预览和恢复边界。

| 项目 | 已核验合同 |
|---|---|
| 基址 | `https://open.maimemo.com/open/api/v1/markji` |
| 鉴权 | `Authorization: Bearer <token>`，仅由进程内存构造 |
| 我的自建牌组 | `GET /decks?offset=0&limit=20`；`decks` 与 `total` 支持显式分页 |
| 指定牌组 | `GET /decks/{deck}` → `deck` |
| 章节列表 | `GET /decks/{deck}/chapters` → `chapters` |
| 章节及卡片 | `GET /decks/{deck}/chapters/{chapter}?with_cards=true` → `chapter`、`cards` |
| 创建 | `POST /decks/{deck}/chapters/{chapter}/cards` → `card`、`chapter` |
| 单卡读回 | `GET /decks/{deck}/cards/{card}` → `card` |

创建请求在路径中指定 deck 和 chapter，线上 JSON 是
`{"card":{"content":"…","grammar_version":…},"order":…}`。
2026-09-09 实际只读调用确认：生产响应外层是 `success`、`data`、`errors`，上述返回对象位于 `data`；
只有业务成功且无错误时才消费。OpenAPI ID 是不透明字符串，已观察到大小写、数字、下划线、短横线和
点号，不能按短卡片引用 ID 校验，也不能更改大小写或自行拆分。
2026-09-09 实测：规范把 deck/chapter 列入请求消息，但在 JSON 正文重复发送这两个不透明 ID 会返回
`common_invalid_param`。客户端在内存中核对路径与目标一致，然后从线上 JSON 排除它们；按已核验的章节
长度显式设置追加位置 `order`，空章节为 0。`content` 是完整 Markji 文本，包含
真实换行、题面、答案线和答案。不能发送字段字典、Markdown manifest 或 XLSX 文件来代替它。
JSON 序列化负责转义换行和反斜杠；解码后必须恢复原始文本，不手工双重转义。

`deck.id`、`chapter.id`、`card.id` 是 API 操作 ID；API 返回的 `card.root_id` 也可能是 `mkjr_…` 形式的
不透明 OpenAPI ID。回执记录它用于定位；不要把它直接当作编辑器内容语法所用的短 root ID，后者需要另行核实。
`grammar_version` 为整数，规范未给出可通用采用的默认值；先在 Markji 创建一张可正常渲染的示例卡，
再通过 `inspect --chapter` 查看版本。空章节可参考同账号其他已验证章节；不能把 `3.8.00` 换算成语法版本。

官方频控为 20 次／10 秒、40 次／60 秒；Markji 另有 8000 次／5 小时限制。工具把请求串行间隔至少
1.6 秒，每批最多 200 张卡，遇到 429 就停止；这个间隔不保证账号在多个进程或长期运行下不会达到限额。

## 设置密钥

用户本人打开[官方请求凭证入口](https://open.maimemo.com/open/api/v1/tokens/openapi)获取 token。
不在 Agent 工具中打开已登录的凭证页面，不让用户粘贴 token 到聊天，也不截图、打印或记录 token。

优先从系统凭据管理器或密码管理器向上传进程注入 `MAIMEMO_API_TOKEN`。这属于本机秘密配置，
不进入 `.agent-skills-config/`、生成 context、Skill、request 或回执。不要把 token 写在 shell 命令中，
也不要使用 `env`、`printenv`、`set -x`、`curl -v` 来检查它。环境变量会对同权限进程和子进程可见；
密码管理器应按需注入，避免在全局 shell 配置中长期导出。

对于 Linux／macOS，也可由用户本人在**交互终端**运行：

```bash
python3 .agent-skills/skills/memo-cards/scripts/markji_api.py auth-set
python3 .agent-skills/skills/memo-cards/scripts/markji_api.py auth-status
```

`auth-set` 使用隐藏输入，不接受命令行 token 或管道输入。默认写入
`~/.config/memo-cards/maimemo-token`；设置了 `XDG_CONFIG_HOME` 时改用其下的 `memo-cards/maimemo-token`。
专用目录必须为 `0700`，凭据文件必须为 `0600` 且归当前用户所有。文件存储是权限保护的明文，
需要加密存储时采用系统凭据管理器。工具拒绝 Git 仓库内路径、符号链接、硬链接和权限过宽的凭据。

自定义路径只通过 `MAIMEMO_API_TOKEN_FILE` 指定仓库外绝对路径；不得把路径变量误设为 token 值。
读取优先级为环境变量 token → 私有凭据文件，设置了无效环境变量时直接报错，不静默回退。
Windows 使用凭据管理器注入环境变量；文件权限模式暂不支持 Windows。远程运行时应在实际执行机器
单独配置秘密，不通过 Git 同步凭据。`auth-status` 只显示存在性，不读取 token，也不代表鉴权已成功。

轮换时先在官方撤销旧 token，由本人移除旧的本机凭据文件，再重新运行 `auth-set`。如果曾泄露，
撤销／轮换才会使旧凭据失效；删除聊天或 Git 文件不能替代撤销。不要宣称官方 token 拥有未核验的细粒度权限。

## 使用流程

用户始终可以用自然语言指定制卡与上传。以下命令供 Agent 执行，只有密钥设置由用户在终端操作。

1. 按原流程完成 `memo_cards.py prepare → publish → verify --request`；同一 request 必须得到
   `operation=no-op`、`would_write=false`。旧产物受模板升级影响时，先展示本地迁移差异，不批量改写。
2. 对准确目标只读查询。牌组不明确时使用 `decks --offset 0 --limit 20`，根据 `total` 按需翻页；
   `inspect --deck <ID>` 列章节，`inspect --deck <ID> --chapter <ID>` 核对章节和已用语法版本。
   不通过标题、网页 URL、文件夹 ID 或本地 collection 猜测 deck／chapter ID。
3. 执行上传预览：

```text
python3 scripts/markji_api.py prepare --repo <repo> --context <context> --request <request.json> --deck <deck_id> --chapter <chapter_id> --grammar-version <verified_integer>
```

展示牌组／章节名称与 ID、`is_private`、完整卡片文本、create／skip 项和 `preview_digest`。
上传到非私有牌组意味着内容将按该牌组现有可见性展示，应让用户在预览中明确看见这一事实。
用户已经明确授权准确目标和内容时无需重复确认；仍缺少目标或上传授权时，只补足缺失信息。

一个文件集可按卡片主题分配到不同章节。为每个目标在 `prepare` 和 `upload` 中重复添加相同的
`--logical-id <mc-...>` 参数；也可在 Python 调用中传 `logical_ids=[...]`。集合必须非空、无重复，
且每个 ID 都是该文件集当前可导出的 active 卡片。工具继续验证完整文件集，只为选中的卡片生成动作，
并将所选 ID 绑定到预览；不能通过筛选掩盖本地产物漂移。省略参数表示整个可导出文件集，因此存在
暂缓卡或多个目标章节时必须显式选择。不同批次仍保留该目标的既有回执记录。

```text
python3 scripts/markji_api.py upload --repo <repo> --context <context> --request <request.json> --deck <deck_id> --chapter <chapter_id> --grammar-version <verified_integer> --preview-digest <digest> --authorization request|confirmed
```

上传器重新验证本地产物、来源、远端快照和回执后才开始创建。它不接受自定义 API 地址，保持 TLS 校验，
禁用自动重定向和环境代理，不输出请求头、完整错误正文或 token 的任何片段。HTTP 错误只提取限长且
脱敏的 code/msg/info，含凭据提示的字段整体隐藏。需要代理时先明确新的受信
传输方案，不能临时关闭证书校验或把凭据发送到兼容网关。

## 去重、恢复与结果

完全相同内容且语法版本相同的唯一正常远端卡片会被跳过；这不是语义去重。
语义身份已经上传而内容发生改变时，本工具停止，保留给显式远端更新流程处理。

上传回执默认位于 `~/.local/state/memo-cards/`，或 `XDG_STATE_HOME` 下的同名目录，位于仓库之外。
它绑定消费仓库、目标文件、牌组和章节，记录逻辑 ID、内容摘要、语法版本、远端 `card.id` 与 `root_id`，
不保存 token 或卡片全文。授权上传包含生成必要恢复回执；不得把回执当作可随意删除的临时文件。

每次 POST 前持久记录 `pending`，得到 ID 后记录 `created`，独立 GET 核对后记录 `verified`。
遇到超时、错误或进程中断时保留状态，不自动重试 POST。明确收到 HTTP 400 时保存 `rejected` 与状态码；
该次调用仍停止，核对错误及远端后，需要新预览才能重新提交。超时／5xx 等未知结果继续保留 `pending`，
不能通过改状态或删除回执绕过不确定结果。同一原请求恢复时重新预览：唯一远端内容匹配
可以恢复为 skip；无法找到唯一匹配就停止，由用户核对账号、章节和中断结果。不要为通过检查而删除回执。
中断遗留的 `upload.lock` 只有在确认无上传进程后才由本人移除。

完成时核对全部 ID 仍属于目标章节，报告新增／跳过数量和回执路径。接口成功与内容读回不等于客户端
视觉验证；首次使用新语法，应在 Markji 检查一张代表卡。没有真实 token／账号测试时明确说明。
官方创建接口未声明幂等键或条件写入；本工具的串行锁和回执不能保证与其他设备同时写入时的全局唯一性，
也不提供跨本地产物和远端账号的原子事务或自动回滚。
