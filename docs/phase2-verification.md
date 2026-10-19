# 0.2.0 人工业务闭环实测

验证日期：2026-10-19。环境：Windows Docker Desktop、Linux Python3.12 镜像、MySQL8.4、Redis7.4、真实 Celery Worker/Dispatcher。业务文件明确为构造样本，不代表企业真实投标经历。

## 已通过的验证

| 验证 | 结果 |
|---|---|
| 镜像内自动测试 | 17 passed；1条 Starlette TestClient/httpx 弃用提示，不影响断言 |
| 从已有0001升级到0002 | Alembic 成功，check 显示模型无未迁移差异 |
| 原有数据保留 | 升级前后均为5项目、4文档、8修订、8解析产物 |
| 真实 API/队列解析 | 构造招标2小时、响应4小时、修订响应2小时，实际经 MySQL/outbox、Redis/Celery |
| 人工要求/基线/材料 | 草稿确认、冻结本轮要求与正式响应版本 |
| 四路并发相同问题请求 | 相同幂等键/请求只产生1问题、1任务，四个响应相同 |
| 整改和独立复核 | EDITOR 开始/提交，另一位 REVIEWER 验收，响应修订号为2 |
| 报告完成条件 | 没有问题不等于审过；验收后仍须最终逐项确认，随后 REVIEW_COMPLETE |
| 材料变更 | 再发布新快照后完成状态失效、reviewed_count=0、任务 NEEDS_RECHECK |
| 历史保留 | 旧提交、复核与最终审核仍可查询 |

自动测试还覆盖：有 OWNER 权限的提交人也不能验收/退回自己的提交，退回重做与旧 submission/version 冲突，参考材料不能作正式满足证据，跨项目引用404，角色限制，未确认/遗漏/重复要求不能发布基线，未发布要求修改阻止完成，同轮新问题使此前满足决定失效。

## 如何复现

```powershell
docker compose up --build -d --wait --wait-timeout 180
docker compose exec -T api python -m pytest -q
docker compose exec -T api python -m alembic check
docker compose exec -T api python scripts/business_smoke.py --base-url http://localhost:8000
```

集成脚本每次新建构造测试项目和随机密钥账号，明文密钥不输出、不落报告。运行报告位于容器的 docs/business-smoke.json，默认不入 Git。脚本最后故意将测试项目置为需重新确认，验证失效路径。

## 本轮验证不能证明什么

当前人工模式不证明模型效果、自动要求覆盖率、采购法律合规、扫描/OCR/表格语义正确性或真实企业上线稳定性；没有进行高可用、压力与灾难恢复测试。全项目失效策略仍较保守，当前也没有任务转派、问题撤销和要求退休。详见技术实现和后续顺序。
