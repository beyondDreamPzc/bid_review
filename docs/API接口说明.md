# 投标审查系统：中文接口使用手册

适用版本：0.2.0。由当前应用的 OpenAPI 自动生成。

先读 [业务流程与接口](业务流程与接口.md)，理解谁在什么场景调用接口，再查本手册的参数。

在线调试：[Swagger](http://127.0.0.1:18080/docs)；机器可读规范：[OpenAPI JSON](openapi.json)。

本系统当前支持**投标材料工程基础和人工业务闭环**：上传 PDF 保留修订、核对原文、人工整理并确认要求、发布基线和正式材料集、登记问题、指派整改、由另一人复核，再逐项作出审核决定。
完整业务场景和连续调用例子见项目 `docs/业务流程与接口.md`。当前 `review_mode=HUMAN`，未接入模型抽取、RAG 或自动审查。

### 第一次使用

1. 点击右上角 **Authorize**，填入项目本地 `.env` 中的 `BID_BOOTSTRAP_API_KEY` 的值；只填值，不加 `Bearer`。
2. 创建项目，记下返回的 `id`，它就是 `project_id`。
3. 上传 PDF，记下 `document_id`、`revision_id`、`job_id`。
4. 查询任务；`status=SUCCEEDED` 后取得 `artifact_id`。
5. 查询解析产物和文字块，再用来源接口获取页码、矩形位置和原件地址。
6. 在“08 要求与基线”登记并确认要求，发布基线；在“09 正式响应材料”明确本轮正式文件。
7. 在“10 问题与整改”登记冲突并指定负责人；整改后由另一人复核，在“11 人工审查结论”完成逐项确认并查看报告。

### 五种 ID 分别是什么

| 名称 | 含义 | 从哪里取得 |
|---|---|---|
| `project_id` | 一次投标工作的资料空间 | 创建/列出项目 |
| `document_id` | 一份逻辑文档，例如技术响应书；多个修订共用 | 上传新文档 |
| `revision_id` | 某一次不可变的 PDF 文件版本 | 上传或列出修订 |
| `job_id` | 后台处理这份文件的任务 | 上传接口 |
| `artifact_id` | 某修订按某解析配置生成的结果 | 查询成功任务 |

`block_id` 是某个产物内部的文字块编号，必须与其 `artifact_id` 配套使用。示例 ID 只说明格式，实际调用时请替换为接口真实返回的 ID。

### 需要正确理解的状态

- HTTP **202**：系统已接收上传并登记任务，请继续查询任务；不表示解析已经完成。
- `SUCCEEDED`：文字层提取的技术任务已完成，不表示投标业务满足要求。
- `NEEDS_REVIEW`：产物需要检查；当前尚未验证表格语义，也没有运行 OCR。
- `formal_review_ready=false`：文字层探针尚不支持自动审查。人工业务可以引用这些文字块，但必须回看原件；自动要求抽取、Milvus、模型审查和更正影响分析尚未接入。
- `review_epoch`：当前要求基线和正式材料集组合的版本号。重新发布会使旧提交和审核决定过期；历史记录保留。
- `REVIEW_COMPLETE`：本轮全部要求已经人工确认，相关问题均独立复核，且没有未发布的要求修改；不是模型自动给出的合规结论。

除健康检查外，所有业务接口都需要 `X-API-Key`。找不到对象和无权访问对象统一返回 **404**。

## 推荐调用顺序

```mermaid
flowchart LR
  A[Authorize 认证] --> B[创建/选择项目] --> C[上传 PDF] --> D[查询 job]
  D -->|SUCCEEDED| E[读取 artifact 概况] --> F[读取 blocks] --> G[查询 source] --> H[下载原 PDF 核对]
  D -->|FAILED| I[查看错误并处理]
```

业务闭环：登记要求 → 人工确认 → 发布基线 → 选择正式材料 → 登记问题 → 负责人整改 → 另一人复核 → 逐项审核 → 查看报告。

## 参数位置怎么区分

| 位置 | 含义 | 如何填写 |
|---|---|---|
| path | URL 路径中的占位符，例如 `{project_id}` | 使用上一步真实返回的 ID |
| query | URL 问号后的筛选或分页参数 | 例如 `?page=3&offset=0&limit=100` |
| header | HTTP 请求头 | `X-API-Key` 负责认证，`Idempotency-Key` 负责业务写入去重 |
| JSON body | JSON 请求体 | 创建项目时填写 `{"name":"项目名称"}` |
| multipart/form-data | 文件加表单字段 | 上传 PDF 时选择 file，并填写 title/kind 等 |

## 全部接口

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/projects` | 创建一次投标工作的项目空间 |
| GET | `/api/v1/projects` | 列出我有权限访问的项目 |
| GET | `/api/v1/me` | 查询我是谁，取得成员授权用的用户 ID |
| POST | `/api/v1/projects/{project_id}/members` | 把已有用户加入项目或调整协作角色 |
| GET | `/api/v1/projects/{project_id}/members` | 查看可协作的项目成员与角色 |
| GET | `/api/v1/projects/{project_id}/workspace` | 查看项目工作台和当前审查输入版本 |
| POST | `/api/v1/projects/{project_id}/documents` | 上传一份新 PDF 文档并登记解析任务 |
| POST | `/api/v1/documents/{document_id}/revisions` | 为已有文档上传新 PDF 修订并保留历史 |
| GET | `/api/v1/documents/{document_id}/revisions` | 查看一份文档的全部历史修订 |
| GET | `/api/v1/jobs/{job_id}` | 查询后台解析任务状态及产物 ID |
| GET | `/api/v1/artifacts/{artifact_id}` | 查看解析概况、页数和质量提示 |
| GET | `/api/v1/artifacts/{artifact_id}/blocks` | 按页和分页条件读取文字来源块 |
| GET | `/api/v1/artifacts/{artifact_id}/blocks/{block_id}/source` | 把某段文字定位到具体文件版本、页码和坐标 |
| GET | `/api/v1/revisions/{revision_id}/original` | 预览或下载某个历史修订的原始 PDF |
| POST | `/api/v1/projects/{project_id}/requirements` | 从招标原文登记一条待确认要求 |
| GET | `/api/v1/projects/{project_id}/requirements` | 查看全部要求的最新草稿或确认版 |
| POST | `/api/v1/projects/{project_id}/requirements/{requirement_id}/revisions` | 因更正或录入错误新增要求修订 |
| GET | `/api/v1/projects/{project_id}/requirements/{requirement_id}/revisions` | 追溯一条要求的全部历史修订 |
| POST | `/api/v1/projects/{project_id}/requirements/{requirement_id}/confirm` | 人工确认最新要求正文及出处 |
| POST | `/api/v1/projects/{project_id}/baselines` | 发布本次审查采用的不可变要求基线 |
| GET | `/api/v1/projects/{project_id}/baselines` | 查看历次基线及各自冻结的要求 |
| POST | `/api/v1/projects/{project_id}/material-sets` | 明确选择本次正式响应文件和附件 |
| GET | `/api/v1/projects/{project_id}/material-sets` | 追溯历次审查使用的正式材料快照 |
| POST | `/api/v1/projects/{project_id}/issues` | 登记一条审查问题并指派整改任务 |
| GET | `/api/v1/projects/{project_id}/issues` | 查看问题、整改进展及旧结论是否过期 |
| GET | `/api/v1/projects/{project_id}/tasks` | 查看本项目整改待办与复核记录 |
| POST | `/api/v1/projects/{project_id}/tasks/{task_id}/transitions` | 负责人开始整改或提交修改后的正式证据 |
| GET | `/api/v1/projects/{project_id}/tasks/{task_id}/submissions` | 追溯任务历次整改提交及其材料依据 |
| POST | `/api/v1/projects/{project_id}/tasks/{task_id}/decisions` | 由另一人复核当前整改提交，验收或退回 |
| POST | `/api/v1/projects/{project_id}/requirement-decisions` | 对当前要求逐项记录人工最终决定 |
| GET | `/api/v1/projects/{project_id}/requirement-decisions` | 查看逐项审核决定的完整历史 |
| GET | `/api/v1/projects/{project_id}/review-report` | 查看本轮人工审查覆盖、未解决问题和完成状态 |
| GET | `/health/live` | 检查 API 进程是否存活 |
| GET | `/health/ready` | 检查数据库和基础表是否就绪 |

## 1. 创建一次投标工作的项目空间

`POST /api/v1/projects`

**用途**：为一次投标工作建立资料空间，例如“某信息化系统采购项目”。

**请求**：JSON 格式，填写 `name`；当前用户自动成为项目 OWNER。

**返回**：201 和 `{id, name}`。把这里的 `id` 作为后续上传接口的 `project_id`。

**注意**：项目名称不是唯一键；再次调用会创建另一个项目。本接口当前没有 Idempotency-Key 去重。

**认证**：需要 `X-API-Key`。

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `name` | 是 | string | 最短字符数=1；最长字符数=200 | 本次投标工作的名称，建议写采购项目名称。首尾空格会去掉；纯空白名称会返回 422。 |

```json
{
  "name": "上海12345平台二期投标材料检查"
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 201 | 项目已创建；返回的 id 用作后续 project_id。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 项目 ID。上传文档时填入路径参数 project_id。 |
| `name` | string | 项目名称。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "name": "上海12345平台二期投标材料检查"
}
```

## 2. 列出我有权限访问的项目

`GET /api/v1/projects`

**用途**：找回当前用户有权限访问的项目 ID 和名称。

**参数**：无额外参数，身份由 X-API-Key 确定。

**返回**：200 和数组；没有项目时为 `[]`。当前没有分页，也没有约定排序。不返回其他用户的私有项目。

**认证**：需要 `X-API-Key`。

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | 项目数组；没有可访问项目时为 []。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 项目 ID。上传文档时填入路径参数 project_id。 |
| `name` | string | 项目名称。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "id": "11111111-1111-4111-8111-111111111111",
    "name": "上海12345平台二期投标材料检查"
  }
]
```

## 3. 查询我是谁，取得成员授权用的用户 ID

`GET /api/v1/me`

**业务场景**：负责人要把同事加入投标项目，需要同事的用户 ID。

**使用人/前置条件**：任意已配置 API Key 的用户。

**处理与结果**：返回本密钥对应的 ID 和姓名，不返回密钥本身。

**下一步**：同事把自己的 ID 告知项目负责人，再由负责人添加成员。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 当前 API Key 对应的用户 ID，不返回密钥或 hash。 |
| `name` | string | 当前用户显示名称。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "示例",
  "name": "示例"
}
```

## 4. 把已有用户加入项目或调整协作角色

`POST /api/v1/projects/{project_id}/members`

**业务场景**：投标负责人组织编写人、审查人及只读观察者，形成责任分工。

**使用人/前置条件**：仅项目 OWNER；目标账号须先通过 CLI bootstrap 创建。

**处理与结果**：按用户 ID 设置项目角色；不能通过本接口变更 OWNER，已有整改任务的负责人须保留 EDITOR 角色。

**下一步**：EDITOR 录入资料和整改，REVIEWER 确认要求并复核；提交整改的人不能自己复核。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `user_id` | 是 | string | — | 已在系统中创建的用户 ID。用户可通过 /api/v1/me 查询自己的 ID。 |
| `role` | 是 | string | 可选值=EDITOR, REVIEWER, READER | EDITOR 编写/整改；REVIEWER 确认要求、登记问题和复核；READER 只读。只有项目 OWNER 可设置。 |

```json
{
  "user_id": "示例",
  "role": "EDITOR"
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | string | 用户 ID。 |
| `name` | string | 用户显示名。 |
| `role` | string | 项目角色：OWNER/EDITOR/REVIEWER/READER。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "user_id": "示例",
  "name": "示例",
  "role": "示例"
}
```

## 5. 查看可协作的项目成员与角色

`GET /api/v1/projects/{project_id}/members`

**业务场景**：审查人登记问题前要选择整改负责人，负责人要检查谁具有复核权限。

**使用人/前置条件**：任意项目成员。

**处理与结果**：返回本项目成员及 OWNER/EDITOR/REVIEWER/READER 角色，不暴露其他项目成员或任何 API Key。

**下一步**：登记问题时只能选择本项目的 OWNER 或 EDITOR 为 assignee_id。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | string | 用户 ID。 |
| `name` | string | 用户显示名。 |
| `role` | string | 项目角色：OWNER/EDITOR/REVIEWER/READER。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "user_id": "示例",
    "name": "示例",
    "role": "示例"
  }
]
```

