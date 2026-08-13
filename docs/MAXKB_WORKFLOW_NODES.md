# MaxKB 工作流节点（卡片）详解

> 整理时间：2026-08-12。
> 调研对象：MaxKB 本地克隆 `/Users/yang/fzy-project/shjd_pro/MaxKB` @ commit `0568ec05`（2026-01-21，`feat: add chat stats`）——比 `docs/WORKFLOW_ENGINES_RESEARCH.md` 固定的 `847755b1`（2025-08-19）更新，本清单以本地克隆为准。
> 资料来源（一手代码，非文档转述）：
> - 后端节点配置 Schema：`apps/application/flow/step_node/<节点>/i_<节点>.py`（序列化器即卡片表单字段）
> - 后端节点执行与输出：`apps/application/flow/step_node/<节点>/impl/base_*.py`（`execute()` 返回的 `NodeResult` 键）
> - 前端卡片注册与文案：`ui/dist/ui/assets/index-a5e9d247.js` 编译产物中的 `WorkflowType` 枚举、卡片注册表（`config.fields` = 可引用输出）、zh/en i18n 字典（卡片名/描述/字段 label）
> - 前端源码不在本地仓库（`ui/` 仅含 `dist`），卡片表单字段以后端序列化器为准，中文文案以编译产物 i18n 为准。

## 1. 总览

MaxKB 高级编排应用（工作流）共 **19 张卡片**（前端 `WorkflowType` 枚举恰 19 种，含固定的「基本信息」「开始」）。除「基本信息」「开始」各唯一、不可删外，其余均可自由添加。画布 JSON 存 `Application.work_flow` 列，LogicFlow 格式：`{nodes:[{id,type,x,y,properties}], edges:[{sourceNodeId,targetNodeId,...}]}`。

| # | 卡片（UI 名） | `type` | 类别 | 一句话用途 |
|---|---|---|---|---|
| 1 | 基本信息 | `base-node` | 基础 | 应用名/描述/开场白/文件上传/自定义变量（固定节点） |
| 2 | 开始 | `start-node` | 基础 | 注入用户问题与全局变量（固定节点） |
| 3 | AI 对话 | `ai-chat-node` | 模型 | 与 AI 大模型对话 |
| 4 | 知识库检索 | `search-dataset-node` | 知识 | 关联知识库，查找与问题相关的分段 |
| 5 | 问题优化 | `question-node` | 模型 | 按历史聊天优化当前问题 |
| 6 | 判断器 | `condition-node` | 逻辑 | 根据不同条件执行不同分支 |
| 7 | 指定回复 | `reply-node` | 逻辑 | 输出自定义/引用变量的回复内容 |
| 8 | 多路召回 | `reranker-node` | 模型 | 用重排模型对多个检索结果二次召回 |
| 9 | 表单收集 | `form-node` | 逻辑 | 问答中收集用户输入，可中断等待提交 |
| 10 | 文档内容提取 | `document-extract-node` | 知识 | 提取文档中的文本内容 |
| 11 | 图片理解 | `image-understand-node` | 多模态 | 视觉模型识别图片并回答 |
| 12 | 图片生成 | `image-generate-node` | 多模态 | 根据提示词生成图片 |
| 13 | 语音转文本 | `speech-to-text-node` | 多模态 | 语音识别模型把音频转文本 |
| 14 | 文本转语音 | `text-to-speech-node` | 多模态 | 语音合成模型把文本转音频 |
| 15 | 自定义函数 | `function-node` | 逻辑 | 执行自定义 Python 脚本（卡片内写代码） |
| 16 | 自定义函数（函数库） | `function-lib-node` | 逻辑 | 调用「函数库」中保存的函数（与 15 同卡片、两来源） |
| 17 | 应用节点 | `application-node` | 子应用 | 调用其他应用（可嵌套） |
| 18 | 变量赋值 | `variable-assign-node` | 逻辑 | 更新全局变量的值 |
| 19 | MCP 调用 | `mcp-node` | 集成 | 通过 SSE 调用 MCP 服务中的工具 |

