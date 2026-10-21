"use strict";
// 这里只调用项目 API，不接收或存储模型密钥。
let aiConfig=null, aiArtifact="", aiQuality=null, aiRuns=[], aiRun="", aiRows=[], aiOffset=0;
let aiSequence=0, aiTimer=null;
const aiStates={QUEUED:"等待抽取",RUNNING:"抽取中",RETRY_WAIT:"等待自动重试",SUCCEEDED:"候选已生成",FAILED:"抽取失败",CANCELLED:"已取消",PENDING:"待人工核对",IMPORTED:"已采纳为草稿",REJECTED:"已忽略"};

function aiFiles() {
  return data.documents.filter(d=>["TENDER","AMENDMENT"].includes(d.kind)).flatMap(d=>{
    const r=d.revisions[0];
    return r?.artifact_id?[{...r,title:d.title,kind:d.kind}]:[];
  });
}

function extractionView() {
  return `<section class="panel"><h2>从招标原文整理要求候选</h2><p class="muted">选择已核对文字可用的页面，后台生成有出处的建议，再由人修改和采纳。</p>
    <div id="ai-body"><p class="muted">正在读取模型配置与抽取记录…</p></div></section>`;
}

async function loadExtractionView() {
  clearTimeout(aiTimer);
  const sequence=++aiSequence, pid=projectId;
  try {
    const [config,runs]=await Promise.all([api("/api/v1/extraction/config"),api(base()+"/extraction-runs?limit=30")]);
    if(sequence!==aiSequence||pid!==projectId||tab!=="ai"||!$("#ai-body"))return;
    aiConfig=config;aiRuns=runs;
    const files=aiFiles();
    if(!files.some(f=>f.artifact_id===aiArtifact))aiArtifact=files[0]?.artifact_id||"";
    if(!aiRuns.some(r=>r.id===aiRun))aiRun=aiRuns[0]?.id||"";
    const pageQuality=aiArtifact?await api(`/api/v1/artifacts/${aiArtifact}/quality`):null;
    if(sequence!==aiSequence||tab!=="ai"||pid!==projectId)return;
    aiQuality=pageQuality;
    aiOffset=0; await loadAiCandidates();
    if(sequence!==aiSequence||tab!=="ai"||pid!==projectId)return;
    $("#ai-body").innerHTML=`<div class="hint ${aiConfig.configured?"":"warning"}">${aiConfig.configured?
      `模型：${esc(aiConfig.model)}<br>原文处理目的地：${esc(aiConfig.provider_origin)}`:esc(aiConfig.reason)}</div>
      <div class="grid"><section><h3>发起一次抽取</h3>${aiCreateForm(files)}</section><section><h3>抽取记录</h3>
      <p class="muted">最近30条任务；已完成批次在重试时保留。失败、取消或过期不会自动创建正式要求。</p>
      <div id="ai-run-list"></div><div id="ai-run-status"></div></section></div><div class="divider"></div>
      <div class="heading"><h2>逐项人工核对候选</h2><button class="small" data-ai-refresh="true">刷新任务与候选</button></div><div id="ai-candidates"></div>`;
    renderAiRun();renderAiCandidates();scheduleAiPoll();
  } catch(error) {
    if(sequence===aiSequence&&$("#ai-body"))$("#ai-body").innerHTML=`<div class="hint warning">抽取信息未能读取，请刷新项目重试。未生成任何模拟结果。</div>`;
    notice(explain(error),true);
  }
}

function aiCreateForm(files) {
  if(!files.length)return empty("先上传并解析最新招标或更正 PDF。");
  if(!canEdit())return empty("由负责人或编写人发起抽取。你可以查看右侧任务与下方候选。");
  return `<form id="ai-create-form"><label>招标文件的最新修订<select id="ai-file" aria-label="抽取文件版本">${files.map(f=>
    `<option value="${esc(f.artifact_id)}" ${f.artifact_id===aiArtifact?"selected":""}>${esc(f.title)} · 第 ${f.revision_no} 版</option>`).join("")}</select></label>
    <p class="muted">本次最多10页、48000字符。页级意见或文件版本变化后，旧候选需重新抽取。</p>
    <div class="ai-page-list">${aiQuality.pages.map(p=>{const ready=p.latest_review?.decision==="TEXT_USABLE";return `<label class="quality-toggle"><input type="checkbox" name="page" value="${p.page}" ${ready?"":"disabled"}>
      第 ${p.page} 页 · ${p.character_count} 字符 · ${ready?"已人工核对文字可用":"须先完成质量核对"}</label>`;}).join("")}</div>
    <button type="button" class="small" data-quality-artifact="${esc(aiArtifact)}">去核对该文件的解析质量</button>
    <label class="quality-toggle"><input type="checkbox" name="consent" required ${aiConfig.configured?"":"disabled"}>我确认所选页面原文可发送给上方展示的模型服务</label>
    <button class="primary" type="submit" ${!aiConfig.configured?"disabled":""}>生成待审要求候选</button></form>`;
}