## 6. 查看项目工作台和当前审查输入版本

`GET /api/v1/projects/{project_id}/workspace`

**业务场景**：进入项目后，确认当前审查哪版要求、哪套响应材料，以及自己能做什么。

**使用人/前置条件**：任意项目成员。

**处理与结果**：返回我的角色、当前基线/材料集 ID、review_epoch、要求/问题数量和未发布修改提示；不把问题总数冒充待办数。

**下一步**：写入前保存 review_epoch；若返回 409，刷新工作台并重新核对材料。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | string | 投标项目 ID。 |
| `name` | string | 项目名称。 |
| `my_role` | string | 当前用户的项目角色。 |
| `review_epoch` | integer | 当前有效业务输入版本。发布要求基线/材料集会递增，写操作须携带所见值。 |
| `current_baseline_id` | string / null | 当前要求基线；尚未发布为 null。 |
| `current_material_set_id` | string / null | 当前正式材料集；尚未发布为 null。 |
| `requirement_count` | integer | 已录入逻辑要求数。 |
| `issue_count` | integer | 历史登记的问题总数，不等于当前未解决数。 |
| `pending_requirement_changes` | boolean | 存在未纳入当前基线的新要求/新修订；需确认并重新发布基线。 |
| `review_mode` | string | 当前为人工业务流程，尚无模型自动抽取/审查。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "project_id": "示例",
  "name": "示例",
  "my_role": "示例",
  "review_epoch": 1,
  "current_baseline_id": "示例",
  "current_material_set_id": "示例",
  "requirement_count": 1,
  "issue_count": 1,
  "pending_requirement_changes": false,
  "review_mode": "HUMAN"
}
```

## 7. 上传一份新 PDF 文档并登记解析任务

`POST /api/v1/projects/{project_id}/documents`

**用途**：在已有项目下新增一份逻辑文档，并保存它的第 1 个 PDF 修订、后台任务及待投递事件。

**填写方式**：`multipart/form-data`。选择 `file`，填写 `title` 和 `kind`，请求头填写 `Idempotency-Key`。

**文件类型**：TENDER=招标文件；AMENDMENT=更正公告；RESPONSE=投标响应；EVIDENCE=证明材料。目前这些类型用于分类存储，上传更正公告不会自动修改要求或触发变更分析。

**返回**：202，保存 document_id、revision_id、job_id。随后查询任务，成功后取得 artifact_id。

**重复请求**：同一用户、项目和新增文档操作内，同键且内容/元数据相同返回原响应；同键但内容或元数据不同返回 409。换一个键会创建另一份逻辑文档，即使文件名或字节相同。

**文件校验**：默认最大 50 MiB；只检查接收格式，损坏、加密、超过默认 300 页等问题可能在后台任务中失败。202 不保证最终解析成功。

**source_url**：仅记录材料来源地址，不会替你从这个网址下载文件；仍须上传 file。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 项目 ID，从创建或列出项目接口取得；不是项目名称。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 一次上传操作的去重凭据，建议使用随机 UUID。网络重试沿用同键和同内容；业务内容改变使用新键。它不是 X-API-Key，也不是文件名。 |

**请求体：`multipart/form-data`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `file` | 是 | string | — | 本机选择的 PDF 文件。默认最大 50 MiB；必须是真实 PDF 内容。此阶段不接收 DOCX。 |
| `title` | 是 | string | 最短字符数=1；最长字符数=200 | 这份逻辑文档的显示名称，例如某项目招标文件；1–200 字符且不能为纯空白。 |
| `kind` | 是 | string | 可选值=TENDER, AMENDMENT, RESPONSE, EVIDENCE | 材料类型：TENDER 招标文件；AMENDMENT 更正公告；RESPONSE 投标响应；EVIDENCE 证明材料。更正类型当前只作分类存储。 |
| `source_url` | 否 | string (uri) / null | — | 可选的 HTTP/HTTPS 来源地址，仅保存出处，不访问该地址，也不能替代 file 上传。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 202 | 已接收或命中幂等记录；请保存 job_id 并继续查询处理状态。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 413 | 上传字节数超过配置上限，默认 50 MiB（52,428,800 字节）。分拆文件或调整服务配置。 |
| 415 | 当前阶段只接收以 %PDF- 开头的 PDF 内容。改扩展名无效；DOCX 和扫描 OCR 尚未接入。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `document_id` | string | 逻辑文档 ID。一份文档的多个修订共用此 ID；上传新修订时使用它。 |
| `revision_id` | string | 本次文件的不可变修订 ID。下载原件时使用它。 |
| `revision_no` | integer | 同一逻辑文档内从 1 开始递增的修订号。它不是项目的总文档数。 |
| `job_id` | string | 后台文字层解析任务 ID。用 GET /api/v1/jobs/{job_id} 查询处理状态。 |
| `sha256` | string | 上传原始 PDF 字节的 SHA-256，用于验证原件一致性；不是文字内容摘要。 |
| `reused` | boolean | true：上传新修订时发现同一文档已有完全相同的文件，复用旧修订和任务。幂等键重放返回原响应，reused 也保持原值，因此 false 不代表这次一定新增记录。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "document_id": "22222222-2222-4222-8222-222222222222",
  "revision_id": "33333333-3333-4333-8333-333333333333",
  "revision_no": 1,
  "job_id": "44444444-4444-4444-8444-444444444444",
  "sha256": "e62549d0c0326992b008c73ebdc6e14934e485b1adbdd6a1a79aee3ab9f5c4f6",
  "reused": false
}
```

## 8. 为已有文档上传新 PDF 修订并保留历史

`POST /api/v1/documents/{document_id}/revisions`

**用途**：给一份已有逻辑文档增加新 PDF 版本，例如“技术响应书修改版”。document_id 保持不变，新的文件生成新的 revision_id 和递增 revision_no。

**请求**：选择 file，传 Idempotency-Key，可选 source_url。标题和材料类型沿用原逻辑文档，不在此修改。

**去重**：同一文档内，如 PDF 原始字节 SHA-256 与历史某修订相同，复用该修订和已有任务，返回 reused=true；不保证是最新修订。若幂等键命中原请求，返回原响应，reused 字段也保留原值。

**返回**：202。旧修订仍可查询和下载；新上传不会覆盖旧文件。当前没有“自动选为正式投标版本”的行为。

**权限与后续**：需要 OWNER/EDITOR；用 job_id 查询后台处理，再读取产物。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `document_id` | path | 是 | string | — | 逻辑文档 ID，从上传新文档接口取得；多个修订共用此 ID。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 一次上传操作的去重凭据，建议使用随机 UUID。网络重试沿用同键和同内容；业务内容改变使用新键。它不是 X-API-Key，也不是文件名。 |

**请求体：`multipart/form-data`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `file` | 是 | string | — | 这份逻辑文档的新 PDF 内容。完全相同的历史字节会复用旧修订。默认最大 50 MiB。 |
| `source_url` | 否 | string (uri) / null | — | 可选的新修订来源网址，只记录出处，不下载文件。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 202 | 返回新修订/任务，或同文档相同字节对应的历史修订/任务。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 413 | 上传字节数超过配置上限，默认 50 MiB（52,428,800 字节）。分拆文件或调整服务配置。 |
| 415 | 当前阶段只接收以 %PDF- 开头的 PDF 内容。改扩展名无效；DOCX 和扫描 OCR 尚未接入。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `document_id` | string | 逻辑文档 ID。一份文档的多个修订共用此 ID；上传新修订时使用它。 |
| `revision_id` | string | 本次文件的不可变修订 ID。下载原件时使用它。 |
| `revision_no` | integer | 同一逻辑文档内从 1 开始递增的修订号。它不是项目的总文档数。 |
| `job_id` | string | 后台文字层解析任务 ID。用 GET /api/v1/jobs/{job_id} 查询处理状态。 |
| `sha256` | string | 上传原始 PDF 字节的 SHA-256，用于验证原件一致性；不是文字内容摘要。 |
| `reused` | boolean | true：上传新修订时发现同一文档已有完全相同的文件，复用旧修订和任务。幂等键重放返回原响应，reused 也保持原值，因此 false 不代表这次一定新增记录。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "document_id": "22222222-2222-4222-8222-222222222222",
  "revision_id": "33333333-3333-4333-8333-333333333333",
  "revision_no": 1,
  "job_id": "44444444-4444-4444-8444-444444444444",
  "sha256": "e62549d0c0326992b008c73ebdc6e14934e485b1adbdd6a1a79aee3ab9f5c4f6",
  "reused": false
}
```

## 9. 查看一份文档的全部历史修订

`GET /api/v1/documents/{document_id}/revisions`

**用途**：查看一份逻辑文档有哪些历史 PDF 版本，确认每个版本的修订号、文件 hash 和处理状态。

**返回**：200，按 revision_no 从小到大排列的数组。字段 id 是 revision_id，不是 document_id。

**状态**：NEEDS_REVIEW 表示文字层探针完成但质量待检查；不能据此判断材料是否满足招标要求。created_at 是 UTC 时间，当前无时区后缀。

**边界**：本接口不返回 job_id；日常调用请保存上传响应中的 job_id。当前列表不分页。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `document_id` | path | 是 | string | — | 逻辑文档 ID，从上传新文档接口取得；多个修订共用此 ID。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | 按 revision_no 升序返回；每条 id 都是文件修订 ID。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 不可变修订 ID，可作为下载原件接口的 revision_id。 |
| `revision_no` | integer | 文档内修订号，按此字段升序返回。 |
| `sha256` | string | 该修订原始 PDF 字节的 SHA-256。 |
| `status` | string | 文件处理状态：UPLOADED 已接收；PARSING 处理中；NEEDS_REVIEW 已完成文字层探针但待检查；RETRY_WAIT 等待重试；PARSE_FAILED 处理失败。 |
| `created_at` | string (date-time) | 修订登记时间，使用 UTC。当前返回值不带时区后缀，请按 UTC 解释；北京时间需加 8 小时。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "id": "33333333-3333-4333-8333-333333333333",
    "revision_no": 1,
    "sha256": "e62549d0c0326992b008c73ebdc6e14934e485b1adbdd6a1a79aee3ab9f5c4f6",
    "status": "NEEDS_REVIEW",
    "created_at": "2026-10-19T08:19:43"
  }
]
```

## 10. 查询后台解析任务状态及产物 ID

`GET /api/v1/jobs/{job_id}`

