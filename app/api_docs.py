"""接口用途、前置条件和错误说明；统一展示在 OpenAPI/Swagger 中。"""
from app.schemas import ErrorResponse

API_DESCRIPTION = """
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
"""

TAGS = [
    {"name": "01 项目管理", "description": "先建项目，再上传该项目的投标材料。不同项目按成员权限隔离。"},
    {"name": "02 文档与修订", "description": "新文档建立逻辑身份；新修订保留同一身份下的新 PDF。旧文件不覆盖。"},
    {"name": "03 后台任务", "description": "上传后在这里查询排队、处理、重试和成功/失败状态。"},
    {"name": "04 解析结果", "description": "任务成功后读取解析概况和文字来源块。当前为文字层探针。"},
    {"name": "05 来源追溯", "description": "取得引用的文件版本、页码、坐标及原件，供人工核对。"},
    {"name": "06 服务状态", "description": "运维健康检查，不需要 API Key。"},
    {"name": "07 成员与工作台", "description": "建立编写、审查、只读角色，查询当前业务输入版本。"},
    {"name": "08 要求与基线", "description": "从招标原文人工登记要求，确认后冻结本轮审查依据。"},
    {"name": "09 正式响应材料", "description": "选择正式响应和附件的确切修订，区分仅供参考的资料。"},
    {"name": "10 问题与整改", "description": "登记具体问题、指派负责人、提交整改并由另一人复核。"},
    {"name": "11 人工审查结论", "description": "记录每条要求是否审核及依据，汇总当前版本的完成情况。"},
]

ERRORS = {
    401: ("缺少或无效的 API Key。点击 Authorize 填写本地密钥，或者发送 X-API-Key 请求头。", "A valid X-API-Key is required"),
    403: ("当前成员角色不能执行该动作，或尝试复核自己的整改。具体角色见各接口的使用人说明。", "Project role cannot perform this action"),
    404: ("对象不存在，或当前用户没有项目访问权限。检查 ID 和所属项目；两种情况都使用 404。", "Project not found"),
    409: ("幂等键内容冲突，或要求修订/任务状态/epoch 已变化。刷新工作台和任务并重新核对；重试沿用原键原内容，新动作换新键。", "Project inputs changed; refresh workspace and recheck the current sources"),
    413: ("上传字节数超过配置上限，默认 50 MiB（52,428,800 字节）。分拆文件或调整服务配置。", "File exceeds configured upload limit"),
    415: ("当前阶段只接收以 %PDF- 开头的 PDF 内容。改扩展名无效；DOCX 和扫描 OCR 尚未接入。", "Phase 1 accepts PDF content only"),
    422: ("参数或请求体校验失败，例如缺少必填字段、枚举值错误、分页超界、幂等键长度不符或名称为纯空白。查看 detail 中的 loc 和 msg。", None),
    503: ("依赖暂时不可用。就绪检查可能是数据库/表不可用；原件下载可能是数据库记录存在但文件缺失。", "Stored original is unavailable"),
}


def error_responses(*codes: int, examples: dict | None = None) -> dict:
    responses = {}
    for code in codes:
        description, example = ERRORS[code]
        if examples and code in examples:
            example = examples[code]
        elif example is None:
            example = [{"type": "missing", "loc": ["header", "idempotency-key"],
                        "msg": "Field required", "input": None}]
        responses[code] = {"model": ErrorResponse, "description": description,
                           "content": {"application/json": {"example": {"detail": example}}}}
    return responses


