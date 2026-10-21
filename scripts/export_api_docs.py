"""从真实 OpenAPI 导出中文接口手册，避免另一份手写参数表与代码漂移。"""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from app.main import app  # noqa: E402


def export():
    specification = app.openapi()
    schemas = specification["components"]["schemas"]

    def resolve(schema):
        if "$ref" in schema:
            return {**schemas[schema["$ref"].rsplit("/", 1)[-1]],
                    **{key: value for key, value in schema.items() if key != "$ref"}}
        return schema

    def type_name(schema):
        schema = resolve(schema)
        if "anyOf" in schema:
            return " / ".join(type_name(item) for item in schema["anyOf"])
        if schema.get("type") == "array":
            return f"数组<{type_name(schema.get('items', {}))}>"
        if schema.get("format") == "binary":
            return "文件"
        return schema.get("type", "object") + (f" ({schema['format']})" if "format" in schema else "")

    def constraints(schema):
        schema = resolve(schema)
        descriptions = []
        for name, label in [("default", "默认"), ("minimum", "最小"), ("maximum", "最大"),
                            ("minLength", "最短字符数"), ("maxLength", "最长字符数"),
                            ("minItems", "最少项数"), ("maxItems", "最多项数")]:
            if name in schema:
                descriptions.append(f"{label}={schema[name]}")
        if "enum" in schema:
            descriptions.append("可选值=" + ", ".join(str(value) for value in schema["enum"]))
        return "；".join(descriptions) or "—"

    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    def example(schema):
        schema = resolve(schema)
        if schema.get("examples"):
            return schema["examples"][0]
        if "const" in schema:
            return schema["const"]
        if "enum" in schema:
            return schema["enum"][0]
        if "default" in schema:
            return schema["default"]
        if schema.get("format") == "date":
            return "2026-10-19"
        if schema.get("format") == "date-time":
            return "2026-10-19T09:00:00"
        if "anyOf" in schema:
            return example(schema["anyOf"][0])
        if schema.get("type") == "object" or "properties" in schema:
            return {name: example(value) for name, value in schema.get("properties", {}).items()}
        if schema.get("type") == "array":
            return [example(schema.get("items", {})) for _ in range(schema.get("minItems", 1))]
        return {"string": "示例", "integer": 1, "number": 1.0, "boolean": False, "null": None}.get(schema.get("type"))

    lines = ["# 投标审查系统：中文接口使用手册", "", f"适用版本：{specification['info']['version']}。由当前应用的 OpenAPI 自动生成。", "",
             "先读 [业务流程与接口](业务流程与接口.md)，理解谁在什么场景调用接口，再查本手册的参数。", "",
             "在线调试：[Swagger](http://127.0.0.1:18080/docs)；机器可读规范：[OpenAPI JSON](openapi.json)。", "",
             specification["info"]["description"].strip(), "",
             "## 推荐调用顺序", "", "```mermaid", "flowchart LR",
             "  A[Authorize 认证] --> B[创建/选择项目] --> C[上传 PDF] --> D[查询 job]",
             "  D -->|SUCCEEDED| E[读取 artifact 概况] --> F[读取 blocks] --> G[查询 source] --> H[下载原 PDF 核对]",
             "  D -->|FAILED| I[查看错误并处理]", "```", "",
             "业务闭环：登记要求 → 人工确认 → 发布基线 → 选择正式材料 → 登记问题 → 负责人整改 → 另一人复核 → 逐项审核 → 查看报告。", "",
             "## 参数位置怎么区分", "",
             "| 位置 | 含义 | 如何填写 |", "|---|---|---|",
             "| path | URL 路径中的占位符，例如 `{project_id}` | 使用上一步真实返回的 ID |",
             "| query | URL 问号后的筛选或分页参数 | 例如 `?page=3&offset=0&limit=100` |",
             "| header | HTTP 请求头 | `X-API-Key` 负责认证，`Idempotency-Key` 负责业务写入去重 |",
             "| JSON body | JSON 请求体 | 创建项目时填写 `{\"name\":\"项目名称\"}` |",
             "| multipart/form-data | 文件加表单字段 | 上传 PDF 时选择 file，并填写 title/kind 等 |", "",
             "## 全部接口", "",
             "| 方法 | 路径 | 用途 |", "|---|---|---|"]
    operations = []
    for path, methods in specification["paths"].items():
        for method, operation in methods.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                operations.append((path, method, operation))
    business_order = ["create_project", "list_projects", "get_me", "set_member", "list_members", "get_workspace", "upload_document", "upload_revision",
                      "list_revisions", "get_job", "get_artifact", "list_blocks",
                      "get_block_source", "download_original", "create_requirement", "list_requirements", "revise_requirement",
                      "list_requirement_revisions", "confirm_requirement", "publish_baseline", "list_baselines",
                      "publish_material_set", "list_material_sets", "create_issue", "list_issues", "list_tasks",
                      "transition_task", "list_task_submissions", "decide_task", "decide_requirement",
                      "list_requirement_decisions", "get_review_report", "check_liveness", "check_readiness"]
    operations.sort(key=lambda item: business_order.index(item[2]["operationId"])
                    if item[2]["operationId"] in business_order else len(business_order))
    for path, method, operation in operations:
        lines.append(f"| {method.upper()} | `{path}` | {operation['summary']} |")
    lines.append("")
    for number, (path, method, operation) in enumerate(operations, 1):
        assert operation.get("summary") and len(operation.get("description", "")) > 100
        lines.extend([f"## {number}. {operation['summary']}", "", f"`{method.upper()} {path}`", "",
                      operation["description"].strip(), "",
                      "**认证**：" + ("使用 `X-API-Key` 或浏览器登录 Cookie；Cookie 写入还须同源 `Origin`。" if operation.get("security") else "不需要已有会话；登录请求体需要账号访问密钥。" if operation["operationId"] == "login_browser" else "不需要认证；浏览器退出须同源 `Origin`。" if operation["operationId"] == "logout_browser" else "不需要认证。"), ""])
        if operation.get("parameters"):
            lines.extend(["**参数说明**", "", "| 名称 | 位置 | 必填 | 类型 | 限制/默认 | 说明 |", "|---|---|---|---|---|---|"])
            for parameter in operation["parameters"]:
                assert parameter.get("description"), (path, parameter["name"])
                lines.append("| " + " | ".join(cell(value) for value in [
                    f"`{parameter['name']}`", parameter["in"], "是" if parameter.get("required") else "否",
                    type_name(parameter.get("schema", {})), constraints(parameter.get("schema", {})),
                    parameter.get("description", "")]) + " |")
            lines.append("")
        for media_type, content in operation.get("requestBody", {}).get("content", {}).items():
            schema = resolve(content.get("schema", {}))
            lines.extend([f"**请求体：`{media_type}`**", "", "| 字段 | 必填 | 类型 | 限制/默认 | 说明 |", "|---|---|---|---|---|"])
            for name, prop in schema.get("properties", {}).items():
                assert prop.get("description") or resolve(prop).get("description"), (path, name)
                lines.append("| " + " | ".join(cell(value) for value in [f"`{name}`",
                    "是" if name in schema.get("required", []) else "否", type_name(prop), constraints(prop),
                    prop.get("description", resolve(prop).get("description", ""))]) + " |")
            lines.append("")
            if media_type == "application/json":
                lines.extend(["```json", json.dumps(example(schema), ensure_ascii=False, indent=2), "```", ""])
        responses = operation["responses"]
        lines.extend(["**HTTP 返回**", "", "| 状态码 | 含义 |", "|---|---|"])
        for status, response in responses.items():
            lines.append(f"| {status} | {cell(response.get('description', ''))} |")
        lines.append("")
        for status, response in responses.items():
            if not status.startswith("2"):
                continue
            for media_type, content in response.get("content", {}).items():
                schema = content.get("schema", {})
                if media_type == "application/pdf":
                    lines.extend(["**成功返回是 PDF 文件字节，没有 JSON 字段。**", ""])
                    continue
                if media_type == "text/markdown":
                    lines.extend(["**成功返回是 UTF-8 Markdown 报告文件，没有 JSON 字段。**", ""])
                    continue
                shape = resolve(schema)
                if shape.get("type") == "array":
                    shape = resolve(shape.get("items", {}))
                lines.extend(["**成功返回字段**（数组接口描述的是每一个元素）", "",
                              "| 字段 | 类型 | 说明 |", "|---|---|---|"])
                for name, prop in shape.get("properties", {}).items():
                    assert prop.get("description"), (path, name)
                    lines.append(f"| `{name}` | {cell(type_name(prop))} | {cell(prop['description'])} |")
                lines.extend(["", "**格式示例**：以下示例 ID 需要替换为实际值，不代表现有数据库记录。", "",
                              "```json", json.dumps(example(schema), ensure_ascii=False, indent=2), "```", ""])
    lines.extend(["## 状态和常见问题速查", "",
        "| 现象 | 解释与处理 |", "|---|---|",
        "| `202` 后马上查不到 artifact_id | 正常：任务仍在排队或处理中，继续查 job |",
        "| `200` 但 job.status 是 FAILED | 查询任务成功，任务执行失败；查看 error_code 和 error_detail |",
        "| `SUCCEEDED` 但 formal_review_ready=false | 文字层提取完成但不具备自动审查能力，人工闭环可继续并回看原件 |",
        "| `NEEDS_REVIEW` | 解析结果都需要人工检查；OCR已执行不等于无错漏，表格语义仍需核对 |",
        "| `404` | ID 错误、ID 用错类型，或当前身份没有项目权限 |",
        "| `409` | 幂等键内容冲突，或基线/材料/epoch/任务状态变化；刷新并重新核对 |",
        "| 下载原件链接直接打开得到 `401` | 先在本站工作台登录以取得 Cookie，或使用 X-API-Key 客户端；Cookie 过期时重新登录 |",
        "| 列表返回 `[]` | 该身份没有项目，或者页码/offset 没有匹配项；不一定是接口失败 |",
        "| 扫描 PDF 技术任务成功，但文字块为 0 | 核对产物所用解析配置、实际OCR标记和模型可用性；不把零文字自动视为空白 |", "",
        "## 最小 Python 调用例子", "",
        "在项目根目录、已安装 requirements.lock 的 Python 环境执行。先准备 `sample.pdf`；密钥从本地 .env 读取，代码不打印它。", "", "```python",
        "import time", "import uuid", "from pathlib import Path", "import httpx", "from dotenv import dotenv_values", "",
        'key = dotenv_values(".env")["BID_BOOTSTRAP_API_KEY"]',
        'with httpx.Client(base_url="http://127.0.0.1:18080",',
        '                  headers={"X-API-Key": key}, timeout=60, trust_env=False) as client:',
        '    response = client.post("/api/v1/projects", json={"name": "接口学习项目"})',
        "    response.raise_for_status()", '    project_id = response.json()["id"]',
        '    request_key = str(uuid.uuid4())  # 本次上传固定一个键；网络重试时沿用',
        '    with Path("sample.pdf").open("rb") as stream:',
        '        response = client.post(f"/api/v1/projects/{project_id}/documents",',
        '            headers={"Idempotency-Key": request_key},',
        '            data={"title": "待核对招标文件", "kind": "TENDER"},',
        '            files={"file": ("sample.pdf", stream, "application/pdf")})',
        "    response.raise_for_status()", '    job_id = response.json()["job_id"]',
        "    for _ in range(180):  # 最多轮询约 6 分钟", '        response = client.get(f"/api/v1/jobs/{job_id}")',
        "        response.raise_for_status()", "        job = response.json()",
        '        if job["status"] == "SUCCEEDED":', "            break",
        '        if job["status"] == "FAILED":', '            raise RuntimeError(f"{job[\'error_code\']}: {job[\'error_detail\']}")',
        "        time.sleep(2)", "    else:", '        raise TimeoutError("任务尚未完成，请检查后台服务")',
        '    artifact_id = job["artifact_id"]',
        '    response = client.get(f"/api/v1/artifacts/{artifact_id}/blocks", params={"limit": 10})',
        "    response.raise_for_status()", "    blocks = response.json()",
        "    if blocks:", '        block_id = blocks[0]["block_id"]',
        '        response = client.get(f"/api/v1/artifacts/{artifact_id}/blocks/{block_id}/source")',
        "        response.raise_for_status()", "        source = response.json()", "        print(source)",
        '        original = client.get(source["original_url"])', "        original.raise_for_status()",
        '        Path("downloaded-original.pdf").write_bytes(original.content)', "```", "",
        "## 文档维护", "", "说明来自 app/main.py、app/schemas.py、app/api_docs.py、app/business_api.py 和 app/business_schemas.py。修改后运行：", "", "```powershell",
        "docker compose exec api python scripts/export_api_docs.py", "```", "",
        "重新构建并启动 API 后，Swagger 使用最新说明。OpenAPI、中文手册以及源码包应一起更新。", ""])
    destination = root / "docs"
    destination.mkdir(exist_ok=True)
    (destination / "openapi.json").write_text(json.dumps(specification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manual = destination / "API接口说明.md"
    manual.write_text("\n".join(lines), encoding="utf-8")
    print(f"Exported {len(operations)} documented operations: {manual.name} and openapi.json")


if __name__ == "__main__":
    export()