**用途**：跟踪上传后后台处理的结果。建议每 1–2 秒查询一次，收到 SUCCEEDED 或 FAILED 后停止轮询；可按网络情况放慢频率。

| status | 含义 | 调用方下一步 |
|---|---|---|
| QUEUED | 已登记，等待 Worker | 继续等待 |
| RUNNING | Worker 已领取并处理 | 继续等待 |
| RETRY_WAIT | 暂时失败，等待自动重试 | 继续等待，观察 error_code |
| SUCCEEDED | 技术处理完成 | 使用 artifact_id 查询产物 |
| FAILED | 最终失败 | 查看 error_code/error_detail，检查材料或运维原因 |

attempt 是已领取执行次数，初始 0。当前任务可能没有百分比进度，也没有公开的手动取消/重试接口。若任务长期排队，需检查 dispatcher、Redis 和 Worker。

**不要混淆**：HTTP 200 表示成功查到了任务，即使任务自身 status=FAILED。SUCCEEDED 也不是投标业务审核通过。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `job_id` | path | 是 | string | — | 后台任务 ID，使用上传响应的 job_id。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | 任务当前状态。HTTP 200 与任务自身是否成功是两回事。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 任务 ID，对应上传接口返回的 job_id。 |
| `status` | string | QUEUED 排队；RUNNING 处理中；RETRY_WAIT 等待自动重试；SUCCEEDED 本次技术处理完成；FAILED 最终失败。SUCCEEDED 不表示投标满足要求。 |
| `attempt` | integer | Worker 实际领取任务的次数。排队尚未执行时为 0，首次执行为 1；不是当前进度百分比。 |
| `artifact_id` | string / null | 成功后生成的解析产物 ID。尚未成功时通常为 null；拿到后查询解析结果和文字块。 |
| `error_code` | string / null | 最近错误代码：PDF_REJECTED 文件不可处理；PROCESSING_ERROR 处理异常；LEASE_EXPIRED Worker 租约过期。无错误或成功后为 null。 |
| `error_detail` | string / null | 可用于定位失败原因的简短信息。不会返回完整文档、密钥或服务器存储路径。 |
| `formal_review_ready` | boolean | 当前固定为 false：任务只做文字层探针，尚不具备自动审查能力；人工引用时须核对原件。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "44444444-4444-4444-8444-444444444444",
  "status": "SUCCEEDED",
  "attempt": 1,
  "artifact_id": "55555555-5555-4555-8555-555555555555",
  "error_code": null,
  "error_detail": null,
  "formal_review_ready": false
}
```

## 11. 查看解析概况、页数和质量提示

`GET /api/v1/artifacts/{artifact_id}`

**用途**：读取某个成功任务的解析概况：文件修订、页数、来源块数、解析配置和质量提示。

**前置**：从成功任务取得 artifact_id。无权限或 ID 不存在返回 404。

**当前产物**：pdfplumber-probe-v1 只处理 PDF 文字层，文字块大体按行划分；block_count 不是要求数。所有结果为 NEEDS_REVIEW、formal_review_ready=false。

**质量提示**：NO_EXTRACTABLE_TEXT 可能表示扫描件没有文字层；PAGES_NEED_ATTENTION 表示部分页待检查。即使技术任务成功，也可能没有可用文字。下一步查询 blocks，并回到原件检查。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `artifact_id` | path | 是 | string | — | 解析产物 ID，使用成功任务返回的 artifact_id。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | 文字层解析产物概况；质量状态当前仍为待检查。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 解析产物 ID。一个产物代表某个文件修订使用某套解析配置生成的结果。 |
| `revision_id` | string | 该产物来源的不可变文件修订 ID。 |
| `revision_sha256` | string | 来源 PDF 原始字节的 SHA-256，可用于核对引用版本。 |
| `parser_profile` | string | 解析配置版本。当前 pdfplumber-probe-v1 只提取文字层及坐标，不验证表格语义或扫描件 OCR。 |
| `page_count` | integer | 原 PDF 的实际页数，包含无文字层页面。 |
| `block_count` | integer | 生成的文字来源块总数。当前通常一行文字为一个块；不是要求数量或 RAG chunk 数量。 |
| `quality_status` | string | 当前固定为 NEEDS_REVIEW，表示需要检查解析质量，不是人工审查已通过。 |
| `quality_flags` | 数组<string> | 质量提示代码。PROVISIONAL_TEXT_LAYER_ONLY 仅文字层；TABLE_STRUCTURE_NOT_VALIDATED 表格未验证；OCR_NOT_PERFORMED 未做 OCR；NO_EXTRACTABLE_TEXT 没有可提取文字；PAGES_NEED_ATTENTION 有页面需人工检查。 |
| `formal_review_ready` | boolean | 当前固定为 false；产物存在不代表自动模型可判断投标满足，人工仍需核对原件。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "55555555-5555-4555-8555-555555555555",
  "revision_id": "33333333-3333-4333-8333-333333333333",
  "revision_sha256": "e62549d0c0326992b008c73ebdc6e14934e485b1adbdd6a1a79aee3ab9f5c4f6",
  "parser_profile": "pdfplumber-probe-v1",
  "page_count": 65,
  "block_count": 1806,
  "quality_status": "NEEDS_REVIEW",
  "quality_flags": [
    "PROVISIONAL_TEXT_LAYER_ONLY",
    "TABLE_STRUCTURE_NOT_VALIDATED",
    "OCR_NOT_PERFORMED"
  ],
  "formal_review_ready": false
}
```

## 12. 按页和分页条件读取文字来源块

`GET /api/v1/artifacts/{artifact_id}/blocks`

**用途**：分页读取提取的文字与位置，为人工阅读、来源核对和后续检索准备数据。

**查询参数**：page 可指定 PDF 实际页（从 1 开始）；offset 表示过滤后跳过多少条，默认 0；limit 为本次最多条数，默认 100，上限 200。

**返回**：200 和数组，按 block_id 升序。没有匹配项或超出结果范围时返回 []；并不表示产物不存在。当前无 total/next_cursor 字段，翻页时可将 offset 增加 limit，直到返回数量小于 limit。

**坐标**：bbox=[左,上,右,下]，单位 PDF point（1/72 英寸），原点在左上；不是像素。PDF 实际页序与印刷页码可能不同。

**下一步**：选定 block_id，连同 artifact_id 调用 source，取得原件地址及版本 hash。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `artifact_id` | path | 是 | string | — | 解析产物 ID，使用成功任务返回的 artifact_id。 |
| `page` | query | 否 | integer / null | — | 可选：只读 PDF 的某个实际页，从 1 开始。省略则跨页查询；超出页数时返回空数组。 |
| `offset` | query | 否 | integer | 默认=0；最小=0 | 在 page 过滤及排序后跳过的文字块数，默认 0。不是页码。 |
| `limit` | query | 否 | integer | 默认=100；最小=1；最大=200 | 本次最多返回的块数，默认 100，范围 1–200。下一批可将 offset 增加 limit。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | 文字块数组，包含原文、实际页序和 PDF 坐标；没有匹配项返回 []。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `block_id` | string | 当前产物内的块 ID，例如 p0003-b0004 为第 3 页第 4 个文字块。只能与本 artifact_id 配合使用。 |
| `page` | integer | PDF 实际页序号，从 1 开始；可能与页面印刷的页码不相同。 |
| `bbox` | 数组<number> | 文字在该 PDF 页上的矩形位置：[左、上、右、下]。单位为 PDF point（1/72 英寸），原点在页面左上角；不是屏幕像素，前端缩放时需要换算。 |
| `text` | string | 提取出的该行原文。用于阅读及来源验证，不是模型生成的回答。 |
| `text_hash` | string | 该块 text 按 UTF-8 编码计算的 SHA-256，用于检查文字是否改变。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "block_id": "p0003-b0004",
    "page": 3,
    "bbox": [
      79.4,
      159.783,
      523.025,
      170.283
    ],
    "text": "测试示例：投标文件应在约定截止时间前提交。",
    "text_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
]
```

## 13. 把某段文字定位到具体文件版本、页码和坐标

`GET /api/v1/artifacts/{artifact_id}/blocks/{block_id}/source`

**用途**：把一个文字块完整回溯到“哪份文件版本、哪一页、哪个矩形位置”，用于引用核验。

**参数关系**：artifact_id 和 block_id 必须来自同一产物；只有 block_id 无法跨产物唯一定位。

**返回**：quote 为提取原文，text_hash 为其 UTF-8 SHA-256；revision_sha256 为原 PDF 字节 hash，二者用途不同。original_url 指向这份修订的原件下载接口。

**查看原件**：下载时仍需要 X-API-Key。浏览器地址栏直接打开 original_url 不会带这个请求头，可能得到 401；可用带认证的客户端获取 PDF，再按 page/bbox 定位。

**边界**：来源存在只证明文字从哪里提取，尚不表示该文字是满足某条要求的有效证据。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `artifact_id` | path | 是 | string | — | 解析产物 ID，使用成功任务返回的 artifact_id。 |
| `block_id` | path | 是 | string | — | 当前产物内的文字块 ID，从文字块列表取得，必须与 artifact_id 配套。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | 可核对的原文引用信息，含原件下载相对地址。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `artifact_id` | string | 该来源块所属的解析产物 ID。 |
| `revision_id` | string | 该块对应的不可变原文件修订 ID。 |
| `revision_sha256` | string | 原文件 SHA-256，用于确保引用和下载原件属于同一版本。 |
| `block_id` | string | 产物内部的来源块 ID。 |
| `page` | integer | PDF 实际页序号，从 1 开始。 |
| `bbox` | 数组<number> | 文字在该 PDF 页上的矩形位置：[左、上、右、下]。单位为 PDF point（1/72 英寸），原点在页面左上角；不是屏幕像素，前端缩放时需要换算。 |
| `coordinate_system` | string | 坐标系名称：PDF point 为单位，页面左上角为原点。 |
| `quote` | string | 该来源块的完整提取原文，与文字块列表的 text 对应。 |
| `text_hash` | string | quote 的 UTF-8 SHA-256，与同一块的 text_hash 相同。 |
| `original_url` | string | 下载这个修订原 PDF 的相对接口地址。访问时仍须发送 X-API-Key；浏览器直接点开不会自动附带认证头。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "artifact_id": "55555555-5555-4555-8555-555555555555",
  "revision_id": "33333333-3333-4333-8333-333333333333",
  "revision_sha256": "e62549d0c0326992b008c73ebdc6e14934e485b1adbdd6a1a79aee3ab9f5c4f6",
  "block_id": "p0003-b0004",
  "page": 3,
  "bbox": [
    79.4,
    159.783,
    523.025,
    170.283
  ],
  "coordinate_system": "pdf_points_top_left",
  "quote": "测试示例：投标文件应在约定截止时间前提交。",
  "text_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "original_url": "/api/v1/revisions/33333333-3333-4333-8333-333333333333/original"
}
```

## 14. 预览或下载某个历史修订的原始 PDF

`GET /api/v1/revisions/{revision_id}/original`

**用途**：查看或下载指定不可变修订的原始 PDF。适合核对引用是否对应正确版本。

**返回**：200，Content-Type 为 application/pdf，内容是文件字节而非 JSON；Content-Disposition 为 inline，支持客户端预览。文件名使用 revision_id。

**前置**：需要有效 X-API-Key 和该修订所在项目的访问权限；可从上传结果或修订列表取得 revision_id。

