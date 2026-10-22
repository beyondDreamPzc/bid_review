"use strict";
let retrievalTimer = null, retrievalSequence = 0, retrievalHits = [], retrievalStatus = null;
const retrievalLabels = {DISABLED:"尚未启用",NOT_BUILT:"尚未构建",QUEUED:"排队中",RUNNING:"正在构建",RETRY_WAIT:"等待重试",SUCCEEDED:"可检索",FAILED:"构建失败"};
function retrievalView() {
  clearTimeout(retrievalTimer); retrievalSequence++; retrievalHits=[]; retrievalStatus=null;
  return `<section class="panel"><div class="heading"><div><div class="eyebrow">证据定位</div><h2>在本轮正式材料中查找原文</h2><p>输入条款关键词，定位我们的响应承诺；打开原件核对后，可带入本轮审查。</p></div></div><div id="retrieval-status" role="status">${skeleton("正在读取检索准备情况")}</div><form id="retrieval-form" class="retrieval-form"><label for="retrieval-query">要查找的内容<input id="retrieval-query" name="query" type="search" maxlength="400" required placeholder="例如：故障响应时限、培训次数、服务期限"></label><button class="primary" id="retrieval-submit" disabled>查找原文</button></form><p class="muted">只检索本轮正式响应与附件。结果按相关性排列，不代替人工判断；未命中也不能证明没有响应。</p><div id="retrieval-results" aria-live="polite">${empty("准备好索引后，输入关键词开始查找。")}</div></section>`;
}
async function loadRetrievalView() {
  const id=projectId, sequence=++retrievalSequence;
  try {
    const s=await api(`/api/v1/projects/${id}/retrieval`);
    if(id!==projectId||sequence!==retrievalSequence||tab!=="retrieval")return;
    if(retrievalStatus && retrievalHits.length && (retrievalStatus.material_set_id!==s.material_set_id || s.status!=="SUCCEEDED")) {
      retrievalHits=[]; $("#retrieval-results").innerHTML=empty("材料或索引状态已变化，请重新查找。");
    }
    retrievalStatus=s;
    $("#retrieval-status").innerHTML=`<div class="retrieval-status"><div><strong>${s.material_version?`正式材料 · 第 ${s.material_version} 套`:"还没有正式材料"}</strong> <span class="badge ${s.status==="SUCCEEDED"?"green":"amber"}">${esc(retrievalLabels[s.status]||s.status)}</span>${s.chunk_count?`<small> · ${s.chunk_count} 个原文片段 · ${s.profile.includes("rerank")?"语义与关键词混合查找":"关键词查找"}</small>`:""}${s.error_detail?`<p class="hint warning">${esc(s.error_detail)}</p>`:""}</div>${s.enabled&&s.material_set_id&&canEdit()?`<button class="small" data-build-index ${["QUEUED","RUNNING","RETRY_WAIT"].includes(s.status)?"disabled":""}>${s.status==="SUCCEEDED"?"重建索引":s.status==="FAILED"?"重试构建":"构建本轮索引"}</button>`:""}</div>${!s.material_set_id?`<p class="hint">先到“资料与版本”选择并发布正式响应材料。</p>`:!s.enabled?`<p class="hint">由管理员启用本地Milvus检索服务后即可使用。</p>`:""}`;
    $("#retrieval-submit").disabled=s.status!=="SUCCEEDED"||busy;
    if(busy) {
      $("#retrieval-submit").dataset.wasDisabled=String(s.status!=="SUCCEEDED");
      $("#retrieval-status").querySelectorAll("button").forEach(button=>{
        button.dataset.wasDisabled=String(button.disabled);button.disabled=true;
      });
    }
    clearTimeout(retrievalTimer);
    if(["QUEUED","RUNNING","RETRY_WAIT"].includes(s.status)) retrievalTimer=setTimeout(loadRetrievalView,2500);
  } catch(e) { if(sequence===retrievalSequence&&tab==="retrieval"){$("#retrieval-status").innerHTML=failureState(explain(e));notice(explain(e),true);} }
}
document.addEventListener("click",event=>{
  const el=event.target.closest("button"); if(!el||busy)return;
  if(el.hasAttribute("data-build-index")) return act(async()=>{
    const s=retrievalStatus;
    await write(base()+"/retrieval/indexes",{expected_material_set_id:s.material_set_id,retry_failed:s.status==="FAILED",rebuild:s.status==="SUCCEEDED"});
    await loadRetrievalView();
  },"索引任务已登记，完成后可检索。",false);
  if(el.dataset.useHit!==undefined) return act(async()=>{
    const hit=retrievalHits[Number(el.dataset.useHit)], materialId=retrievalStatus.material_set_id;
    const next=await api(base()+"/workbench");
    if(next.workspace.current_material_set_id!==materialId) { const error=new Error("正式材料已变化，请重新查找。");error.status=409;throw error; }
    const source=await api(`/api/v1/artifacts/${hit.source.artifact_id}/blocks/${hit.source.block_id}/source`);
    data=next;tab="review";resetPicker();picks=[source];render();dirty=true;focusContent();
  },"已将完整原文块带入当前要求，请核对要求标题并回看原件；切换要求会清空引用。",false);
});
document.addEventListener("submit",event=>{
  if(event.target.id!=="retrieval-form")return;
  event.preventDefault(); if(busy||retrievalStatus?.status!=="SUCCEEDED")return;
  const id=projectId, query=new FormData(event.target).get("query"), materialId=retrievalStatus.material_set_id;
  act(async()=>{
    const result=await api(`/api/v1/projects/${id}/retrieval/search`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_material_set_id:materialId,query,limit:5})});
    if(id!==projectId||tab!=="retrieval")return;
    retrievalHits=result.results;
    $("#retrieval-results").innerHTML=`<div class="divider"></div><h3>找到 ${result.results.length} 处相关原文</h3>${result.results.map((hit,i)=>`<article class="retrieval-hit"><div class="row"><strong>${i+1}. ${esc(hit.source.title)}</strong><span class="badge">第 ${hit.source.page} 页</span><small>${hit.source.submission_role==="FORMAL_RESPONSE"?"正式响应":"正式附件"}</small></div><div class="quote">${esc(hit.quote)}</div><div class="row"><a class="button small" href="${esc(hit.original_url)}" target="_blank" rel="noopener">打开原 PDF 对应页 ↗</a>${data.baseline?`<button class="small" data-use-hit="${i}">用于本轮核对</button>`:""}<details><summary>查看来源信息</summary><p>修订 ${esc(hit.source.revision_id)}<br>原文块 ${esc(hit.source.block_id)}<br>相关性 ${hit.score.toFixed(3)} · 不代表满足概率</p></details></div></article>`).join("")||`<div class="hint">没有召回相关原文。可换一组关键词，或打开正式材料逐页核对。</div>`}`;
  },null,false);
});