DESCRIPTIONS = {
    "live": """**用途**：检查 API 进程是否还能响应 HTTP，供容器或监控使用。

**前置条件**：无；不需要 API Key。返回 200 和 `status=ok` 只说明进程在运行，不检查数据库、Redis、Worker 或文件存储。

**下一步**：检查数据库与基础表是否就绪，调用 `/health/ready`。""",
    "ready": """**用途**：确认数据库可连接，并且迁移创建的用户、项目业务字段和人工审核记录表可以查询。

**返回**：200 表示这两个检查通过；503 表示数据库或表结构不可用。无需 API Key。

**边界**：它不检测 Redis、Worker 或文档解析质量；`formal_review_ready=false` 是当前功能阶段说明，不是数据库异常。""",
    "create_project": """**用途**：为一次投标工作建立资料空间，例如“某信息化系统采购项目”。

**请求**：JSON 格式，填写 `name`；当前用户自动成为项目 OWNER。

**返回**：201 和 `{id, name}`。把这里的 `id` 作为后续上传接口的 `project_id`。

**注意**：项目名称不是唯一键；再次调用会创建另一个项目。本接口当前没有 Idempotency-Key 去重。""",
    "list_projects": """**用途**：找回当前用户有权限访问的项目 ID 和名称。

**参数**：无额外参数，身份由 X-API-Key 确定。

**返回**：200 和数组；没有项目时为 `[]`。当前没有分页，也没有约定排序。不返回其他用户的私有项目。""",
    "upload_document": """**用途**：在已有项目下新增一份逻辑文档，并保存它的第 1 个 PDF 修订、后台任务及待投递事件。

**填写方式**：`multipart/form-data`。选择 `file`，填写 `title` 和 `kind`，请求头填写 `Idempotency-Key`。

**文件类型**：TENDER=招标文件；AMENDMENT=更正公告；RESPONSE=投标响应；EVIDENCE=证明材料。目前这些类型用于分类存储，上传更正公告不会自动修改要求或触发变更分析。

**返回**：202，保存 document_id、revision_id、job_id。随后查询任务，成功后取得 artifact_id。

**重复请求**：同一用户、项目和新增文档操作内，同键且内容/元数据相同返回原响应；同键但内容或元数据不同返回 409。换一个键会创建另一份逻辑文档，即使文件名或字节相同。

**文件校验**：默认最大 50 MiB；只检查接收格式，损坏、加密、超过默认 300 页等问题可能在后台任务中失败。202 不保证最终解析成功。

**source_url**：仅记录材料来源地址，不会替你从这个网址下载文件；仍须上传 file。""",
    "upload_revision": """**用途**：给一份已有逻辑文档增加新 PDF 版本，例如“技术响应书修改版”。document_id 保持不变，新的文件生成新的 revision_id 和递增 revision_no。

**请求**：选择 file，传 Idempotency-Key，可选 source_url。标题和材料类型沿用原逻辑文档，不在此修改。

**去重**：同一文档内，如 PDF 原始字节 SHA-256 与历史某修订相同，复用该修订和已有任务，返回 reused=true；不保证是最新修订。若幂等键命中原请求，返回原响应，reused 字段也保留原值。

**返回**：202。旧修订仍可查询和下载；新上传不会覆盖旧文件。当前没有“自动选为正式投标版本”的行为。

**权限与后续**：需要 OWNER/EDITOR；用 job_id 查询后台处理，再读取产物。""",
    "list_revisions": """**用途**：查看一份逻辑文档有哪些历史 PDF 版本，确认每个版本的修订号、文件 hash 和处理状态。

**返回**：200，按 revision_no 从小到大排列的数组。字段 id 是 revision_id，不是 document_id。

**状态**：NEEDS_REVIEW 表示文字层探针完成但质量待检查；不能据此判断材料是否满足招标要求。created_at 是 UTC 时间，当前无时区后缀。

**边界**：本接口不返回 job_id；日常调用请保存上传响应中的 job_id。当前列表不分页。""",
    "get_job": """**用途**：跟踪上传后后台处理的结果。建议每 1–2 秒查询一次，收到 SUCCEEDED 或 FAILED 后停止轮询；可按网络情况放慢频率。

| status | 含义 | 调用方下一步 |
|---|---|---|
| QUEUED | 已登记，等待 Worker | 继续等待 |
| RUNNING | Worker 已领取并处理 | 继续等待 |
| RETRY_WAIT | 暂时失败，等待自动重试 | 继续等待，观察 error_code |
| SUCCEEDED | 技术处理完成 | 使用 artifact_id 查询产物 |
| FAILED | 最终失败 | 查看 error_code/error_detail，检查材料或运维原因 |

attempt 是已领取执行次数，初始 0。当前任务可能没有百分比进度，也没有公开的手动取消/重试接口。若任务长期排队，需检查 dispatcher、Redis 和 Worker。

**不要混淆**：HTTP 200 表示成功查到了任务，即使任务自身 status=FAILED。SUCCEEDED 也不是投标业务审核通过。""",
    "get_artifact": """**用途**：读取某个成功任务的解析概况：文件修订、页数、来源块数、解析配置和质量提示。

**前置**：从成功任务取得 artifact_id。无权限或 ID 不存在返回 404。

**当前产物**：pdfplumber-probe-v1 只处理 PDF 文字层，文字块大体按行划分；block_count 不是要求数。所有结果为 NEEDS_REVIEW、formal_review_ready=false。

**质量提示**：NO_EXTRACTABLE_TEXT 可能表示扫描件没有文字层；PAGES_NEED_ATTENTION 表示部分页待检查。即使技术任务成功，也可能没有可用文字。下一步查询 blocks，并回到原件检查。""",
    "list_blocks": """**用途**：分页读取提取的文字与位置，为人工阅读、来源核对和后续检索准备数据。

**查询参数**：page 可指定 PDF 实际页（从 1 开始）；offset 表示过滤后跳过多少条，默认 0；limit 为本次最多条数，默认 100，上限 200。

**返回**：200 和数组，按 block_id 升序。没有匹配项或超出结果范围时返回 []；并不表示产物不存在。当前无 total/next_cursor 字段，翻页时可将 offset 增加 limit，直到返回数量小于 limit。

**坐标**：bbox=[左,上,右,下]，单位 PDF point（1/72 英寸），原点在左上；不是像素。PDF 实际页序与印刷页码可能不同。

**下一步**：选定 block_id，连同 artifact_id 调用 source，取得原件地址及版本 hash。""",
    "source": """**用途**：把一个文字块完整回溯到“哪份文件版本、哪一页、哪个矩形位置”，用于引用核验。

**参数关系**：artifact_id 和 block_id 必须来自同一产物；只有 block_id 无法跨产物唯一定位。

**返回**：quote 为提取原文，text_hash 为其 UTF-8 SHA-256；revision_sha256 为原 PDF 字节 hash，二者用途不同。original_url 指向这份修订的原件下载接口。

**查看原件**：下载时仍需要 X-API-Key。浏览器地址栏直接打开 original_url 不会带这个请求头，可能得到 401；可用带认证的客户端获取 PDF，再按 page/bbox 定位。

**边界**：来源存在只证明文字从哪里提取，尚不表示该文字是满足某条要求的有效证据。""",
    "original": """**用途**：查看或下载指定不可变修订的原始 PDF。适合核对引用是否对应正确版本。

**返回**：200，Content-Type 为 application/pdf，内容是文件字节而非 JSON；Content-Disposition 为 inline，支持客户端预览。文件名使用 revision_id。

**前置**：需要有效 X-API-Key 和该修订所在项目的访问权限；可从上传结果或修订列表取得 revision_id。

**错误**：无权限或修订不存在返回 404；数据库有记录但存储文件缺失返回 503。下载历史修订不会自动替换成最新文件。""",
}