> 注：`step_node/` 下另有空目录 `ai_writing_node/`，未注册、未在 UI 出现（遗留占位）。
> 前端卡片注册表 `menuNodes`（节点面板添加顺序）：ai-chat → image-understand → image-generate → search-dataset → reranker → condition → reply → form → question → document-extract → speech-to-text → text-to-speech → variable-assign → mcp；函数节点单独分组。

## 2. 卡片公共结构

每张卡片在画布 JSON 中形如：

```json
{
  "id": "b931efe5-...",
  "type": "search-dataset-node",
  "x": 840, "y": 3210,
  "properties": {
    "stepName": "知识库检索",          // 画布上显示的名称，可改
    "height": 794,                    // 画布卡片尺寸（布局用）
    "config": { "fields": [...] },    // 该卡片对外暴露的可引用字段（变量引用面板）
    "node_data": { ... }              // 卡片表单配置的实际数据
  }
}
```

公共机制：

- **变量引用**：表单中「引用变量」型输入的值是引用地址 `[node_id, field]`（如 `["start-node","question"]`），引擎经 `WorkflowManage.get_reference_field()` 解析；引用表达式（如提示词内 `{{ question }}`）经 `reset_prompt()` 渲染。
- **返回内容开关（`is_result`）**：AI 对话/问题优化/函数/多模态等节点的「返回内容」开关，关闭后该节点内容不输出给用户（不写 `answer_text`）。
- **输出字段**：`config.fields` 决定下游「引用变量」面板里能看到哪些字段；本文每节列出的「输出」= `config.fields` + `execute()` 实际写入节点上下文的键。
- **分支连接**：判断器每个分支有独立出边锚点；多出边 = 并行执行（画布按 Y 坐标排序后分别提交线程池），汇聚节点（判断器）按 `condition: and|or` 决定等待全部/任一分支。
- 运行时每节点 `get_details()` 落库到 `ChatRecord.details`（含 `run_time/status/err_message/name(stepName)` 等公共键）。

## 3. 各卡片详解

### 3.1 基本信息 `base-node`（固定，id=`base-node`）

画布上唯一的应用配置卡片（固定节点，不可删、不可复制）。

卡片内配置：

| 字段 | 位置 | 说明 |
|---|---|---|
| 应用名称 | `node_data.name` | 发布时回填到应用 |
| 应用描述 | `node_data.desc` | 发布时回填到应用 |
| 开场白 | `node_data.prologue` | 对话开始语 |
| 文字转语音方式 | `node_data.tts_type` | 默认 `BROWSER` |
| 文件上传开关 | `properties.file_upload` | 开启后问答页面显示上传文件按钮 |
| 文件上传设置 | `properties.FileUploadSetting` | `maxFiles` 单次最多文件数；`fileLimit` 每文件最大 MB；`fileUploadType` 允许的文件类型（文档/图片/音频，UI 提示：文档需「文档内容提取」节点解析、图片需「视觉模型」节点、音频需「语音转文本」节点） |
| 自定义输入字段 | `properties.input_field_list` | 变量名 + 默认值 → 注册为**全局变量**（API 调用可传入，`get_default_global_variable()` 注入） |
| 用户输入字段 | `properties.user_input_field_list` | 问答页面收集的用户输入（`user_input_config.title`） |

输出：`input_field_list` 定义的变量（全局）；表单提交数据合并进全局上下文。

后端：`workflow_manage.py` 多处特判 `node.type == 'base-node'`；发布时从它回填应用名/描述/开场白。

### 3.2 开始 `start-node`（固定，id=`start-node`）

画布入口，唯一、不可删。无表单配置（仅可改名称）。

输出：

