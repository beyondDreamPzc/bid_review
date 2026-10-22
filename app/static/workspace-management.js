"use strict";
let managementSequence=0;
function changesView() {
  const impacts=data.change_impacts||[];
  return `<div class="workspace-columns"><section class="panel"><div class="section-heading"><h2>更正影响</h2><span class="count">${impacts.filter(i=>i.disposition==="PENDING").length} 项待处理</span></div><p class="muted">明确更正影响哪些要求。关联会让该要求的旧判断失效，不自动改写正文。</p>${impacts.map(i=>`<article class="req"><div class="row"><h3>${esc(data.requirements.find(r=>r.requirement_id===i.requirement_id)?.title||"历史要求")}</h3>${tag(i.disposition)}</div><p>${esc(i.note)}</p>${sourceQuotes(i.source)}${i.review_note?`<div class="history"><strong>${esc(who(i.reviewed_by))}</strong><p>${esc(i.review_note)}</p></div>`:""}${i.disposition==="PENDING"&&canReview()?`<div class="row"><button class="small" data-impact-decision="${esc(i.id)}" data-disposition="REVISED">已据此修订要求</button><button class="small" data-impact-decision="${esc(i.id)}" data-disposition="NO_CHANGE">确认不需修改</button></div>`:""}</article>`).join("")||emptyState("还没有关联的更正影响","收到更正后，先上传为更正文件，再选择受影响要求与出处。")}</section><section class="panel"><h2>关联一项更正</h2>${canReview()&&data.requirements.length?`<form id="impact-form"><label>受影响要求<select name="requirement_id" required>${data.requirements.map(r=>`<option value="${esc(r.requirement_id)}">${esc(r.title)}</option>`).join("")}</select></label>${pickerHtml("amendment")}<label>影响说明<textarea name="note" minlength="5" maxlength="2000" required placeholder="更正改变了什么，需要核对哪项要求"></textarea></label><button class="primary" type="submit">关联更正并要求重新核对</button></form>`:emptyState("先准备要求与更正原文",canReview()?"整理有效要求并上传更正文件后，在这里关联。":"更正影响由负责人或审查人登记。")}</section></div>`;
}
function auditView() {
  return `<section class="panel"><h2>操作记录</h2><p class="muted">保留实际操作者、动作及时间，不因撤销、退休或移除成员而删除。</p>${listToolbar("audit",[],"按操作类型检索")}<div id="audit-list">${skeleton("正在读取审计记录")}</div></section>`;
}
async function loadAuditView() {
  const pid=projectId,sequence=++managementSequence,s=stateFor("audit");
  try {
    const result=await api(base()+`/catalog/audit?q=${encodeURIComponent(s.q)}&offset=${(s.page-1)*s.size}&limit=${s.size}`);
    if(pid!==projectId||tab!=="audit"||sequence!==managementSequence)return;
    s.total=result.total;
    $("#audit-list").innerHTML=`<div class="table-scroll"><table><caption class="sr-only">项目操作记录</caption><thead><tr><th scope="col">动作</th><th scope="col">操作人</th><th scope="col">北京时间</th><th scope="col">详情</th></tr></thead><tbody>${result.items.map(row=>`<tr><td>${esc(auditLabel(row.action))}</td><td>${esc(row.actor_id?who(row.actor_id):"后台任务")}</td><td>${formatDate(row.created_at,true)}</td><td><details><summary>查看详情</summary><pre>${esc(JSON.stringify(row.details,null,2))}</pre></details></td></tr>`).join("")}</tbody></table></div>${result.items.length?"":emptyState("没有符合条件的记录","清除关键词或完成一次项目操作后查看。")}${pager("audit")}`;
  } catch(error){if(pid===projectId&&tab==="audit")$("#audit-list").innerHTML=failureState(explain(error));}
}
function auditLabel(action) {
  return ({PROJECT_CREATED:"创建项目",CREATE_REQUIREMENT:"录入要求",CONFIRM_REQUIREMENT:"确认要求",PUBLISH_BASELINE:"发布要求基线",PUBLISH_MATERIAL_SET:"发布正式材料",CREATE_ISSUE:"登记问题",TRANSITION_TASK:"更新整改任务",DECIDE_TASK:"复核整改",DOCUMENT_REVISION_CREATED:"上传文件修订",PDF_PARSE_COMPLETED:"完成文件解析",TASK_ASSIGNMENT_CHANGED:"变更整改负责人",ISSUE_LIFECYCLE_CHANGED:"撤销或恢复问题",REQUIREMENT_LIFECYCLE_CHANGED:"退休或恢复要求",AMENDMENT_IMPACT_REVIEWED:"处理更正影响",ASSISTANT_SUGGESTION_COMPLETED:"生成辅助建议",DOCX_CONVERSION_COMPLETED:"Word转换完成",MATERIAL_INDEX_COMPLETED:"材料检索索引完成"})[action]||action;
}
function operationsView() {
  return `<section class="panel"><h2>运行维护</h2><p class="muted">查看项目任务与检索容量，连接与恢复由管理员在受保护环境执行。</p><div id="operations-body">${skeleton("正在读取运行指标")}</div></section>`;
}
async function loadOperationsView() {
  const pid=projectId,sequence=++managementSequence;
  try {
    const value=await api(base()+"/operations");
    if(pid!==projectId||tab!=="operations"||sequence!==managementSequence)return;
    $("#operations-body").innerHTML=`<dl class="summary-list"><div><dt>逻辑修订总量</dt><dd>${(value.revision_bytes/1024/1024).toFixed(2)} MiB</dd></div><div><dt>索引记录（含历史）</dt><dd>${value.indexes}</dd></div><div><dt>检索片段（含历史）</dt><dd>${value.chunks}</dd></div><div><dt>生成模型配置</dt><dd>${value.features.model_configured?"配置完整，待实际验证":"尚未配置"}</dd></div></dl><h3>后台任务</h3><div class="table-scroll"><table><caption class="sr-only">任务状态计数</caption><thead><tr><th scope="col">类型</th><th scope="col">状态</th><th scope="col">数量</th></tr></thead><tbody>${Object.entries(value.jobs).map(([key,count])=>`<tr><td>${esc(key.split(":")[0])}</td><td>${esc(key.split(":")[1])}</td><td>${count}</td></tr>`).join("")||`<tr><td colspan="3">暂无任务</td></tr>`}</tbody></table></div><a href="${base()}/operations/metrics" target="_blank" rel="noopener">查看受权限保护的指标文本</a><div class="divider"></div><h3>备份与恢复</h3><p>管理员通过backup_project工具生成全安装备份，核对摘要，只恢复到新的空数据库和文件目录。</p><p class="hint warning">备份包含安装数据与认证摘要，必须受保护存储。页面不会执行覆盖恢复，也不提供连接密钥。</p><p>启动、隔离恢复及旧索引清理步骤见仓库“完整启动与运维”文档。</p>`;
  } catch(error){if(pid===projectId&&tab==="operations")$("#operations-body").innerHTML=failureState(explain(error));}
}
