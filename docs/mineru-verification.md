# 0.7.0 MinerU解析重构验收

验收日期：2026-10-21。Windows + Docker Desktop Linux容器，16个逻辑CPU、约16GiB容器内存；使用CPU，无GPU依赖。

## 运行版本与默认路径

新上传和重解析默认`mineru-4.0.12-flash-auto-v1`。实际SDK为MinerU4.0.12、DocVortex0.5.16，隔离Python3.12环境的112项依赖已锁定。不是模拟HTTP返回，也未使用旧探针回退生成新产物；历史任务仍按原profile运行。

## 真实SDK和队列

运行`docker compose exec -T api python -m scripts.mineru_smoke`，通过真实HTTP、MySQL/outbox、Redis/Celery及独立SDK进程得到：

| 检查 | 结果 |
|---|---|
| 三页构造中文招标PDF | 3页、23个文字块；实际Flash/txt |
| 同一旧PDF升级 | 同一文件修订下2份产物，旧pdfplumber与新MinerU并存 |
| 4路相同幂等键重解析 | 复用1个解析任务 |
| 旧原文出处和要求引用 | 保持不变，仍可查询 |
| 新质量意见 | 0条，未继承旧产物意见 |
| 基线/正式材料及epoch | 不因重解析自动改变 |
| 新上传路径 | 产物profile确认为MinerU |

运行`python -m scripts.mineru_scan_smoke`：将仓库构造招标第2页栅格化为没有文字层的图片PDF，再经项目适配器实际调用SDK。输出实际模式Flash/ocr，“2小时”和“2次”两处检查点均识别到。测试文件只在临时目录，公开模型缓存写入独立卷。

验收时发现缺少中文字体会使未嵌入字体的构造PDF栅格化后只剩数字。已查看实际渲染图确认，并在解析镜像加入fontconfig和Noto CJK，再运行上述OCR检查通过。这是字体渲染问题的修复，不是OCR准确率保证。

## 已有业务和网页

真实`business_smoke`已通过：4路重复问题登记仅1条问题/任务，修改响应后由另一人复核，报告为REVIEW_COMPLETE；发布另一份快照后旧结果转NEEDS_RECHECK。说明替换解析器后原业务链路仍可运行。

网页使用已有构造验收账号，对招标和正式响应分别点击“重新解析”。两份文件均显示MinerU profile和23个文字块；正式材料选择仍显示“当前冻结解析 · pdfplumber-probe-v1”，新MinerU产物作为另一个可选项，不自动替换。基线第1版、正式材料第1套保持不变。

新招标产物的质量页显示“人工已核对0/3页”，原件链接和逐页文字可查看；没有替用户确认质量或重新发布。截图随本地交付保存为`outputs/bid-review-mineru.png`。验收完成退出测试账号，保留工作台登录入口。

## 页码/短句检查点

4份同模板构造PDF、6个既有页码/完整短句检查点全部执行真实MinerU。由于MinerU将全角冒号`：`变为半角`:`：

- 保留原标点的严格匹配为 **0/6**。
- 去空白并做Unicode NFKC等价比较为 **6/6**，页数全部正确。
- 输出分别保存`strict_matched`和`matched`，比较规则为`unicode-nfkc-whitespace-v1`；原始提取文本没有为评测改写。

该结果不能与旧探针的逐字匹配数混为同一个指标。NFKC不把“2小时”和“4小时”视为相同，已增加回归检查。引导演示和合成模型验收的条款查找也兼容此类标点差异，来源正文仍保留实际输出。

评测结果默认写在可写的存储卷`/data/blobs/evaluation/extraction-report.json`，避免非root容器向只读应用根目录新建data目录。它不是整文准确率，也不覆盖多模板、复杂表格或真实扫描集。

## 自动测试与接口

完整回归 **64 passed**，原46项加新增18项；保留1条既有Starlette/httpx测试工具弃用警告。新增覆盖坐标换算、列表/表格文本、未知协议与错误版本、缺页、无效矩形、重复块顺序、图片描述隔离、PDF预检、子进程超时/租约失效、缺失运行环境、重解析权限/幂等、跨配置互斥、旧证据保留和标点兼容。

Alembic检查没有新升级操作，数据库结构无变更。新增1个重解析接口，公开接口合计52个，中文手册和OpenAPI从实际代码导出。前端脚本语法检查通过。

## 验证边界

本轮实际验收Flash/txt及Flash/ocr。Basic可按独立profile配置，但没有本轮实际效果结果；Standard/Advanced及VLM未接入。表格HTML纯文本和坐标适配有单元测试，没有复杂真实表格效果结论。尚未重跑历史65页公开采购样本，不能把旧结果算作本轮MinerU结果。

云模型要求候选的语义效果仍待实际配置与评测；RAG/Milvus、自动响应审查和DOCX上传尚未实现。使用和配置见[MinerU解析重构](MinerU解析重构.md)。