| 字段 | 说明 |
|---|---|
| `question` | 用户问题 |
| `image` / `document` / `audio` | 本次对话上传的文件列表（`[{file_id, url, ...}]`） |
| `time`（全局） | 当前时间 `%Y-%m-%d %H:%M:%S` |
| `history_context`（全局） | 历史问答列表 `[{question, answer}]` |
| `chat_id` / `start_time`（全局） | 会话 ID / 运行开始时间戳 |

### 3.3 AI 对话 `ai-chat-node`

与 AI 大模型对话（LLM 问答节点）。

卡片内配置（`ChatNodeSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 模型 | `model_id` | 是 | 选择大语言模型 |
| 角色设定 | `system` | 否 | 系统提示词 |
| 提示词 | `prompt` | 是 | Jinja2 模板，可引用变量，默认"已知信息" |
| 多轮对话数 | `dialogue_number` | 是 | 带入的历史对话轮数（int） |
| 上下文类型 | `dialogue_type` | 否 | `NODE`（仅取本节点历史）\| `WORKFLOW`（取整条流程历史） |
| 模型参数 | `model_params_setting` | 否 | temperature 等（dict） |
| 模型设置 | `model_setting` | 否 | （dict） |
| 返回内容 | `is_result` | 否 | 开关，关闭后不输出给用户 |
| MCP 开关 | `mcp_enable` + `mcp_servers` | 否 | 开启后对话过程可调用 MCP 工具（SSE） |

输出（`config.fields`：`answer`、`reasoning_content`）：`answer`（AI 回答内容）、`reasoning_content`（思考过程，若模型支持）、`result`、`chat_model`、`message_list`、`history_message`、`question`。

### 3.4 知识库检索 `search-dataset-node`

关联知识库，查找与问题相关的分段（RAG 检索节点）。

卡片内配置（`SearchDatasetStepNodeSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 选择知识库 | `dataset_id_list` | 是 | 知识库 ID 列表（支持我的/共享/机构知识库） |
| 检索问题 | `question_reference_address` | 是 | 变量引用（默认 `start-node.question`） |
| 引用分段数 | `dataset_setting.top_n` | 是 | 检索返回的分段数 |
| 相似度 | `dataset_setting.similarity` | 是 | float，0–2（默认 0.6） |
| 检索模式 | `dataset_setting.search_mode` | 是 | `embedding` \| `keywords` \| `blend` |
| 最大引用字符数 | `dataset_setting.max_paragraph_char_number` | 是 | 拼接结果的截断长度（默认 5000） |

输出（`config.fields` 4 项）：

| 字段 | 说明 |
|---|---|
| `paragraph_list` | 检索结果的分段列表（含 `similarity`、`is_hit_handling_method`、`dataset_id/document_id` 等） |
| `is_hit_handling_method_list` | 满足直接回答条件的分段列表 |
| `data`（UI 名"检索结果"） | 分段标题+内容拼接文本，截断到 `max_paragraph_char_number` |
| `directly_return` | 满足直接回答的分段内容拼接 |

行为：`re_chat` 追问（同问题再次触发）时自动排除历史已引用过的分段 ID（`exclude_paragraph_id_list`）；发布时反向解析该节点更新应用的知识库关联。

### 3.5 问题优化 `question-node`

根据历史聊天记录优化完善当前问题，更利于匹配知识库分段。