async function loadAiCandidates() {
  const pid=projectId,rid=aiRun,offset=aiOffset;
  const rows=rid?await api(base()+`/requirement-candidates?run_id=${encodeURIComponent(rid)}&offset=${offset}&limit=50`):[];
  if(pid===projectId&&rid===aiRun&&offset===aiOffset)aiRows=rows;
}

function renderAiRun() {
  $("#ai-run-list").innerHTML=aiRuns.length?`<label>选择抽取记录<select id="ai-run" aria-label="抽取记录">${aiRuns.map((r,i)=>
    `<option value="${esc(r.id)}" ${r.id===aiRun?"selected":""}>${i+1}. 第 ${r.pages.join("、")} 页 · ${aiStates[r.status]||r.status}</option>`).join("")}</select></label>`:empty("还没有抽取任务，未配置模型时可以继续手工整理要求。");
  const r=aiRuns.find(r=>r.id===aiRun);
  if(!r){$("#ai-run-status").innerHTML="";return;}
  $("#ai-run-status").innerHTML=`<div class="history"><strong>${esc(aiStates[r.status]||r.status)}</strong><p>已完成 ${r.completed_batch_count}/${r.batch_count} 批 · 第 ${r.attempt} 次执行</p>
    <small>${esc(r.model)} · ${esc(r.provider_origin)}</small>${r.freshness==="STALE"?`<div class="hint warning">输入已变化，旧候选不能直接采纳，请重新核对最新文件后抽取。</div>`:""}
    ${r.error_detail?`<p class="hint warning">${esc(r.error_detail)}</p>`:""}
    <div class="row">${canEdit()&&["QUEUED","RUNNING","RETRY_WAIT"].includes(r.status)?`<button class="small" data-ai-cancel="true">取消后续处理</button>`:""}
    ${canEdit()&&r.status==="FAILED"&&r.freshness==="CURRENT"?`<button class="small" data-ai-retry="true">重试未完成批次</button>`:""}</div></div>
    <p class="muted">取消不保证撤回已发出的云端请求。超时或手工重试可能再次产生未完成批次的调用费用。</p>`;
}

function renderAiCandidates() {
  const container=$("#ai-candidates");if(!container)return;
  container.innerHTML=aiRows.length?aiRows.map(c=>{const p=c.proposed;return `<article class="req ai-candidate"><div class="row"><h3>${esc(p.title)}</h3><span class="badge">${esc(aiStates[c.status])}</span></div>
    <p>${esc(p.text)}</p><p class="muted">模型建议理由：${esc(p.rationale)}。这不是已确认事实。</p>${sourceQuotes(c.sources)}
    ${c.freshness==="STALE"?`<div class="hint warning">来源文件或页级质量意见已变化，当前只可忽略旧候选。</div>`:""}
    ${c.status==="PENDING"&&canEdit()?`<form class="ai-decision-form" data-ai-candidate="${esc(c.id)}"><label>核对后的标题<input name="title" required maxlength="200" value="${esc(p.title)}"></label>
      <label>核对后的完整要求<textarea name="text" required maxlength="8000">${esc(p.text)}</textarea></label><div class="row"><label>类别<select name="category">${Object.entries({TECHNICAL:"技术",QUALIFICATION:"资质",DELIVERY:"交付",FORMAT:"格式",OTHER:"其他"}).map(([v,n])=>`<option value="${v}" ${p.category===v?"selected":""}>${n}</option>`).join("")}</select></label>
      <label>重要性<select name="priority">${Object.entries({MANDATORY:"必须满足",SCORING:"评分项",GENERAL:"一般要求"}).map(([v,n])=>`<option value="${v}" ${p.priority===v?"selected":""}>${n}</option>`).join("")}</select></label></div>
      <label>人工核对或忽略说明<textarea name="note" required maxlength="4000"></textarea></label><div class="row"><button type="submit" class="primary" value="IMPORT" ${c.freshness==="STALE"?"disabled":""}>采纳为待确认草稿</button>
      <button type="submit" value="REJECT" formnovalidate>忽略此候选</button></div></form>`:c.status==="IMPORTED"?`<p class="hint">已关联到要求清单的草稿。请到“整理要求”确认后，再显式发布基线。</p>`:c.status==="REJECTED"?`<p class="muted">人工忽略意见：${esc(c.review?.note)}</p>`:""}</article>`;}).join(""):
    empty(aiRun?"本页还没有候选。请查看任务状态；成功但候选为空也不代表已覆盖全部要求。":"选择抽取任务后查看候选。");
  container.innerHTML+=`<div class="row">${aiOffset?`<button class="small" data-ai-offset="${Math.max(0,aiOffset-50)}">上一页候选</button>`:""}${aiRows.length===50?`<button class="small" data-ai-offset="${aiOffset+50}">下一页候选</button>`:""}</div>`;
}