**错误**：无权限或修订不存在返回 404；数据库有记录但存储文件缺失返回 503。下载历史修订不会自动替换成最新文件。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `revision_id` | path | 是 | string | — | 不可变文件修订 ID，从上传或修订列表取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | 原始 PDF 文件字节，不是 JSON；历史修订不会替换为最新文件。 |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |
| 503 | 依赖暂时不可用。就绪检查可能是数据库/表不可用；原件下载可能是数据库记录存在但文件缺失。 |

**成功返回是 PDF 文件字节，没有 JSON 字段。**

## 15. 从招标原文登记一条待确认要求

`POST /api/v1/projects/{project_id}/requirements`

**业务场景**：编写人读到招标文件“故障响应不得超过2小时”，把它登记为一项可核对要求。

**使用人/前置条件**：OWNER/EDITOR；先上传并解析招标或更正 PDF，取得原文块。

**处理与结果**：创建逻辑要求和第 1 版草稿，服务端回查并冻结原文/页码/坐标/hash；客户端不能伪造引文。

**下一步**：由 OWNER/REVIEWER 确认该要求，再发布到要求基线。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `title` | 是 | string | 最短字符数=1；最长字符数=200 | 要求标题，例如故障响应时限。 |
| `text` | 是 | string | 最短字符数=1；最长字符数=8000 | 可单独核对的一项招标要求，保持原意。 |
| `category` | 是 | string | 可选值=TECHNICAL, QUALIFICATION, DELIVERY, FORMAT, OTHER | 要求类别：技术、资质、交付、格式或其他。 |
| `priority` | 是 | string | 可选值=MANDATORY, SCORING, GENERAL | 重要性，须按招标文件定义人工确认，不能仅凭符号猜测。 |
| `sources` | 是 | 数组<object> | 最少项数=1；最多项数=20 | 至少一个本项目招标/更正文件的原文位置；服务端保存完整来源快照。 |

```json
{
  "title": "故障响应时限",
  "text": "故障响应时间不得超过2小时。",
  "category": "TECHNICAL",
  "priority": "MANDATORY",
  "sources": [
    {
      "artifact_id": "示例",
      "block_id": "示例"
    }
  ]
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 201 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `requirement_id` | string | 逻辑要求 ID。 |
| `revision_id` | string | 该要求不可变修订 ID。正文修改会创建新 ID。 |
| `revision_no` | integer | 该逻辑要求内递增的修订号。 |
| `title` | string | 要求标题。 |
| `text` | string | 本修订的完整要求正文。 |
| `category` | string | 要求类别。 |
| `priority` | string | 人工标定的重要性。 |
| `status` | string | DRAFT 待确认；CONFIRMED 已确认可纳入基线。确认不等于投标响应满足。 |
| `sources` | 数组<object> | 要求出处的不可变引用快照。 |
| `created_by` | string | 创建本修订的用户 ID。 |
| `confirmed_by` | string / null | 确认人 ID；草稿为 null。 |
| `created_at` | string (date-time) | UTC 创建时间，当前无时区后缀。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "requirement_id": "示例",
  "revision_id": "示例",
  "revision_no": 1,
  "title": "示例",
  "text": "示例",
  "category": "示例",
  "priority": "示例",
  "status": "示例",
  "sources": [
    {
      "artifact_id": "示例",
      "block_id": "示例",
      "revision_id": "示例",
      "document_id": "示例",
      "document_kind": "示例",
      "revision_sha256": "示例",
      "page": 1,
      "bbox": [
        79.4,
        159.783,
        523.025,
        170.283
      ],
      "quote": "示例",
      "text_hash": "示例",
      "submission_role": "示例"
    }
  ],
  "created_by": "示例",
  "confirmed_by": "示例",
  "created_at": "2026-10-19T09:00:00"
}
```

## 16. 查看全部要求的最新草稿或确认版

`GET /api/v1/projects/{project_id}/requirements`

**业务场景**：负责人检查哪些招标要求已经整理、哪些仍待确认。

**使用人/前置条件**：任意项目成员。

**处理与结果**：每个逻辑要求只返回最新修订，包含来源和确认状态；最新草稿可能尚未纳入当前审查基线。

**下一步**：需要知道实际审查的是哪版时，查询基线；需要修改时，携带这里的 revision_no。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `requirement_id` | string | 逻辑要求 ID。 |
| `revision_id` | string | 该要求不可变修订 ID。正文修改会创建新 ID。 |
| `revision_no` | integer | 该逻辑要求内递增的修订号。 |
| `title` | string | 要求标题。 |
| `text` | string | 本修订的完整要求正文。 |
| `category` | string | 要求类别。 |
| `priority` | string | 人工标定的重要性。 |
| `status` | string | DRAFT 待确认；CONFIRMED 已确认可纳入基线。确认不等于投标响应满足。 |
| `sources` | 数组<object> | 要求出处的不可变引用快照。 |
| `created_by` | string | 创建本修订的用户 ID。 |
| `confirmed_by` | string / null | 确认人 ID；草稿为 null。 |
| `created_at` | string (date-time) | UTC 创建时间，当前无时区后缀。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "requirement_id": "示例",
    "revision_id": "示例",
    "revision_no": 1,
    "title": "示例",
    "text": "示例",
    "category": "示例",
    "priority": "示例",
    "status": "示例",
    "sources": [
      {
        "artifact_id": "示例",
        "block_id": "示例",
        "revision_id": "示例",
        "document_id": "示例",
        "document_kind": "示例",
        "revision_sha256": "示例",
        "page": 1,
        "bbox": [
          79.4,
          159.783,
          523.025,
          170.283
        ],
        "quote": "示例",
        "text_hash": "示例",
        "submission_role": "示例"
      }
    ],
    "created_by": "示例",
    "confirmed_by": "示例",
    "created_at": "2026-10-19T09:00:00"
  }
]
```

## 17. 因更正或录入错误新增要求修订

`POST /api/v1/projects/{project_id}/requirements/{requirement_id}/revisions`

**业务场景**：招标更正或人工录入错误需要修改要求，但历史审查依据不能消失。

**使用人/前置条件**：OWNER/EDITOR；携带所见最新 expected_revision_no。

**处理与结果**：创建新的 DRAFT 修订；旧确认、旧基线及旧结论均保留。并发修改返回 409。当前报告会提示未发布的要求变化。

**下一步**：重新确认要求并发布新基线，旧审查决定和已验收整改会显示需重新核对。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `requirement_id` | path | 是 | string | — | 逻辑要求 ID。多次修订仍属于同一要求。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `title` | 是 | string | 最短字符数=1；最长字符数=200 | 要求标题，例如故障响应时限。 |
| `text` | 是 | string | 最短字符数=1；最长字符数=8000 | 可单独核对的一项招标要求，保持原意。 |
| `category` | 是 | string | 可选值=TECHNICAL, QUALIFICATION, DELIVERY, FORMAT, OTHER | 要求类别：技术、资质、交付、格式或其他。 |
| `priority` | 是 | string | 可选值=MANDATORY, SCORING, GENERAL | 重要性，须按招标文件定义人工确认，不能仅凭符号猜测。 |
| `sources` | 是 | 数组<object> | 最少项数=1；最多项数=20 | 至少一个本项目招标/更正文件的原文位置；服务端保存完整来源快照。 |
| `expected_revision_no` | 是 | integer | 最小=1.0 | 当前最新修订号。与数据库不一致返回 409，防止覆盖其他人的修改。 |

```json
{
  "title": "故障响应时限",
  "text": "故障响应时间不得超过2小时。",
  "category": "TECHNICAL",
  "priority": "MANDATORY",
  "sources": [
    {
      "artifact_id": "示例",
      "block_id": "示例"
    }
  ],
  "expected_revision_no": 1
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 201 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `requirement_id` | string | 逻辑要求 ID。 |
| `revision_id` | string | 该要求不可变修订 ID。正文修改会创建新 ID。 |
| `revision_no` | integer | 该逻辑要求内递增的修订号。 |
| `title` | string | 要求标题。 |
| `text` | string | 本修订的完整要求正文。 |
| `category` | string | 要求类别。 |
| `priority` | string | 人工标定的重要性。 |
| `status` | string | DRAFT 待确认；CONFIRMED 已确认可纳入基线。确认不等于投标响应满足。 |
| `sources` | 数组<object> | 要求出处的不可变引用快照。 |
| `created_by` | string | 创建本修订的用户 ID。 |
| `confirmed_by` | string / null | 确认人 ID；草稿为 null。 |
| `created_at` | string (date-time) | UTC 创建时间，当前无时区后缀。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "requirement_id": "示例",
  "revision_id": "示例",
  "revision_no": 1,
  "title": "示例",
  "text": "示例",
  "category": "示例",
  "priority": "示例",
  "status": "示例",
  "sources": [
    {
      "artifact_id": "示例",
      "block_id": "示例",
      "revision_id": "示例",
      "document_id": "示例",
      "document_kind": "示例",
      "revision_sha256": "示例",
      "page": 1,
      "bbox": [
        79.4,
        159.783,
        523.025,
        170.283
      ],
      "quote": "示例",
      "text_hash": "示例",
      "submission_role": "示例"
    }
  ],
  "created_by": "示例",
  "confirmed_by": "示例",
  "created_at": "2026-10-19T09:00:00"
}
```

## 18. 追溯一条要求的全部历史修订

`GET /api/v1/projects/{project_id}/requirements/{requirement_id}/revisions`

**业务场景**：更正公告改变了响应时限，需要解释原来为什么按旧要求审查。

**使用人/前置条件**：任意项目成员。

**处理与结果**：按修订号返回正文、原始来源和确认人；旧基线和问题仍引用旧修订，不会被新正文覆盖。

**下一步**：修改要求使用新增修订接口；新修订经确认并重新发布基线后才成为当前审查依据。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `requirement_id` | path | 是 | string | — | 逻辑要求 ID。多次修订仍属于同一要求。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `requirement_id` | string | 逻辑要求 ID。 |
| `revision_id` | string | 该要求不可变修订 ID。正文修改会创建新 ID。 |
| `revision_no` | integer | 该逻辑要求内递增的修订号。 |
| `title` | string | 要求标题。 |
| `text` | string | 本修订的完整要求正文。 |
| `category` | string | 要求类别。 |
| `priority` | string | 人工标定的重要性。 |
| `status` | string | DRAFT 待确认；CONFIRMED 已确认可纳入基线。确认不等于投标响应满足。 |
| `sources` | 数组<object> | 要求出处的不可变引用快照。 |
| `created_by` | string | 创建本修订的用户 ID。 |
| `confirmed_by` | string / null | 确认人 ID；草稿为 null。 |
| `created_at` | string (date-time) | UTC 创建时间，当前无时区后缀。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "requirement_id": "示例",
    "revision_id": "示例",
    "revision_no": 1,
    "title": "示例",
    "text": "示例",
    "category": "示例",
    "priority": "示例",
    "status": "示例",
    "sources": [
      {
        "artifact_id": "示例",
        "block_id": "示例",
        "revision_id": "示例",
        "document_id": "示例",
        "document_kind": "示例",
        "revision_sha256": "示例",
        "page": 1,
        "bbox": [
          79.4,
          159.783,
          523.025,
          170.283
        ],
        "quote": "示例",
        "text_hash": "示例",
        "submission_role": "示例"
      }
    ],
    "created_by": "示例",
    "confirmed_by": "示例",
    "created_at": "2026-10-19T09:00:00"
  }
]
```

## 19. 人工确认最新要求正文及出处

`POST /api/v1/projects/{project_id}/requirements/{requirement_id}/confirm`