卡片内配置（`QuestionNodeSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 模型 | `model_id` | 是 | 大语言模型 |
| 角色设定 | `system` | 否 | 默认"你是一个问题优化大师" |
| 提示词 | `prompt` | 是 | 默认"根据上下文优化和完善用户问题：…请输出一个优化后的问题。" |
| 多轮对话数 | `dialogue_number` | 是 | int |
| 模型参数 | `model_params_setting` | 否 | dict |
| 返回内容 | `is_result` | 否 | 开关 |

输出（`config.fields`：`answer`，UI 名"问题优化结果"）：`answer`/`result`（优化后的问题）、`chat_model`、`message_list`。

### 3.6 判断器 `condition-node`

根据不同条件执行不同的分支（可多分支，UI 卡片宽 600）。

卡片内配置（`ConditionNodeParamsSerializer`）：`branch` 分支列表，每个分支：

| 字段 | 说明 |
|---|---|
| `id` | 分支 ID（随机串） |
| `type` | 分支类型：`IF` \| `ELSE IF N` \| `ELSE` |
| `condition` | 分支内条件组合：`and`（全部满足）\| `or`（任一满足） |
| `conditions[]` | 条件列表：`field`（变量引用 `[node_id, field]`）、`compare`（比较符）、`value`（比较值） |

比较符（前端 `compareList`，后端 `compare/__init__.py` 注册 16 种）：

| 比较符 | 含义 | 比较符 | 含义 |
|---|---|---|---|
| `eq` | 等于 | `len_eq` | 长度等于 |
| `ge` | 大于等于 | `len_ge` | 长度大于等于 |
| `gt` | 大于 | `len_gt` | 长度大于 |
| `le` | 小于等于 | `len_le` | 长度小于等于 |
| `lt` | 小于 | `len_lt` | 长度小于 |
| `contain` | 包含 | `is_true` | 为真 |
| `not_contain` | 不包含 | `is_not_true` | 为假 |
| `is_null` | 为空 | `is_not_null` | 不为空 |

输出（`config.fields`：`branch_name`）：`branch_id`、`branch_name`（命中的分支名，如 `IF`/`ELSE IF 1`/`ELSE`，可供下游引用判断走的分支）。

### 3.7 指定回复 `reply-node`

输出指定内容（常作为流程结束节点输出最终回答）。

卡片内配置（`ReplyNodeParamsSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 回复类型 | `reply_type` | 是 | `custom`（自定义）\| `referencing`（引用变量） |
| 内容 | `content` | 条件必填 | custom 时必填，Jinja2 模板，引用变量转字符串 |
| 引用字段 | `fields` | 条件必填 | referencing 时必填且 ≥2 个（`[引用地址, 说明]`） |
| 返回内容 | `is_result` | 否 | 开关 |

输出（`config.fields`：`answer`）：`answer`（回复内容）。

### 3.8 多路召回 `reranker-node`

使用重排模型对多个知识库的检索结果进行二次召回（RAG 重排节点）。

卡片内配置（`RerankerStepNodeSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 重排内容 | `reranker_reference_list` | 是 | 多个变量引用（通常是多个检索节点的 `paragraph_list`） |
| 检索问题 | `question_reference_address` | 是 | 变量引用 |
| 重排模型 | `reranker_model_id` | 是 | 重排模型 |
| 引用分段数 | `reranker_setting.top_n` | 是 | int |
| 相似度 | `reranker_setting.similarity` | 是 | float 0–2 |
| 最大引用字符数 | `reranker_setting.max_paragraph_char_number` | 是 | int（UI 提示"Score 越高相关性越强"） |

输出（`config.fields`：`result_list`、`result`）：`result_list`（重排结果列表）、`result`（重排结果拼接文本）。

### 3.9 表单收集 `form-node`

在问答过程中收集用户信息，收集到的数据可驱动后续流程（**唯一可中断节点**）。

卡片内配置（`FormNodeParamsSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 表单配置 | `form_field_list` | 是 | 表单字段定义列表（字段名/label/类型/必填等），前端渲染为表单 |
| 表单输出内容 | `form_content_format` | 是 | Jinja2 模板，`{ form }` 为表单占位符；默认"你好，请先填写下面表单内容：`{{ form }}` 填写后请点击【提交】按钮进行提交。" |
| 表单数据 | `form_data` | 否 | 提交后写入的数据（运行期由前端提交） |
| 返回内容 | `is_result` | 否 | 默认开 |

输出（`config.fields`：`form_data`）：`result`（渲染后的表单消息，`<form_rander>{json}</form_rander>` 包裹）、`form_data`（表单全部内容）、`form_field_list`；提交后每个表单字段都进节点上下文可引用。

