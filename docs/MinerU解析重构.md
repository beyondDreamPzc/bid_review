# MinerU PDF 解析与历史产物升级

适用版本：0.7.0。新上传的PDF默认使用 **MinerU4.0.12、Flash档位、auto模式**；按实际文件选择原生文字或OCR。使用本地SDK，不上传到官方解析云服务。已有pdfplumber产物继续按原配置读取，不改写旧出处。

## 业务操作

在[我的项目](http://127.0.0.1:18080/workspace)的“资料与版本”上传PDF，等待解析任务完成。文件行会显示实际产物的解析配置。点击“检查解析质量”，按页核对文字和原件；解析完成仍是NEEDS_REVIEW，不表示投标响应符合要求。

已有文件无需重复上传，点击文件修订的“重新解析”。它调用 `POST /api/v1/revisions/{revision_id}/parse`，对同一不可变PDF登记当前配置的任务；相同配置复用已有任务，失败后按钮可明确重试。HTTP202表示已登记，随后轮询job_id。

重解析成功后，工作台使用新产物供后续选择。原有要求、材料集和基线仍引用原来冻结的artifact/block，不自动替换。新产物不继承旧页级核对意见。若要用新来源改写要求或本轮材料，仍需人工修订、确认和发布。重解析本身不增加审查epoch。

重解析进行中或失败时，最近成功的历史产物仍可查看，页面分别显示“产物配置”和“本次请求配置”。不会把失败伪装成已升级成功。OWNER/EDITOR可以发起，其他成员只读；不能同时为同一文件启动不同配置的解析任务。

## 技术链路

```mermaid
flowchart LR
    A[上传或重解析] --> B[MySQL Job与outbox]
    B --> C[Redis parse队列]
    C --> D[独立Celery解析Worker]
    D --> E[PDF页数和完整性检查]
    E --> F[隔离Python子进程调用MinerU SDK]
    F --> G[MiddleJson协议与页覆盖校验]
    G --> H[PDF点坐标与文字块]
    H --> I[不可变产物和来源索引]
    I --> J[人工核对及后续要求整理]
```

API、dispatcher、AI候选Worker仍使用轻量应用镜像。只有parse Worker使用`bid-review-parser:0.7.0`，MinerU的112项Python依赖完整固定在`requirements-mineru.lock`，安装到`/opt/mineru`虚拟环境。它与API的依赖分开，避免升级Gradio、Pydantic或模型包影响既有业务。

Worker用应用环境读取MySQL及原件，通过独立进程调用固定SDK；子进程不继承`BID_*`业务凭据。SDK只处理本地临时文件，`page_range=""`明确处理全文件，不受文档库CLI默认前10页的限制。没有VLM图片描述，图片生成描述也不会被当作原文证据。

推理和模型下载期间，每10秒以内续租。超时或租约失效会停止独立进程组，包括OCR渲染子进程，旧执行者不能提交结果。SDK异常只保留类别，任务不回显原文、路径、密钥或完整失败响应。临时文件随调用结束清理，模型缓存保存在独立命名卷。

## 数据协议与坐标

本次固定SDK4.0.12、DocVortex0.5.16和MiddleJson2.0。校验完整文档标识、实际档位/模式、逐页覆盖、页面点尺寸、块顺序及坐标；不接受未知版本、缺页或1000制坐标冒充0..1坐标。

MinerU的`page_idx`从0开始，系统展示页从1开始；归一化bbox按每页真实`width_pt/height_pt`转换为PDF point，左上角为原点。它与旧系统的来源契约相同，但块划分会改变，因此block_id始终须与新的artifact_id配套使用。

正文、标题、列表、页眉页脚等合并行内span，顶层块保留一个定位矩形。表格HTML转换成纯文本，单元格用制表符、行用换行分隔；不执行HTML脚本，不把表格矩形描述成单元格级坐标。原MiddleJson保存在不可变JSON中，后续仍能回查结构。本次未实现表格单元格级业务引用。

产物仍为`NEEDS_REVIEW`及`formal_review_ready=false`。`NATIVE_TEXT_MODE`或`OCR_PERFORMED`记录实际模式，`TABLE_TEXT_FLATTENED`表示表格文字展平。没有文本的页面仍保留并提示检查，不自动当作原件空白。

## 配置与启动

```powershell
python scripts/init_env.py
docker compose up --build -d --wait --wait-timeout 180
```

升级继续复用原数据库和文件卷，不需要清库。新建`mineru_models`卷只保存本地模型缓存。首次OCR或Basic运行需要联网下载公开模型，可能比普通文本PDF慢；不会因此自动降级到旧探针或远端解析服务。离线运行须事先准备相应模型。

可在本地`.env`设置：

```dotenv
BID_PARSER_PROFILE=mineru-4.0.12-flash-auto-v1
BID_MINERU_TIMEOUT_SECONDS=900
```

| profile | 用途 |
|---|---|
| `mineru-4.0.12-flash-auto-v1` | 默认；自动选择原生文字或OCR，本轮实际验收配置 |
| `mineru-4.0.12-flash-txt-v1` | 明确只走原生文字，扫描页需人工处理 |
| `mineru-4.0.12-flash-ocr-v1` | 明确使用OCR，需准备模型 |
| `mineru-4.0.12-basic-auto-v1` | 小模型解析档位，需要更多模型；本轮未做Basic效果验收 |
| `pdfplumber-probe-v1` | 历史兼容配置，不是MinerU失败时的回退 |

切换profile后重建API与Worker配置：`docker compose up -d --wait --wait-timeout 180`。不同配置产生不同产物。SDK/适配规则升级须新增profile，不能仅修改同一profile背后的引擎版本。Standard/Advanced依赖VLM及额外资源，本轮未接入。

模型默认采用ONNX/CPU，本轮不要求GPU。解析镜像包含Noto CJK和fontconfig：缺少中文字体时，部分未嵌入字体的PDF栅格化会丢中文，不能把这种错误归因于OCR本身。共享部署仍需上传资源隔离、配额及安全加固；当前沿用本地Compose部署范围。

默认文件上限50MiB、300页；SDK结果上限50MiB，单文字块UTF-8最多60000字节，超限明确失败，不截断后冒充完整结果。默认单次执行最多900秒，保留既有有限重试机制。

## 验收命令

```powershell
# 真实HTTP、数据库、队列和SDK；只用仓库构造PDF
docker compose exec -T api python -m scripts.mineru_smoke

# 将构造中文PDF页栅格化为纯图片PDF，再实际运行OCR
docker compose exec -T worker python -m scripts.mineru_scan_smoke

# 原有4份构造文档的6个页码/短句检查点，现在使用当前配置
docker compose exec -T worker python -m scripts.evaluate_extraction

docker compose exec -T api python -m pytest -q
docker compose exec -T api python -m alembic check
```

测试结果见[0.7.0验收记录](mineru-verification.md)。这些是构造样本功能检查，不是多模板或整文准确率评测。

## 官方依据

本次按照[Python SDK](https://opendatalab.github.io/MinerU/usage/sdk_api/)、[输出协议](https://opendatalab.github.io/MinerU/reference/output_files/)和[档位/运行环境](https://opendatalab.github.io/MinerU/usage/tiers/)实现。当前4.x的SDK/HTTP接口与旧2.x/3.x不同，不直接套用旧版`/file_parse`示例。Python包版本已按发布包实际验证。