**业务场景**：审查人核对录入的“2小时”是否准确，有没有漏掉适用范围或例外。

**使用人/前置条件**：OWNER/REVIEWER；确认的是当前最新 revision_no。

**处理与结果**：将最新 DRAFT 标为 CONFIRMED 并记录确认人；仅表示招标要求录入正确，不表示投标响应满足。

**下一步**：所有要求最新修订均确认后发布基线；确认本身不会悄悄更换正在审查的版本。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `requirement_id` | path | 是 | string | — | 逻辑要求 ID。多次修订仍属于同一要求。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `expected_revision_no` | 是 | integer | 最小=1.0 | 本次确认的最新要求修订号；只能确认当前最新草稿。 |

```json
{
  "expected_revision_no": 1
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `requirement_id` | string | 逻辑要求 ID。 |
| `revision_id` | string | 该要求不可变修订 ID。正文修改会创建新 ID。 |
| `revision_no` | integer | 该逻辑要求内递增的修订号。 |
| `title` | string | 要求标题。 |
| `text` | string | 本修订的完整要求正文。 |
| `category` | string | 要求类别。 |
| `priority` | string | 人工标定的重要性。 |
| `status` | string | DRAFT 待确认；CONFIRMED 已确认可纳入基线。确认不等于投标响应满足。 |
| `sources` | 数组<object> | 要求出处的不可变引用快照。 |
| `created_by` | string | 创建本修订的用户 ID。 |
| `confirmed_by` | string / null | 确认人 ID；草稿为 null。 |
| `created_at` | string (date-time) | UTC 创建时间，当前无时区后缀。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "requirement_id": "示例",
  "revision_id": "示例",
  "revision_no": 1,
  "title": "示例",
  "text": "示例",
  "category": "示例",
  "priority": "示例",
  "status": "示例",
  "sources": [
    {
      "artifact_id": "示例",
      "block_id": "示例",
      "revision_id": "示例",
      "document_id": "示例",
      "document_kind": "示例",
      "revision_sha256": "示例",
      "page": 1,
      "bbox": [
        79.4,
        159.783,
        523.025,
        170.283
      ],
      "quote": "示例",
      "text_hash": "示例",
      "submission_role": "示例"
    }
  ],
  "created_by": "示例",
  "confirmed_by": "示例",
  "created_at": "2026-10-19T09:00:00"
}
```

## 20. 发布本次审查采用的不可变要求基线

`POST /api/v1/projects/{project_id}/baselines`

**业务场景**：审查启动前，团队统一“这次到底按哪版招标要求检查”。

**使用人/前置条件**：OWNER/REVIEWER；全部最新要求已确认，携带工作台 epoch 和上一基线 ID。

**处理与结果**：要求 ID 列表必须完整且不重复；冻结全部最新确认版，增加 review_epoch。旧基线和结论保留，但旧决定不会继续冒充当前结果。

**下一步**：选择正式材料集，然后登记问题或逐项作出人工审核决定。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `name` | 否 | string | 默认=要求基线；最长字符数=200 | 基线名称，例如首次确认版。 |
| `expected_epoch` | 是 | integer | 最小=0.0 | 工作台当前 review_epoch；版本变化后须刷新。 |
| `expected_current_baseline_id` | 否 | string / null | — | 预期上一基线 ID；首次发布为 null。 |
| `requirement_revision_ids` | 是 | 数组<string> | 最少项数=1；最多项数=1000 | 当前全部要求的最新已确认修订 ID，不能遗漏、重复或包含草稿。 |

```json
{
  "name": "要求基线",
  "expected_epoch": 1,
  "expected_current_baseline_id": "示例",
  "requirement_revision_ids": [
    "示例"
  ]
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 201 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 发布后的不可变基线 ID。 |
| `project_id` | string | 所属项目 ID。 |
| `version` | integer | 项目内基线版本号。 |
| `name` | string | 基线名称。 |
| `parent_id` | string / null | 上一基线 ID，首版为 null。 |
| `requirements` | 数组<object> | 基线冻结的全部要求修订及来源。 |
| `created_by` | string | 发布人 ID。 |
| `created_at` | string (date-time) | UTC 发布时间。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "示例",
  "project_id": "示例",
  "version": 1,
  "name": "示例",
  "parent_id": "示例",
  "requirements": [
    {
      "requirement_id": "示例",
      "revision_id": "示例",
      "revision_no": 1,
      "title": "示例",
      "text": "示例",
      "category": "示例",
      "priority": "示例",
      "status": "示例",
      "sources": [
        {
          "artifact_id": "示例",
          "block_id": "示例",
          "revision_id": "示例",
          "document_id": "示例",
          "document_kind": "示例",
          "revision_sha256": "示例",
          "page": 1,
          "bbox": [
            79.4,
            159.783,
            523.025,
            170.283
          ],
          "quote": "示例",
          "text_hash": "示例",
          "submission_role": "示例"
        }
      ],
      "created_by": "示例",
      "confirmed_by": "示例",
      "created_at": "2026-10-19T09:00:00"
    }
  ],
  "created_by": "示例",
  "created_at": "2026-10-19T09:00:00"
}
```

## 21. 查看历次基线及各自冻结的要求

`GET /api/v1/projects/{project_id}/baselines`

**业务场景**：复盘一个旧问题时，需要还原当时采用的招标要求，而不是最新草稿。

**使用人/前置条件**：任意项目成员。

**处理与结果**：按版本递增返回基线、父基线和完整要求来源；这些内容不会被后续编辑替换。当前基线 ID 从工作台取得。

**下一步**：对照问题中的 baseline_id 和 requirement_revision_id 还原当时依据。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 发布后的不可变基线 ID。 |
| `project_id` | string | 所属项目 ID。 |
| `version` | integer | 项目内基线版本号。 |
| `name` | string | 基线名称。 |
| `parent_id` | string / null | 上一基线 ID，首版为 null。 |
| `requirements` | 数组<object> | 基线冻结的全部要求修订及来源。 |
| `created_by` | string | 发布人 ID。 |
| `created_at` | string (date-time) | UTC 发布时间。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "id": "示例",
    "project_id": "示例",
    "version": 1,
    "name": "示例",
    "parent_id": "示例",
    "requirements": [
      {
        "requirement_id": "示例",
        "revision_id": "示例",
        "revision_no": 1,
        "title": "示例",
        "text": "示例",
        "category": "示例",
        "priority": "示例",
        "status": "示例",
        "sources": [
          {
            "artifact_id": "示例",
            "block_id": "示例",
            "revision_id": "示例",
            "document_id": "示例",
            "document_kind": "示例",
            "revision_sha256": "示例",
            "page": 1,
            "bbox": [
              79.4,
              159.783,
              523.025,
              170.283
            ],
            "quote": "示例",
            "text_hash": "示例",
            "submission_role": "示例"
          }
        ],
        "created_by": "示例",
        "confirmed_by": "示例",
        "created_at": "2026-10-19T09:00:00"
      }
    ],
    "created_by": "示例",
    "created_at": "2026-10-19T09:00:00"
  }
]
```

## 22. 明确选择本次正式响应文件和附件

`POST /api/v1/projects/{project_id}/material-sets`

**业务场景**：资料库里既有旧响应书、模板，又有最终版；必须确定本次检查哪一套。

**使用人/前置条件**：OWNER/EDITOR；文件已解析，携带工作台 epoch 和上一材料集 ID。

**处理与结果**：冻结修订、hash、解析配置及提交角色；至少一份正式 RESPONSE，同一逻辑文档只能选一个版本。发布会增加 epoch，旧结论需重核。

**下一步**：审查和整改引用本材料集的原文；REFERENCE 只能辅助阅读，不能证明正式响应已满足。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `name` | 否 | string | 默认=正式响应材料；最长字符数=200 | 本套材料的名称。 |
| `expected_epoch` | 是 | integer | 最小=0.0 | 工作台当前 review_epoch。 |
| `expected_current_material_set_id` | 否 | string / null | — | 预期当前材料集 ID；首次为 null。 |
| `items` | 是 | 数组<object> | 最少项数=1；最多项数=200 | 显式选择文件和角色；至少一份 FORMAL_RESPONSE，不能自动选最后上传的文件。 |

```json
{
  "name": "正式响应材料",
  "expected_epoch": 1,
  "expected_current_material_set_id": "示例",
  "items": [
    {
      "artifact_id": "示例",
      "submission_role": "FORMAL_RESPONSE"
    }
  ]
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 201 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 不可变材料集 ID。 |
| `project_id` | string | 项目 ID。 |
| `version` | integer | 项目内材料集版本号。 |
| `name` | string | 材料集名称。 |
| `items` | 数组<object> | 冻结的文件修订、解析配置和提交角色。 |
| `created_by` | string | 发布人 ID。 |
| `created_at` | string (date-time) | UTC 发布时间。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "示例",
  "project_id": "示例",
  "version": 1,
  "name": "示例",
  "items": [
    {
      "artifact_id": "示例",
      "submission_role": "FORMAL_RESPONSE",
      "revision_id": "示例",
      "document_id": "示例",
      "title": "示例",
      "document_kind": "示例",
      "sha256": "示例",
      "parser_profile": "示例"
    }
  ],
  "created_by": "示例",
  "created_at": "2026-10-19T09:00:00"
}
```

## 23. 追溯历次审查使用的正式材料快照

`GET /api/v1/projects/{project_id}/material-sets`

**业务场景**：复核人需要确认整改提交引用的是最终响应书，而不是旧模板或事后覆盖的文件。

**使用人/前置条件**：任意项目成员。

**处理与结果**：按版本递增返回各套材料的文件修订、原件 hash 和角色。上传新文件不会自动替换现有材料集，必须显式发布。

**下一步**：核对任务 submission.material_set_id；如果与工作台当前值不同，重新提交整改再复核。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 不可变材料集 ID。 |
| `project_id` | string | 项目 ID。 |
| `version` | integer | 项目内材料集版本号。 |
| `name` | string | 材料集名称。 |
| `items` | 数组<object> | 冻结的文件修订、解析配置和提交角色。 |
| `created_by` | string | 发布人 ID。 |
| `created_at` | string (date-time) | UTC 发布时间。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "id": "示例",
    "project_id": "示例",
    "version": 1,
    "name": "示例",
    "items": [
      {
        "artifact_id": "示例",
        "submission_role": "FORMAL_RESPONSE",
        "revision_id": "示例",
        "document_id": "示例",
        "title": "示例",
        "document_kind": "示例",
        "sha256": "示例",
        "parser_profile": "示例"
      }
    ],
    "created_by": "示例",
    "created_at": "2026-10-19T09:00:00"
  }
]
```

## 24. 登记一条审查问题并指派整改任务

`POST /api/v1/projects/{project_id}/issues`

**业务场景**：审查人发现招标要求2小时，正式响应书却写4小时，需要明确问题及责任人。

**使用人/前置条件**：OWNER/REVIEWER；已发布当前基线和材料集，负责人是本项目 OWNER/EDITOR。

**处理与结果**：冻结当时要求和证据，创建一条问题及唯一 TODO 任务。冲突必须有正式材料原文；缺失问题可无引文，但须说明核对范围。