行为：未提交时中断执行（`is_interrupt_exec()` → SSE 停在该节点）；前端提交时带 `chat_record_id + runtime_node_id + node_data` 重开会话，`load_node` 从 `ChatRecord.details` 重建已执行节点上下文后从断点续跑。

### 3.10 文档内容提取 `document-extract-node`

提取文档中的内容为文本。

卡片内配置（`DocumentExtractNodeSerializer`）：`document_list`（必填，变量引用，通常引用 `start-node.document` 或前置节点文件）。

输出（`config.fields`：`content`）：`content`（文档内容，多文档按分隔符拼接）。

### 3.11 图片理解 `image-understand-node`

用视觉模型识别图片中的对象、场景等信息回答用户问题。

卡片内配置（`ImageUnderstandNodeSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 视觉模型 | `model_id` | 是 | IMAGE 类型模型 |
| 角色设定 | `system` | 否 | |
| 提示词 | `prompt` | 是 | |
| 多轮对话数 | `dialogue_number` | 是 | int |
| 上下文类型 | `dialogue_type` | 是 | `NODE` \| `WORKFLOW` |
| 选择图片 | `image_list` | 否 | 变量引用（引用上传图片列表） |
| 模型参数 | `model_params_setting` | 否 | JSON |
| 返回内容 | `is_result` | 否 | 开关 |

输出（`config.fields`：`answer`）：`answer`（AI 回答内容）、`result`、`chat_model`、`message_list`。

### 3.12 图片生成 `image-generate-node`

根据文本提示词生成图片（TTI）。

卡片内配置（`ImageGenerateNodeSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 图片生成模型 | `model_id` | 是 | TTI 类型模型 |
| 提示词（正向） | `prompt` | 是 | 描述期望的元素和视觉特点 |
| 提示词（负向） | `negative_prompt` | 否 | 描述不希望出现的内容（如颜色、血腥内容） |
| 多轮对话数 | `dialogue_number` | 否 | 默认 0 |
| 上下文类型 | `dialogue_type` | 否 | 默认 `NODE` |
| 模型参数 | `model_params_setting` | 否 | JSON |
| 返回内容 | `is_result` | 否 | 开关 |

输出（`config.fields`：`answer`、`image`）：`answer`（`![Image](url)` 拼接的 markdown）、`image`（图片列表 `[{file_id, url}]`）、`chat_model`、`message_list`。

### 3.13 语音转文本 `speech-to-text-node`

通过语音识别模型把音频转换为文本（STT）。

卡片内配置（`SpeechToTextNodeSerializer`）：`stt_model_id`（语音识别模型，必填）、`audio_list`（选择语音文件，必填，变量引用）、`is_result`（开关）。校验：音频须含 `file_id`。

输出（`config.fields`：`result`）：`answer`（转写文本，多文件换行拼接）、`result`。

### 3.14 文本转语音 `text-to-speech-node`

通过语音合成模型把文本转换为音频（TTS）。

卡片内配置（`TextToSpeechNodeSerializer`）：`tts_model_id`（语音合成模型，必填）、`content_list`（选择文本内容，必填，变量引用）、`model_params_setting`（可选）、`is_result`（开关）。

输出（`config.fields`：`result`）：`answer`（音频展示 label）、`result`（音频列表）。

> i18n 缺陷：中文文案 `tts_model.label` 误写为"语音识别模型"（应为"语音合成模型"），见编译产物 zh 字典。

### 3.15 自定义函数 `function-node`（卡片内写代码）

通过执行自定义 Python 脚本实现数据处理。UI 上"自定义函数"卡片提供两种来源：卡片内写代码（`function-node`）与调用函数库（`function-lib-node`），共用同一个 label。

