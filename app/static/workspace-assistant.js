"use strict";
let assistantTimer=null,assistantSequence=0,assistantConfig=null,assistantRuns=[],assistantRunId="";
const assistantStates={QUEUED:"排队中",RUNNING:"检查中",RETRY_WAIT:"等待重试",SUCCEEDED:"建议已生成",FAILED:"检查未完成",CANCELLED:"已取消"};
function assistantView() {
  return `<div class="workspace-columns"><section class="panel"><h2>依据正式材料生成辅助建议</h2><p class="muted">先查找证据，再生成可回看的分析。建议不会直接变成审核结论。</p><div id="assistant-form-body">${skeleton("正在读取模型配置")}</div></section><section class="panel"><div class="section-heading"><h2>本项目建议记录</h2><button class="small" data-assistant-refresh>刷新</button></div><div id="assistant-run-list">${skeleton("正在读取任务")}</div></section></div><section class="panel assistant-result" id="assistant-result"></section>`;
}
function assistantForm() {
  const config=assistantConfig,requirements=data.baseline?.requirements||[],check=canReview()&&requirements.length;
  return `<div class="hint ${config.configured?"":"warning"}">${config.configured?`模型 ${esc(config.model)}<br>内容处理目的地 ${esc(config.provider_origin)}`:esc(config.reason)}</div><form id="assistant-form"><fieldset ${config.configured&&data.material_set?"":"disabled"}><label>需要怎样的帮助<select id="assistant-kind" name="kind"><option value="QUESTION" ${!check?"selected":""}>从材料中回答问题</option>${check?`<option value="REQUIREMENT_CHECK" selected>逐项检查当前要求</option>`:""}</select></label><label id="assistant-question-label" ${check?"hidden":""}>待核对的问题<textarea name="question" maxlength="400" ${!check?"required":""} placeholder="例如：我们的方案承诺多久到场处理故障？"></textarea></label>${check?`<label id="assistant-requirement-label">本轮基线要求<select name="requirement_revision_id">${requirements.map(r=>`<option value="${esc(r.revision_id)}" ${r.requirement_id===selectedRequirement?"selected":""}>${esc(r.title)}</option>`).join("")}</select></label>`:""}<label class="checkbox-label"><input type="checkbox" name="consent" required><span>我允许将本次问题或要求，以及最多6处匹配的正式响应片段发送到上方模型服务，用于本次辅助检查。</span></label><button class="primary" type="submit">生成带出处的建议</button></fieldset></form>${!data.material_set?`<p class="hint">请先在资料页确定正式材料，并构建本轮检索索引。</p>`:""}<p class="field-help">证据不足会明确提示。引用有效不代表分析一定正确，最终仍需回看原件并由人判断。</p>`;
}
async function loadAssistantView() {
  clearTimeout(assistantTimer);const pid=projectId,sequence=++assistantSequence;
  try {
    const [config,runs]=await Promise.all([api("/api/v1/assistant/config"),api(`/api/v1/projects/${pid}/assistant-runs`)]);
    if(pid!==projectId||tab!=="assistant"||sequence!==assistantSequence)return;
    const changed=assistantConfig&&assistantConfig.config_fingerprint!==config.config_fingerprint;
    assistantConfig=config;assistantRuns=runs;
    const form=$("#assistant-form-body");
    if(changed||!form.querySelector("form"))form.innerHTML=assistantForm();
    if(changed)notice("模型处理目的地或配置已变化，请重新确认本次发送授权。",true);
    if(!runs.some(r=>r.id===assistantRunId))assistantRunId=runs[0]?.id||"";
    $("#assistant-run-list").innerHTML=runs.map(run=>`<button class="run-row ${run.id===assistantRunId?"selected":""}" data-assistant-run="${esc(run.id)}"><span><strong>${esc(run.question.slice(0,60))}</strong><small>${run.kind==="QUESTION"?"证据问答":"逐项检查"}${run.freshness==="STALE"?" / 输入已变化":""}</small></span><span class="badge ${run.status==="SUCCEEDED"?"green":"amber"}">${esc(assistantStates[run.status]||run.status)}</span></button>`).join("")||emptyState("还没有辅助建议","确认处理目的地后，发起本项目的第一次问答或检查。");
    renderAssistantResult();
    if(runs.some(r=>["QUEUED","RUNNING","RETRY_WAIT"].includes(r.status)))assistantTimer=setTimeout(loadAssistantView,2500);
  } catch(error){if(pid===projectId&&tab==="assistant"){$("#assistant-run-list").innerHTML=failureState(explain(error));notice(explain(error),true);}}
}
function renderAssistantResult() {
  const run=assistantRuns.find(r=>r.id===assistantRunId),box=$("#assistant-result");if(!box)return;
  if(!run){box.innerHTML=emptyState("选择一条建议查看证据","模型建议和实际整改记录分别保存。");return;}
  const output=run.result.output,active=["QUEUED","RUNNING","RETRY_WAIT"].includes(run.status);
  box.innerHTML=`<div class="section-heading"><h2>${run.kind==="QUESTION"?"证据问答":"逐项检查建议"}</h2><div class="row">${active?`<button class="small" data-assistant-control="CANCEL">取消任务</button>`:""}${run.status==="FAILED"&&run.freshness==="CURRENT"?`<button class="small" data-assistant-control="RETRY">重试检查</button>`:""}</div></div><p class="quote">${esc(run.question)}</p>${run.freshness==="STALE"?`<p class="hint warning">输入或问题代次已变化。此结果仅供追溯，请按当前版本重新生成。</p>`:""}${active?skeleton("后台正在检索并分析证据"):run.error_detail?`<p class="hint warning">${esc(run.error_detail)}</p>`:""}${output?`<h3>${esc(labels[output.verdict]||output.verdict)}</h3><p class="assistant-answer">${esc(output.answer)}</p><h3>引用的响应证据</h3>${run.sources.filter(s=>output.citations.includes(s.id)).map(s=>`<article class="evidence-hit"><div class="row"><strong>依据 ${esc(s.id.slice(1))} / ${esc(s.source.title)}</strong><span class="badge">第 ${s.source.page} 页</span></div><blockquote class="quote">${esc(s.quote)}</blockquote><a class="button small" target="_blank" rel="noopener" href="${esc(s.original_url)}">打开对应原件页</a></article>`).join("")||`<p class="hint">没有足够的可引用证据，请人工检查正式材料。</p>`}${run.result.adopted_issue_id?`<p class="hint">此建议已人工采纳为整改问题，后续仍需独立复核。</p>`:run.kind==="REQUIREMENT_CHECK"&&output.verdict!=="SUPPORTED"&&run.freshness==="CURRENT"&&canReview()?`<button class="primary" data-adopt-assistant>人工核对并登记整改</button>`:""}<details><summary>查看本次召回上下文</summary>${run.sources.map(s=>`<p>依据${esc(s.id.slice(1))} / 第${s.source.page}页</p><div class="quote">${esc(s.quote)}</div>`).join("")}</details>`:""}`;
}
document.addEventListener("submit",event=>{
  if(event.target.id!=="assistant-form")return;event.preventDefault();if(busy)return;
  const values=Object.fromEntries(new FormData(event.target)),check=values.kind==="REQUIREMENT_CHECK";
  act(async()=>{
    const run=await write(base()+"/assistant-runs",{kind:values.kind,question:check?"":values.question,
      requirement_revision_id:check?values.requirement_revision_id:null,expected_epoch:data.workspace.review_epoch,
      expected_material_set_id:data.workspace.current_material_set_id,consent:values.consent==="on",config_fingerprint:assistantConfig.config_fingerprint});
    assistantRunId=run.id;dirty=false;event.target.elements.question.value="";event.target.elements.consent.checked=false;await loadAssistantView();
  },"已登记辅助检查任务，结果需要人工核对。",false);
});
document.addEventListener("click",event=>{
  const el=event.target.closest("button");if(!el||busy)return;
  if(el.hasAttribute("data-assistant-refresh"))return loadAssistantView();
  if(el.dataset.assistantRun){assistantRunId=el.dataset.assistantRun;renderAssistantResult();focusContent("#assistant-result h2");return;}
  if(el.dataset.assistantControl){const run=assistantRuns.find(r=>r.id===assistantRunId);return act(async()=>{
    await write(base()+`/assistant-runs/${run.id}/control`,{action:el.dataset.assistantControl,expected_status:run.status});await loadAssistantView();
  },"任务状态已更新。",false);}
  if(el.hasAttribute("data-adopt-assistant"))adoptAssistantDialog();
});
document.addEventListener("change",event=>{
  if(event.target.id!=="assistant-kind")return;
  const check=event.target.value==="REQUIREMENT_CHECK";
  $("#assistant-question-label").hidden=check;$("#assistant-question-label textarea").required=!check;
  if($("#assistant-requirement-label"))$("#assistant-requirement-label").hidden=!check;
});
function adoptAssistantDialog() {
  const run=assistantRuns.find(r=>r.id===assistantRunId),req=data.baseline.requirements.find(r=>r.revision_id===run.requirement_revision_id);
  const evidence=run.sources.filter(s=>run.result.output.citations.includes(s.id));
  openDialog({title:"人工确认问题并安排整改",description:"请自行核对要求和原件，修改分析中不准确的内容。采纳只登记普通问题与任务，不代表模型最终判定。",submitLabel:"确认登记整改",
    body:`<label>问题标题<input name="title" required maxlength="200" value="${esc(req.title+"：待核对缺口")}"></label><label>人工核对说明<textarea name="description" required maxlength="8000">${esc(run.result.output.answer)}</textarea></label><label>问题类型<select name="kind"><option value="MISSING_EVIDENCE">缺少证明</option><option value="CONFLICT">承诺冲突</option><option value="MISSING_RESPONSE">缺少响应</option><option value="OTHER">其他</option></select></label><label>优先级<select name="severity"><option value="HIGH">高</option><option value="MEDIUM">中</option><option value="LOW">低</option></select></label><label>整改负责人<select name="assignee_id">${data.members.filter(m=>["OWNER","EDITOR"].includes(m.role)).map(m=>`<option value="${esc(m.user_id)}">${esc(m.name)}</option>`).join("")}</select></label>${evidence.map(s=>`<label class="checkbox-label"><input type="checkbox" name="evidence:${s.id}" checked><span>引用依据${esc(s.id.slice(1))}：第${s.source.page}页 ${esc(s.quote.slice(0,160))}</span></label>`).join("")}`,
    onSubmit:values=>act(async()=>{
      const seen=new Set(),refs=evidence.filter(s=>values["evidence:"+s.id]).flatMap(s=>{const key=s.source.artifact_id+":"+s.source.block_id;if(seen.has(key))return [];seen.add(key);return [{artifact_id:s.source.artifact_id,block_id:s.source.block_id}];});
      await write(base()+`/assistant-runs/${run.id}/adopt`,{expected_epoch:data.workspace.review_epoch,
        requirement_revision_id:run.requirement_revision_id,title:values.title,description:values.description,
        kind:values.kind,severity:values.severity,assignee_id:values.assignee_id,evidence:refs});
    },"已登记整改问题，请由实际负责人处理。")});
}