**下一步**：负责人查看任务，START 后修改文件，再发布新版材料集并 SUBMIT 整改。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `expected_epoch` | 是 | integer | 最小=0.0 | 当前工作台 epoch，保证问题登记在所见的基线和材料版本上。 |
| `requirement_revision_id` | 是 | string | — | 当前基线中的要求修订 ID。 |
| `title` | 是 | string | 最短字符数=1；最长字符数=200 | 问题标题。 |
| `description` | 是 | string | 最短字符数=1；最长字符数=8000 | 人工核对依据，例如要求2小时而响应为4小时。 |
| `kind` | 是 | string | 可选值=CONFLICT, MISSING_RESPONSE, MISSING_EVIDENCE, OTHER | 冲突、缺少响应、缺少证明或其他。 |
| `severity` | 是 | string | 可选值=HIGH, MEDIUM, LOW | 人工标记的问题优先级。 |
| `assignee_id` | 是 | string | — | 整改负责人 ID，必须是本项目 OWNER 或 EDITOR。 |
| `due_date` | 否 | string (date) / null | — | 可选整改期限，格式 YYYY-MM-DD。 |
| `evidence` | 否 | 数组<object> | 最多项数=20 | 响应证据。CONFLICT 必须附至少一处正式材料原文；缺失问题可为空并在描述中说明核对范围。 |

```json
{
  "expected_epoch": 1,
  "requirement_revision_id": "示例",
  "title": "响应时限与招标要求冲突",
  "description": "示例",
  "kind": "CONFLICT",
  "severity": "HIGH",
  "assignee_id": "示例",
  "due_date": "2026-10-19",
  "evidence": [
    {
      "artifact_id": "示例",
      "block_id": "示例"
    }
  ]
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 201 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 人工登记的问题 ID。 |
| `requirement_id` | string | 问题对应的逻辑要求。 |
| `requirement_revision_id` | string | 登记问题时的要求修订，历史不覆盖。 |
| `baseline_id` | string | 登记问题时的基线。 |
| `material_set_id` | string | 登记问题时的材料集。 |
| `epoch` | integer | 登记时 epoch。 |
| `title` | string | 问题标题。 |
| `description` | string | 人工核对的依据和缺口。 |
| `kind` | string | 问题类型。 |
| `severity` | string | 问题优先级。 |
| `evidence` | 数组<object> | 登记时响应材料的来源。 |
| `status` | string | OPEN 待整改；RESOLVED 当前版本已复核验收；NEEDS_RECHECK 旧验收已过期。 |
| `freshness` | string | 原始问题是否仍是当前输入；旧问题历史可为 STALE，但整改可在新版本完成。 |
| `task` | object | 对应的整改任务，一条问题只建一条任务，补件后继续使用。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "示例",
  "requirement_id": "示例",
  "requirement_revision_id": "示例",
  "baseline_id": "示例",
  "material_set_id": "示例",
  "epoch": 1,
  "title": "示例",
  "description": "示例",
  "kind": "示例",
  "severity": "示例",
  "evidence": [
    {
      "artifact_id": "示例",
      "block_id": "示例",
      "revision_id": "示例",
      "document_id": "示例",
      "document_kind": "示例",
      "revision_sha256": "示例",
      "page": 1,
      "bbox": [
        79.4,
        159.783,
        523.025,
        170.283
      ],
      "quote": "示例",
      "text_hash": "示例",
      "submission_role": "示例"
    }
  ],
  "status": "示例",
  "freshness": "示例",
  "task": {
    "id": "示例",
    "issue_id": "示例",
    "requirement_id": "示例",
    "assignee_id": "示例",
    "due_date": "2026-10-19",
    "status": "示例",
    "effective_status": "示例",
    "freshness": "示例",
    "version": 1,
    "current_submission": {
      "id": "示例",
      "task_version": 1,
      "requirement_revision_id": "示例",
      "baseline_id": "示例",
      "material_set_id": "示例",
      "epoch": 1,
      "note": "示例",
      "evidence": [
        {
          "artifact_id": "示例",
          "block_id": "示例",
          "revision_id": "示例",
          "document_id": "示例",
          "document_kind": "示例",
          "revision_sha256": "示例",
          "page": 1,
          "bbox": [
            79.4,
            159.783,
            523.025,
            170.283
          ],
          "quote": "示例",
          "text_hash": "示例",
          "submission_role": "示例"
        }
      ],
      "submitted_by": "示例",
      "created_at": "2026-10-19T09:00:00"
    },
    "decisions": [
      {
        "id": "示例",
        "submission_id": "示例",
        "decision": "示例",
        "note": "示例",
        "decided_by": "示例",
        "task_version": 1,
        "created_at": "2026-10-19T09:00:00"
      }
    ]
  }
}
```

## 25. 查看问题、整改进展及旧结论是否过期

`GET /api/v1/projects/{project_id}/issues`

**业务场景**：项目负责人跟踪仍未解决的问题，审查人回看原始冲突依据。

**使用人/前置条件**：任意项目成员。

**处理与结果**：返回全部历史问题和对应任务。旧问题原文保持原样；整改可引用新材料。RESOLVED 只用于当前输入已验收的结果，旧验收变为 NEEDS_RECHECK。

**下一步**：根据任务负责人和 effective_status 推动整改；完整覆盖率查看 review-report。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 人工登记的问题 ID。 |
| `requirement_id` | string | 问题对应的逻辑要求。 |
| `requirement_revision_id` | string | 登记问题时的要求修订，历史不覆盖。 |
| `baseline_id` | string | 登记问题时的基线。 |
| `material_set_id` | string | 登记问题时的材料集。 |
| `epoch` | integer | 登记时 epoch。 |
| `title` | string | 问题标题。 |
| `description` | string | 人工核对的依据和缺口。 |
| `kind` | string | 问题类型。 |
| `severity` | string | 问题优先级。 |
| `evidence` | 数组<object> | 登记时响应材料的来源。 |
| `status` | string | OPEN 待整改；RESOLVED 当前版本已复核验收；NEEDS_RECHECK 旧验收已过期。 |
| `freshness` | string | 原始问题是否仍是当前输入；旧问题历史可为 STALE，但整改可在新版本完成。 |
| `task` | object | 对应的整改任务，一条问题只建一条任务，补件后继续使用。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "id": "示例",
    "requirement_id": "示例",
    "requirement_revision_id": "示例",
    "baseline_id": "示例",
    "material_set_id": "示例",
    "epoch": 1,
    "title": "示例",
    "description": "示例",
    "kind": "示例",
    "severity": "示例",
    "evidence": [
      {
        "artifact_id": "示例",
        "block_id": "示例",
        "revision_id": "示例",
        "document_id": "示例",
        "document_kind": "示例",
        "revision_sha256": "示例",
        "page": 1,
        "bbox": [
          79.4,
          159.783,
          523.025,
          170.283
        ],
        "quote": "示例",
        "text_hash": "示例",
        "submission_role": "示例"
      }
    ],
    "status": "示例",
    "freshness": "示例",
    "task": {
      "id": "示例",
      "issue_id": "示例",
      "requirement_id": "示例",
      "assignee_id": "示例",
      "due_date": "2026-10-19",
      "status": "示例",
      "effective_status": "示例",
      "freshness": "示例",
      "version": 1,
      "current_submission": {
        "id": "示例",
        "task_version": 1,
        "requirement_revision_id": "示例",
        "baseline_id": "示例",
        "material_set_id": "示例",
        "epoch": 1,
        "note": "示例",
        "evidence": [
          {
            "artifact_id": "示例",
            "block_id": "示例",
            "revision_id": "示例",
            "document_id": "示例",
            "document_kind": "示例",
            "revision_sha256": "示例",
            "page": 1,
            "bbox": [
              79.4,
              159.783,
              523.025,
              170.283
            ],
            "quote": "示例",
            "text_hash": "示例",
            "submission_role": "示例"
          }
        ],
        "submitted_by": "示例",
        "created_at": "2026-10-19T09:00:00"
      },
      "decisions": [
        {
          "id": "示例",
          "submission_id": "示例",
          "decision": "示例",
          "note": "示例",
          "decided_by": "示例",
          "task_version": 1,
          "created_at": "2026-10-19T09:00:00"
        }
      ]
    }
  }
]
```

## 26. 查看本项目整改待办与复核记录

`GET /api/v1/projects/{project_id}/tasks`

**业务场景**：编写人查看自己负责哪些问题，复核人查看哪些整改已经提交。

**使用人/前置条件**：任意项目成员；当前首版返回项目全部任务，由 assignee_id 识别负责人。

**处理与结果**：返回状态、version、最近提交和全部复核决定。effective_status 反映当前输入是否变化，持久化历史状态不被删除。

**下一步**：负责人使用 version 发起 START/SUBMIT，复核人使用当前 submission.id 和 version 作出决定。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 整改任务 ID。 |
| `issue_id` | string | 对应的审查问题 ID。 |
| `requirement_id` | string | 逻辑要求 ID，新修订仍沿用此关系。 |
| `assignee_id` | string | 整改负责人。 |
| `due_date` | string (date) / null | 整改期限。 |
| `status` | string | 持久化状态：TODO/IN_PROGRESS/SUBMITTED/ACCEPTED/RETURNED。 |
| `effective_status` | string | 当前业务状态；已提交或已验收的结果遇到输入版本变化时为 NEEDS_RECHECK，历史状态保留。 |
| `freshness` | string | CURRENT 或 STALE，相对于项目当前基线、材料集与 epoch。 |
| `version` | integer | 乐观锁版本，执行下一个动作时作为 expected_version。 |
| `current_submission` | object / null | 最近一次整改提交；尚未提交为 null。 |
| `decisions` | 数组<object> | 此任务全部人工复核记录，按任务版本递增。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "id": "示例",
    "issue_id": "示例",
    "requirement_id": "示例",
    "assignee_id": "示例",
    "due_date": "2026-10-19",
    "status": "示例",
    "effective_status": "示例",
    "freshness": "示例",
    "version": 1,
    "current_submission": {
      "id": "示例",
      "task_version": 1,
      "requirement_revision_id": "示例",
      "baseline_id": "示例",
      "material_set_id": "示例",
      "epoch": 1,
      "note": "示例",
      "evidence": [
        {
          "artifact_id": "示例",
          "block_id": "示例",
          "revision_id": "示例",
          "document_id": "示例",
          "document_kind": "示例",
          "revision_sha256": "示例",
          "page": 1,
          "bbox": [
            79.4,
            159.783,
            523.025,
            170.283
          ],
          "quote": "示例",
          "text_hash": "示例",
          "submission_role": "示例"
        }
      ],
      "submitted_by": "示例",
      "created_at": "2026-10-19T09:00:00"
    },
    "decisions": [
      {
        "id": "示例",
        "submission_id": "示例",
        "decision": "示例",
        "note": "示例",
        "decided_by": "示例",
        "task_version": 1,
        "created_at": "2026-10-19T09:00:00"
      }
    ]
  }
]
```

## 27. 负责人开始整改或提交修改后的正式证据

`POST /api/v1/projects/{project_id}/tasks/{task_id}/transitions`

**业务场景**：编写人接受“4小时改为2小时”的整改任务，完成修改后交给别人复核。

**使用人/前置条件**：仅任务负责人且仍有 OWNER/EDITOR 角色；带 expected_version 和 expected_epoch。

**处理与结果**：START 将待办/退回任务转为处理中；SUBMIT 必须有说明和当前正式材料引文。过期的已提交/已验收任务也要 START 后重新提交。