卡片内配置（`FunctionNodeParamsSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 输入参数 | `input_field_list` | 是 | 每项：`name` 变量名、`is_required` 是否必填、`type`（`string\|int\|dict\|array\|float`）、`source`（`custom` 手填 \| `reference` 引用变量）、`value` 值 |
| 函数 | `code` | 是 | Python 代码（`def handler(...)` 形式，通过受限执行器跑） |
| 返回内容 | `is_result` | 否 | 开关 |

输出（`config.fields`：`result`）：`result`（脚本返回值）。

### 3.16 自定义函数（函数库） `function-lib-node`

调用"函数库"模块中已保存并发布的函数。

卡片内配置（`FunctionLibNodeParamsSerializer`）：`function_lib_id`（选择函数库中的函数，必填，删除校验）、`input_field_list`（输入参数：`name` 变量名 + `value` 值/引用，必填）、`is_result`（开关）。

输出（`config.fields`：`result`）：`result`（函数返回值）。

### 3.17 应用节点 `application-node`

调用其他应用（可嵌套子应用，构建多应用协作流程）。

卡片内配置（`ApplicationNodeSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 应用 | `application_id` | 是 | 选择被调用的应用 |
| 用户问题 | `question_reference_address` | 是 | 变量引用，作为传给子应用的问题 |
| API 输入字段 | `api_input_field_list` | 否 | 子应用 API 输入变量映射 |
| 用户输入字段 | `user_input_field_list` | 否 | 子应用用户输入字段映射 |
| 图片/文档/音频 | `image_list` / `document_list` / `audio_list` | 否 | 透传文件（校验须含 `file_id`） |
| 子节点 | `child_node` | 否 | 子应用内嵌画布（用于编排子流程） |
| 表单数据 | `node_data` | 否 | |

输出（`config.fields`：`result`）：`result`（子应用回答）、`question`（透传问题）。流式场景下子应用回答以生成器形式透传。

### 3.18 变量赋值 `variable-assign-node`

更新全局变量的值（后续节点可引用新值）。

卡片内配置（`VariableAssignNodeParamsSerializer`）：`variable_list`（赋值列表，必填；每项：全局变量名 + 引用值/手填值）。

输出：`result_list`（赋值结果列表）、`variable_list`。前端 `config.fields` 为空（不暴露字段）。

### 3.19 MCP 调用 `mcp-node`

通过 SSE 方式执行 MCP 服务中的工具。

卡片内配置（`McpNodeSerializer`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| MCP Server 配置 | `mcp_servers` | 是 | 服务器配置列表（JSON，仅支持 SSE 调用方式；UI 提示"请输入 JSON 格式的 MCP 服务器配置"） |
| MCP Server | `mcp_server` | 是 | 从配置中选择服务器 |
| 工具 | `mcp_tool` | 是 | 从服务器拉取工具列表后选择 |
| 工具参数 | `tool_params` | 是 | dict，值可引用变量 |

输出（`config.fields`：`result`）：`result`（工具返回内容列表）、`tool_params`、`mcp_tool`。

## 4. 与 `847755b1`（2025-08-19）版本的差异

两个 commit 的 `apps/application/flow/step_node/` 文件列表逐文件比对为空差异（GitHub tree API vs 本地 `find`），关键序列化字段（ai-chat 的 `mcp_enable`/`mcp_servers`、question 的 `is_result`、image-generate 的 `dialogue_type`/`is_result`）在 `847755b1` 已存在——**卡片清单在这两个版本之间无差异**。

两点备注：

- `mcp-node` 于 2025-03-21（`2d6ac806`）加入，两个 commit 均含；`docs/WORKFLOW_ENGINES_RESEARCH.md` 的 3.1 节点类型表未列 `mcp-node`，属该文档疏漏（引擎章节的 `step_node/` 包列表已包含 mcp）。
- 本地克隆 `ui/` 仅有编译产物，卡片中文文案取自 zh i18n 字典（含 `text-to-speech` 节点 label 误写"语音识别模型"的缺陷），与 `847755b1` 的 UI 源码可能存在文案级差异，不影响卡片字段。
