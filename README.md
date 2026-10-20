# 投标文件审查与资料协同系统

当前版本 **0.4.0**：在引导式演示之外，新增独立的“我的项目”网页。可以使用自己的 PDF 走通要求整理、正式材料选择、人工审查、整改复核及报告导出。项目仍处于本地单机开发阶段；没有声称已有企业上线或实际客户使用经历。

## 使用自己的项目

打开 **[我的项目](http://127.0.0.1:18080/workspace)**，使用本地 `.env` 中的 `BID_BOOTSTRAP_API_KEY` 登录初始负责人账号。密钥仅用于登录请求，网页不在本地存储中保存它；后续使用可撤销的 HttpOnly Cookie。详细操作见 [真实项目工作台使用说明](docs/真实项目工作台.md)。

1. 创建项目，在“资料与版本”上传有文字层的招标、响应或证明 PDF；等待后台解析，并打开原件检查。
2. 在“整理要求”选择招标原文，写出一条能独立核对的要求，保存、确认，再发布全部要求。
3. 在“资料与版本”明确选择本轮使用的响应修订及用途，发布正式材料集。
4. 在“本轮审查”逐项阅读双方原文，保存人工判断；发现问题时登记缺口并指派整改人。
5. 负责人修改实际 PDF，上传修订并发布新版材料，提交整改；另一位实际账号登录后复核。
6. 整改验收后逐项最终确认，在“检查报告”查看覆盖情况并下载 Markdown。

网页没有演示角色切换。协作账号通过已有 CLI 创建，由负责人在成员页按姓名查找并加入；不能复核自己的整改提交。

## 先体验，三分钟看懂这个方向

启动后打开 **[演示工作台](http://127.0.0.1:18080/)**，点击“开始这次文件检查”。[体验说明与实测](docs/mvp体验说明.md) 记录当前范围：

1. 对照两边原文：采购方要求2小时内响应，我们的文件却承诺4小时。
2. 登记这处问题，交给编写人陈工。
3. 切换到陈工，开始整改，保存新的2小时响应 PDF，提交复核。
4. 切回审查人林悦，回看原文，验收并确认本项满足。
5. 在报告中核对、勾选剩余两项，完成本轮检查；可以下载记录。
6. 可选：模拟响应文件又更新一稿，看看旧结论怎样保留并提示重新核对。

页面不需要填写技术 ID 或 API Key。每个浏览器会话创建隔离的演示项目，Cookie 可恢复七天内的进度；“重新体验”新建样例，不删除旧数据。PDF 修订、要求来源、整改、复核和报告均写入真实后端，差异是预设演示规则，未接模型。角色切换只是此构造项目的体验功能。

Compose 本机默认开启 `BID_DEMO_ENABLED=true`，普通应用配置默认关闭。正式共享部署须关闭此变量；演示 Cookie 不能操作或下载其他项目。所有本机端口仍只绑定127.0.0.1。

已实现：项目成员与角色、PDF 上传/不可变修订/幂等、MySQL 任务与 outbox、Redis/Celery 投递、租约恢复和旧 Worker 写入拦截、文字层探针、页码/bbox 来源与原件下载、要求修订/确认/完整基线、冻结正式材料集、问题指派/整改/独立复核、逐项人工报告和审计。

当前为 `review_mode=HUMAN`。解析器 `pdfplumber-probe-v1` 只提取文字层，产物固定 `NEEDS_REVIEW`、`formal_review_ready=false`，表示不能自动审查；人工引用时须回看原件。Docling、DOCX、OCR、RAG/Milvus、LangGraph 模型审查和更正自动影响分析尚未实现。

## 接口怎么使用

先读 [业务流程与接口](docs/业务流程与接口.md)，用“要求2小时、响应4小时”的连续场景理解谁在什么时候调用哪个接口，再查 [40 个接口的中文使用手册](docs/API接口说明.md) 或 [Swagger](http://127.0.0.1:18080/docs)。接口均有中文业务用途、角色、前置条件、字段、状态、错误与下一步说明。

顺序：认证/项目分工 → 上传 PDF 并核对原文 → 登记要求 → 确认并发布基线 → 选择正式材料 → 登记问题 → 负责人整改 → 另一人复核 → 逐项审核决定 → 报告。Swagger 的 `Try it out` 可调试，`Schema` 可查看字段中文说明。各 ID 不能混用。

新材料/基线会使旧提交及审核过期；同轮发现新问题也会使该要求的原满足决定失效。没有问题记录不等于检查过，未发布要求修改也会阻止报告显示完成。

`docs/openapi.json` 与接口手册从实际代码导出：`python scripts/export_api_docs.py`。实现说明见 [技术实现](docs/技术实现.md)，当前验收见 [0.4.0 工作台实测](docs/workspace-verification.md)。

## 启动

需要 Docker Desktop（Linux 容器）和用于生成本地环境文件的 Python。终端进入本目录：

```powershell
python scripts/init_env.py
docker compose up --build -d --wait --wait-timeout 180
docker compose ps
```

接口文档：http://127.0.0.1:18080/docs 。点击 Authorize，填入本地 `.env` 中的 `BID_BOOTSTRAP_API_KEY`。凭据每份安装独立生成，不在仓库中提供默认公开密钥。MySQL 与 Redis 仅在 Compose 内部网络开放。

首次启动执行 Alembic 迁移及 owner 初始化。已有 `.env` 不会被覆盖。已有数据库的凭据须与首次建库时一致。

Compose 项目名沿用 `bid-review-phase1`，用于复用升级前的命名卷。其他账号由运维用 `python -m app.cli bootstrap --name ... --key-env ...` 创建：密钥从所指定的环境变量读取，至少24字符。每人使用自己的 API Key，负责人再添加项目角色。

## 验证完整业务流程

```powershell
docker compose exec -T api python scripts/business_smoke.py --base-url http://localhost:8000
```

脚本创建构造样本项目与编写/审查账号，通过真实 HTTP、MySQL、Redis/Worker 跑通“2小时要求、4小时响应、修改为2小时、独立复核、最终确认”。四路并发登记同一问题只建一条问题和任务，最后发布新快照验证旧结论失效。运行报告 `docs/business-smoke.json` 不含明文密钥且排除在 Git 外；测试项目保留在本地库中。

## 验证真实样本

样本是 2023 年上海政府采购的 65 页信息化项目招标文件，只用于历史文本和来源定位验证。仓库不附带第三方 PDF，脚本从固定公开来源下载：

```powershell
docker compose exec api python scripts/fetch_sample.py
docker compose exec api python scripts/smoke.py --base-url http://localhost:8000
```

第二条命令会实际创建项目并完成 API → MySQL/outbox → Redis/Celery → 来源查询；验证重复上传不会新建任务，以及原件 hash、页码和返回内容一致。容器内下载样本和报告存于该容器工作目录；需要留存时使用 `docker compose cp` 拷出。原始业务文件和解析产物另有命名卷保存。

本机执行可先创建 Python 3.12 虚拟环境并安装 `requirements.lock`，然后运行同名脚本。Docker 为推荐运行方式；Celery Worker 在 Linux 容器中执行。

## 测试与迁移

```powershell
docker compose exec api python -m pytest -q
docker compose exec api python -m alembic current
docker compose exec api python -m alembic check
docker compose exec api python scripts/mysql_invariants.py
```

自动测试使用独立 SQLite 数据库检查业务不变量；真实 MySQL、Redis 和 Worker 另用集成路径验证，不能以 SQLite 单测代替 MySQL 兼容性结论。迁移在 `migrations/versions`，不得通过应用启动时 `create_all` 代替生产迁移。

`docs/phase1-verification.md`、`docs/phase2-verification.md` 保留前两阶段历史结果，本轮见 `docs/workspace-verification.md`。`requirements.lock` 固定开发/测试镜像依赖；正式部署前再拆分纯运行依赖。

## 目录

```text
app/main.py          HTTP 接口与项目鉴权
app/dependencies.py  共用身份认证与请求参数
app/business_api.py  按业务动作组织的接口
app/business.py      基线、材料、问题整改、复核与报告规则
app/business_schemas.py  业务字段与中文说明
app/demo.py          隔离演示会话与业务动作适配
app/workbench_api.py 实际账号登录、项目聚合读取、成员查找与报告导出
app/session_auth.py  Cookie 写入同源检查
app/static/          中文引导页面，原生HTML/CSS/JS，无前端构建依赖
app/demo_assets/     明确标记的中文PDF构造样本
app/services.py      上传幂等及文档版本事务
app/models.py        核心领域表
app/jobs.py          领取、租约、结果提交、恢复及 outbox
app/parsers.py       文字层和 bbox 诊断
app/worker.py        Celery Worker
app/dispatcher.py    单实例投递与恢复扫描
migrations/          Alembic 迁移
tests/               权限、幂等、版本、任务恢复与引用测试
scripts/             环境初始化、公开样本下载与端到端验证
docs/                实测结果与后续任务
```

## 当前运行约定

- 时间入库使用 UTC；对外界面后续按用户时区转换。
- v1 只有单实例 dispatcher；并发扩容前需验证批量领取公平性、索引与恢复时延。
- 原件、解析产物和 source ID 不原位覆盖；新解析器使用新 profile。
- 技术解析成功与业务判断分开；当前的满足/有问题/不适用均由人明确记录，模型未参与。
- 本地端口只绑定 127.0.0.1；正式共享部署前配置 HTTPS、组织身份认证和配额。
- 单机 Compose 只验证进程恢复，不提供高可用和磁盘故障零丢失承诺。
- 当前无任务转派、问题撤销、要求退休/删除和自动通知；已有任务的负责人须保留 EDITOR 权限。新输入暂按全项目失效，尚无局部影响分析。
- `.env`、业务文件、运行报告、IDE 配置不入 Git。`python scripts/package_source.py` 可生成排除这些内容的源码包。

演示 PDF 是仓库内的固定构造素材，不是业务原件。重新生成仅开发时需要 reportlab==4.4.9，运行 `python scripts/build_demo_assets.py`；应用运行本身不依赖 ReportLab。

停止服务使用 `docker compose stop`，保留命名卷。不要在未备份业务数据时使用带 `-v` 的删除命令。