**下一步**：另一位 OWNER/REVIEWER 对 current_submission.id 作出 ACCEPT/RETURN；提交本身不等于问题解决。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `task_id` | path | 是 | string | — | 整改任务 ID，从登记问题或任务列表取得。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `action` | 是 | string | 可选值=START, SUBMIT | START 领取开始/退回后重做；SUBMIT 提交整改。只允许任务负责人操作。 |
| `expected_version` | 是 | integer | 最小=1.0 | 任务当前 version，防止并发重复状态变更。 |
| `expected_epoch` | 是 | integer | 最小=0.0 | 工作台当前 review_epoch；材料或要求基线变化后必须刷新核对再操作。 |
| `note` | 否 | string | 默认=；最长字符数=8000 | SUBMIT 必须说明修改内容；START 可省略。 |
| `evidence` | 否 | 数组<object> | 最多项数=20 | SUBMIT 必须引用当前正式材料集中的修改后原文，不能引用仅参考材料。 |

```json
{
  "action": "START",
  "expected_version": 1,
  "expected_epoch": 1,
  "note": "",
  "evidence": [
    {
      "artifact_id": "示例",
      "block_id": "示例"
    }
  ]
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 整改任务 ID。 |
| `issue_id` | string | 对应的审查问题 ID。 |
| `requirement_id` | string | 逻辑要求 ID，新修订仍沿用此关系。 |
| `assignee_id` | string | 整改负责人。 |
| `due_date` | string (date) / null | 整改期限。 |
| `status` | string | 持久化状态：TODO/IN_PROGRESS/SUBMITTED/ACCEPTED/RETURNED。 |
| `effective_status` | string | 当前业务状态；已提交或已验收的结果遇到输入版本变化时为 NEEDS_RECHECK，历史状态保留。 |
| `freshness` | string | CURRENT 或 STALE，相对于项目当前基线、材料集与 epoch。 |
| `version` | integer | 乐观锁版本，执行下一个动作时作为 expected_version。 |
| `current_submission` | object / null | 最近一次整改提交；尚未提交为 null。 |
| `decisions` | 数组<object> | 此任务全部人工复核记录，按任务版本递增。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "示例",
  "issue_id": "示例",
  "requirement_id": "示例",
  "assignee_id": "示例",
  "due_date": "2026-10-19",
  "status": "示例",
  "effective_status": "示例",
  "freshness": "示例",
  "version": 1,
  "current_submission": {
    "id": "示例",
    "task_version": 1,
    "requirement_revision_id": "示例",
    "baseline_id": "示例",
    "material_set_id": "示例",
    "epoch": 1,
    "note": "示例",
    "evidence": [
      {
        "artifact_id": "示例",
        "block_id": "示例",
        "revision_id": "示例",
        "document_id": "示例",
        "document_kind": "示例",
        "revision_sha256": "示例",
        "page": 1,
        "bbox": [
          79.4,
          159.783,
          523.025,
          170.283
        ],
        "quote": "示例",
        "text_hash": "示例",
        "submission_role": "示例"
      }
    ],
    "submitted_by": "示例",
    "created_at": "2026-10-19T09:00:00"
  },
  "decisions": [
    {
      "id": "示例",
      "submission_id": "示例",
      "decision": "示例",
      "note": "示例",
      "decided_by": "示例",
      "task_version": 1,
      "created_at": "2026-10-19T09:00:00"
    }
  ]
}
```

## 28. 追溯任务历次整改提交及其材料依据

`GET /api/v1/projects/{project_id}/tasks/{task_id}/submissions`

**业务场景**：整改被退回或材料多次补充后，需要解释每次提交改了什么、复核的是哪一版。

**使用人/前置条件**：任意项目成员。

**处理与结果**：按任务版本返回所有不可变提交，包含当时基线、材料集、原文引证、说明和提交人，不只返回最后一次。

**下一步**：将提交 ID 与任务 decisions 中的 submission_id 对照，还原退回和验收过程。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `task_id` | path | 是 | string | — | 整改任务 ID，从登记问题或任务列表取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 不可变整改提交 ID。 |
| `task_version` | integer | 提交时的任务版本。 |
| `requirement_revision_id` | string | 本次整改依据的当前要求修订。 |
| `baseline_id` | string | 提交时要求基线。 |
| `material_set_id` | string | 提交时正式材料集。 |
| `epoch` | integer | 提交时 review_epoch。输入变化后此提交需要重新确认。 |
| `note` | string | 整改说明。 |
| `evidence` | 数组<object> | 修改后正式材料的引用。 |
| `submitted_by` | string | 实际提交人 ID。 |
| `created_at` | string (date-time) | UTC 提交时间。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "id": "示例",
    "task_version": 1,
    "requirement_revision_id": "示例",
    "baseline_id": "示例",
    "material_set_id": "示例",
    "epoch": 1,
    "note": "示例",
    "evidence": [
      {
        "artifact_id": "示例",
        "block_id": "示例",
        "revision_id": "示例",
        "document_id": "示例",
        "document_kind": "示例",
        "revision_sha256": "示例",
        "page": 1,
        "bbox": [
          79.4,
          159.783,
          523.025,
          170.283
        ],
        "quote": "示例",
        "text_hash": "示例",
        "submission_role": "示例"
      }
    ],
    "submitted_by": "示例",
    "created_at": "2026-10-19T09:00:00"
  }
]
```

## 29. 由另一人复核当前整改提交，验收或退回

`POST /api/v1/projects/{project_id}/tasks/{task_id}/decisions`

**业务场景**：审查人重新打开修改后的响应书核对2小时承诺，决定是否通过整改。

**使用人/前置条件**：OWNER/REVIEWER 且不是该次整改提交人；任务必须为 SUBMITTED。

**处理与结果**：校验任务 version、submission_id 及基线/材料/epoch。输入变更拒绝旧提交验收。ACCEPT 解决当前问题，RETURN 交回负责人并保留意见。

**下一步**：问题解决后还需要逐项最终审核决定，不能把“没有未解决问题”直接当作所有要求已审查。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `task_id` | path | 是 | string | — | 整改任务 ID，从登记问题或任务列表取得。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `expected_version` | 是 | integer | 最小=1.0 | 当前任务 version。 |
| `submission_id` | 是 | string | — | 本次复核的 current_submission.id，不能误验收旧提交。 |
| `decision` | 是 | string | 可选值=ACCEPT, RETURN | ACCEPT 验收；RETURN 退回。只允许 OWNER/REVIEWER，且不能验收或退回自己提交的整改。 |
| `note` | 是 | string | 最短字符数=1；最长字符数=8000 | 复核意见，无论通过或退回都必须填写。 |

```json
{
  "expected_version": 1,
  "submission_id": "示例",
  "decision": "ACCEPT",
  "note": "示例"
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 整改任务 ID。 |
| `issue_id` | string | 对应的审查问题 ID。 |
| `requirement_id` | string | 逻辑要求 ID，新修订仍沿用此关系。 |
| `assignee_id` | string | 整改负责人。 |
| `due_date` | string (date) / null | 整改期限。 |
| `status` | string | 持久化状态：TODO/IN_PROGRESS/SUBMITTED/ACCEPTED/RETURNED。 |
| `effective_status` | string | 当前业务状态；已提交或已验收的结果遇到输入版本变化时为 NEEDS_RECHECK，历史状态保留。 |
| `freshness` | string | CURRENT 或 STALE，相对于项目当前基线、材料集与 epoch。 |
| `version` | integer | 乐观锁版本，执行下一个动作时作为 expected_version。 |
| `current_submission` | object / null | 最近一次整改提交；尚未提交为 null。 |
| `decisions` | 数组<object> | 此任务全部人工复核记录，按任务版本递增。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "示例",
  "issue_id": "示例",
  "requirement_id": "示例",
  "assignee_id": "示例",
  "due_date": "2026-10-19",
  "status": "示例",
  "effective_status": "示例",
  "freshness": "示例",
  "version": 1,
  "current_submission": {
    "id": "示例",
    "task_version": 1,
    "requirement_revision_id": "示例",
    "baseline_id": "示例",
    "material_set_id": "示例",
    "epoch": 1,
    "note": "示例",
    "evidence": [
      {
        "artifact_id": "示例",
        "block_id": "示例",
        "revision_id": "示例",
        "document_id": "示例",
        "document_kind": "示例",
        "revision_sha256": "示例",
        "page": 1,
        "bbox": [
          79.4,
          159.783,
          523.025,
          170.283
        ],
        "quote": "示例",
        "text_hash": "示例",
        "submission_role": "示例"
      }
    ],
    "submitted_by": "示例",
    "created_at": "2026-10-19T09:00:00"
  },
  "decisions": [
    {
      "id": "示例",
      "submission_id": "示例",
      "decision": "示例",
      "note": "示例",
      "decided_by": "示例",
      "task_version": 1,
      "created_at": "2026-10-19T09:00:00"
    }
  ]
}
```

## 30. 对当前要求逐项记录人工最终决定

`POST /api/v1/projects/{project_id}/requirement-decisions`

**业务场景**：即便没发现问题，也必须记录这条要求是否真正检查过及检查依据。

**使用人/前置条件**：OWNER/REVIEWER；要求在当前基线内，携带当前 epoch。

**处理与结果**：确认满足须有正式材料证据且所有相关问题已由他人复核；确认有问题须先登记可整改的问题；不适用须说明理由。每次决定追加保留。

**下一步**：查询 review-report 看逐项覆盖率。新基线或新材料发布后，旧决定保留但不再计入当前覆盖率。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |
| `Idempotency-Key` | header | 是 | string | 最短字符数=16；最长字符数=128 | 本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。 |

**请求体：`application/json`**

| 字段 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|
| `expected_epoch` | 是 | integer | 最小=0.0 | 项目当前 epoch。 |
| `requirement_revision_id` | 是 | string | — | 当前基线内的要求修订。 |
| `decision` | 是 | string | 可选值=CONFIRMED_SATISFIED, CONFIRMED_ISSUE, NOT_APPLICABLE | 人工确认满足、确认有问题、确认不适用。不是模型自动结论。 |
| `note` | 是 | string | 最短字符数=1；最长字符数=8000 | 人工审核意见；不适用必须说明原因。 |
| `evidence` | 否 | 数组<object> | 最多项数=20 | 确认满足必须提供正式材料引用；其他决定可按实际情况提供。 |

```json
{
  "expected_epoch": 1,
  "requirement_revision_id": "示例",
  "decision": "CONFIRMED_SATISFIED",
  "note": "示例",
  "evidence": [
    {
      "artifact_id": "示例",
      "block_id": "示例"
    }
  ]
}
```

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 201 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 403 | 当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 409 | 幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 不可变人工审核记录 ID。 |
| `requirement_id` | string | 逻辑要求 ID。 |
| `requirement_revision_id` | string | 审核的具体要求修订。 |
| `baseline_id` | string | 对应基线。 |
| `material_set_id` | string | 对应正式材料集。 |
| `epoch` | integer | 决定适用的项目输入版本。 |
| `sequence` | integer | 该逻辑要求内递增的决定序号，不能靠同秒时间排序。 |
| `review_version` | integer | 该要求的问题代次；新增问题会递增，之前的满足决定必须重新确认。 |
| `decision` | string | 人工确认满足/有问题/不适用。 |
| `note` | string | 审核意见。 |
| `evidence` | 数组<object> | 审核依据的正式材料引用。 |
| `decided_by` | string | 审核人 ID。 |
| `created_at` | string (date-time) | UTC 审核时间。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "id": "示例",
  "requirement_id": "示例",
  "requirement_revision_id": "示例",
  "baseline_id": "示例",
  "material_set_id": "示例",
  "epoch": 1,
  "sequence": 1,
  "review_version": 1,
  "decision": "示例",
  "note": "示例",
  "evidence": [
    {
      "artifact_id": "示例",
      "block_id": "示例",
      "revision_id": "示例",
      "document_id": "示例",
      "document_kind": "示例",
      "revision_sha256": "示例",
      "page": 1,
      "bbox": [
        79.4,
        159.783,
        523.025,
        170.283
      ],
      "quote": "示例",
      "text_hash": "示例",
      "submission_role": "示例"
    }
  ],
  "decided_by": "示例",
  "created_at": "2026-10-19T09:00:00"
}
```