function scheduleAiPoll() {
  clearTimeout(aiTimer);
  const r=aiRuns.find(r=>r.id===aiRun), pid=projectId, rid=aiRun;
  if(!r||!["QUEUED","RUNNING","RETRY_WAIT"].includes(r.status))return;
  aiTimer=setTimeout(async()=>{
    if(tab!=="ai"||pid!==projectId||rid!==aiRun)return;
    if(busy){scheduleAiPoll();return;}
    try {
      const updated=await api(base()+`/extraction-runs/${rid}`);
      if(tab!=="ai"||pid!==projectId||rid!==aiRun||busy)return;
      aiRuns=aiRuns.map(r=>r.id===rid?updated:r);renderAiRun();
      if(!["QUEUED","RUNNING","RETRY_WAIT"].includes(updated.status)){await loadAiCandidates();if(tab==="ai"&&pid===projectId&&rid===aiRun)renderAiCandidates();}
      scheduleAiPoll();
    }catch(error){notice(explain(error),true);}
  },2500);
}

document.addEventListener("change",event=>{
  if(event.target.id==="ai-file"){
    if(busy){event.target.value=aiArtifact;return;}
    aiArtifact=event.target.value;loadExtractionView();
  }
  if(event.target.id==="ai-run"){
    if(busy){event.target.value=aiRun;return;}
    aiRun=event.target.value;aiOffset=0;
    act(async()=>{await loadAiCandidates();renderAiRun();renderAiCandidates();scheduleAiPoll();},null,false);
  }
});

document.addEventListener("click",event=>{
  const button=event.target.closest("button");if(!button||busy)return;
  if(button.dataset.aiRefresh)return act(loadExtractionView,"抽取记录已刷新",false);
  if(button.dataset.aiOffset!==undefined){aiOffset=Number(button.dataset.aiOffset);return act(async()=>{await loadAiCandidates();renderAiCandidates();},null,false);}
  if(button.dataset.aiCancel||button.dataset.aiRetry){const r=aiRuns.find(r=>r.id===aiRun);return act(async()=>{
    await write(base()+`/extraction-runs/${r.id}/${button.dataset.aiCancel?"cancel":"retry"}`,{expected_attempt:r.attempt});await loadExtractionView();
  },"任务状态已更新",false);}
});

document.addEventListener("submit",event=>{
  const form=event.target;
  if(form.id!=="ai-create-form"&&!form.classList.contains("ai-decision-form"))return;
  event.preventDefault();if(busy)return;
  const values=Object.fromEntries(new FormData(form));
  if(form.id==="ai-create-form"){
    const pages=[...form.querySelectorAll('input[name="page"]:checked')].map(v=>Number(v.value));
    return act(async()=>{
      if(!pages.length||pages.length>10)throw new Error("请选择1至10页已核对文字可用的页面。");
      const r=await write(base()+"/extraction-runs",{artifact_id:aiArtifact,pages,
        expected_config_fingerprint:aiConfig.config_fingerprint,acknowledge_external_processing:values.consent==="on"});
      aiRun=r.id;await loadExtractionView();
    },"抽取任务已创建，请等待后台处理。",false);
  }
  const candidate=aiRows.find(c=>c.id===form.dataset.aiCandidate), action=event.submitter.value;
  act(async()=>{
    if(!values.note.trim())throw new Error("请填写人工核对或忽略说明。");
    await write(base()+`/requirement-candidates/${candidate.id}/decisions`,{expected_version:candidate.version,
      action,note:values.note,requirement:action==="IMPORT"?{title:values.title,text:values.text,category:values.category,priority:values.priority}:null});
    // 采纳创建了新要求，更新工作台快照，保证切到“整理要求”能立即看到草稿。
    if(action==="IMPORT")data=await api(base()+"/workbench");
    await loadAiCandidates();renderAiCandidates();
  },action==="IMPORT"?"已采纳为要求草稿，请继续到整理要求页核对并确认。":"已记录忽略意见。",false);
});