## 31. 查看逐项审核决定的完整历史

`GET /api/v1/projects/{project_id}/requirement-decisions`

**业务场景**：需求或材料变更后，需要追溯为什么上一轮认为满足、由谁确认、引用什么证据。

**使用人/前置条件**：任意项目成员。

**处理与结果**：返回本项目所有人工决定，同一要求按 sequence 递增；包含已过期决定，不应直接累加为当前完成数量。

**下一步**：当前有效结论及是否仍有未解决问题，以 review-report 为准；本接口用于审计和复盘。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 不可变人工审核记录 ID。 |
| `requirement_id` | string | 逻辑要求 ID。 |
| `requirement_revision_id` | string | 审核的具体要求修订。 |
| `baseline_id` | string | 对应基线。 |
| `material_set_id` | string | 对应正式材料集。 |
| `epoch` | integer | 决定适用的项目输入版本。 |
| `sequence` | integer | 该逻辑要求内递增的决定序号，不能靠同秒时间排序。 |
| `review_version` | integer | 该要求的问题代次；新增问题会递增，之前的满足决定必须重新确认。 |
| `decision` | string | 人工确认满足/有问题/不适用。 |
| `note` | string | 审核意见。 |
| `evidence` | 数组<object> | 审核依据的正式材料引用。 |
| `decided_by` | string | 审核人 ID。 |
| `created_at` | string (date-time) | UTC 审核时间。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
[
  {
    "id": "示例",
    "requirement_id": "示例",
    "requirement_revision_id": "示例",
    "baseline_id": "示例",
    "material_set_id": "示例",
    "epoch": 1,
    "sequence": 1,
    "review_version": 1,
    "decision": "示例",
    "note": "示例",
    "evidence": [
      {
        "artifact_id": "示例",
        "block_id": "示例",
        "revision_id": "示例",
        "document_id": "示例",
        "document_kind": "示例",
        "revision_sha256": "示例",
        "page": 1,
        "bbox": [
          79.4,
          159.783,
          523.025,
          170.283
        ],
        "quote": "示例",
        "text_hash": "示例",
        "submission_role": "示例"
      }
    ],
    "decided_by": "示例",
    "created_at": "2026-10-19T09:00:00"
  }
]
```

## 32. 查看本轮人工审查覆盖、未解决问题和完成状态

`GET /api/v1/projects/{project_id}/review-report`

**业务场景**：投标负责人在提交前核实是否每条要求都有人检查，是否仍有整改未复核。

**使用人/前置条件**：任意项目成员。

**处理与结果**：按当前基线/材料/epoch 汇总逐项结论，未登记问题不等于已审查。缺输入显示 NOT_READY，有未发布要求修改也不能显示完成。

**下一步**：针对 UNREVIEWED/NEEDS_REVIEW 补充人工决定，针对 ISSUES_OPEN 继续整改。本报告为人工工作流状态，不是模型合规保证。

**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。

**认证**：需要 `X-API-Key`。

**参数说明**

| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |
|---|---|---|---|---|---|
| `project_id` | path | 是 | string | — | 投标项目 ID，从创建项目接口取得。 |

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | Successful Response |
| 401 | 缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。 |
| 404 | 对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。 |
| 422 | 参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | string | 项目 ID。 |
| `baseline_id` | string / null | 报告对应的当前基线。 |
| `material_set_id` | string / null | 报告对应的当前材料集。 |
| `review_epoch` | integer | 报告读取的业务输入 epoch。 |
| `review_mode` | string | 人工审查，不包含自动 RAG/模型判断。 |
| `status` | string | NOT_READY 缺基线/材料；ISSUES_OPEN 有未解决问题；IN_REVIEW 尚有要求未确认；REVIEW_COMPLETE 本快照的人工审查已完成。 |
| `manual_review_complete` | boolean | 只有全部要求有当前人工确认且没有未解决问题时为 true；没有问题记录不等于审查完成。 |
| `pending_requirement_changes` | boolean | 有尚未纳入基线的要求修改时为 true，阻止项目显示人工审查完成。 |
| `requirement_count` | integer | 当前基线的要求数。 |
| `reviewed_count` | integer | 已在当前输入下人工确认满足/不适用且无未解决问题的要求数。 |
| `unresolved_issue_count` | integer | 当前基线逻辑要求关联的未解决问题数，包含需重审的旧验收。 |
| `requirements` | 数组<object> | 逐项人工审查覆盖和问题状态。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "project_id": "示例",
  "baseline_id": "示例",
  "material_set_id": "示例",
  "review_epoch": 1,
  "review_mode": "HUMAN",
  "status": "示例",
  "manual_review_complete": false,
  "pending_requirement_changes": false,
  "requirement_count": 1,
  "reviewed_count": 1,
  "unresolved_issue_count": 1,
  "requirements": [
    {
      "requirement_id": "示例",
      "requirement_revision_id": "示例",
      "title": "示例",
      "status": "示例",
      "unresolved_issue_count": 1,
      "current_decision": {
        "id": "示例",
        "requirement_id": "示例",
        "requirement_revision_id": "示例",
        "baseline_id": "示例",
        "material_set_id": "示例",
        "epoch": 1,
        "sequence": 1,
        "review_version": 1,
        "decision": "示例",
        "note": "示例",
        "evidence": [
          {
            "artifact_id": "示例",
            "block_id": "示例",
            "revision_id": "示例",
            "document_id": "示例",
            "document_kind": "示例",
            "revision_sha256": "示例",
            "page": 1,
            "bbox": [
              79.4,
              159.783,
              523.025,
              170.283
            ],
            "quote": "示例",
            "text_hash": "示例",
            "submission_role": "示例"
          }
        ],
        "decided_by": "示例",
        "created_at": "2026-10-19T09:00:00"
      }
    }
  ]
}
```

## 33. 检查 API 进程是否存活

`GET /health/live`

**用途**：检查 API 进程是否还能响应 HTTP，供容器或监控使用。

**前置条件**：无；不需要 API Key。返回 200 和 `status=ok` 只说明进程在运行，不检查数据库、Redis、Worker 或文件存储。

**下一步**：检查数据库与基础表是否就绪，调用 `/health/ready`。

**认证**：不需要认证。

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | API 能响应 HTTP；不代表数据库或 Worker 可用。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | ok：API 进程能够响应 HTTP 请求。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "status": "ok"
}
```

## 34. 检查数据库和基础表是否就绪

`GET /health/ready`

**用途**：确认数据库可连接，并且迁移创建的用户、项目业务字段和人工审核记录表可以查询。

**返回**：200 表示这两个检查通过；503 表示数据库或表结构不可用。无需 API Key。

**边界**：它不检测 Redis、Worker 或文档解析质量；`formal_review_ready=false` 是当前功能阶段说明，不是数据库异常。

**认证**：不需要认证。

**HTTP 返回**

| 状态码 | 含义 |
|---|---|
| 200 | 数据库连接及核心表查询通过；自动模型审查尚未开放。 |
| 503 | 依赖暂时不可用。就绪检查可能是数据库/表不可用；原件下载可能是数据库记录存在但文件缺失。 |

**成功返回字段**（数组接口描述的是每一个元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | ready：数据库可连接且核心业务表可查询。 |
| `stage` | string | 当前阶段 human-review-workflow：文档工程和人工审查闭环。 |
| `formal_review_ready` | boolean | 当前固定为 false：尚未开放自动模型审查；人工业务已可用。这与数据库是否就绪无关。 |

**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。

```json
{
  "status": "ready",
  "stage": "human-review-workflow",
  "formal_review_ready": false
}
```

## 状态和常见问题速查

| 现象 | 解释与处理 |
|---|---|
| `202` 后马上查不到 artifact_id | 正常：任务仍在排队或处理中，继续查 job |
| `200` 但 job.status 是 FAILED | 查询任务成功，任务执行失败；查看 error_code 和 error_detail |
| `SUCCEEDED` 但 formal_review_ready=false | 文字层提取完成但不具备自动审查能力，人工闭环可继续并回看原件 |
| `NEEDS_REVIEW` | 当前解析结果都需要人工检查，尚未验证 OCR 和表格语义 |
| `404` | ID 错误、ID 用错类型，或当前身份没有项目权限 |
| `409` | 幂等键内容冲突，或基线/材料/epoch/任务状态变化；刷新并重新核对 |
| 下载原件链接直接打开得到 `401` | 浏览器地址栏没有发送 X-API-Key；使用带请求头的客户端下载 |
| 列表返回 `[]` | 该身份没有项目，或者页码/offset 没有匹配项；不一定是接口失败 |
| 扫描 PDF 技术任务成功，但文字块为 0 | 没有可提取的文字层；当前未执行 OCR，需检查质量提示 |

## 最小 Python 调用例子

在项目根目录、已安装 requirements.lock 的 Python 环境执行。先准备 `sample.pdf`；密钥从本地 .env 读取，代码不打印它。

```python
import time
import uuid
from pathlib import Path
import httpx
from dotenv import dotenv_values

key = dotenv_values(".env")["BID_BOOTSTRAP_API_KEY"]
with httpx.Client(base_url="http://127.0.0.1:18080",
                  headers={"X-API-Key": key}, timeout=60, trust_env=False) as client:
    response = client.post("/api/v1/projects", json={"name": "接口学习项目"})
    response.raise_for_status()
    project_id = response.json()["id"]
    request_key = str(uuid.uuid4())  # 本次上传固定一个键；网络重试时沿用
    with Path("sample.pdf").open("rb") as stream:
        response = client.post(f"/api/v1/projects/{project_id}/documents",
            headers={"Idempotency-Key": request_key},
            data={"title": "待核对招标文件", "kind": "TENDER"},
            files={"file": ("sample.pdf", stream, "application/pdf")})
    response.raise_for_status()
    job_id = response.json()["job_id"]
    for _ in range(180):  # 最多轮询约 6 分钟
        response = client.get(f"/api/v1/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] == "SUCCEEDED":
            break
        if job["status"] == "FAILED":
            raise RuntimeError(f"{job['error_code']}: {job['error_detail']}")
        time.sleep(2)
    else:
        raise TimeoutError("任务尚未完成，请检查后台服务")
    artifact_id = job["artifact_id"]
    response = client.get(f"/api/v1/artifacts/{artifact_id}/blocks", params={"limit": 10})
    response.raise_for_status()
    blocks = response.json()
    if blocks:
        block_id = blocks[0]["block_id"]
        response = client.get(f"/api/v1/artifacts/{artifact_id}/blocks/{block_id}/source")
        response.raise_for_status()
        source = response.json()
        print(source)
        original = client.get(source["original_url"])
        original.raise_for_status()
        Path("downloaded-original.pdf").write_bytes(original.content)
```

## 文档维护

说明来自 app/main.py、app/schemas.py、app/api_docs.py、app/business_api.py 和 app/business_schemas.py。修改后运行：

```powershell
docker compose exec api python scripts/export_api_docs.py
```

重新构建并启动 API 后，Swagger 使用最新说明。OpenAPI、中文手册以及源码包应一起更新。
