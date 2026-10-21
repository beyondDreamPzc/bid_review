"use strict";
// 与 workspace.js 共用会话、项目与 API helper；本文件只管理质量检查页。
let qualityArtifact = "", qualityReport = null, qualityPage = 1, qualitySequence = 0;
let qualityTextOffset = 0, qualityOnlyAttention = false;
const qualityDecisions = {TEXT_USABLE:"已核对，文字可用", NEEDS_REPROCESS:"需要重新处理", BLANK_CONFIRMED:"已确认原件为空白"};

function qualityFiles() {
  return data.documents.flatMap(doc => doc.revisions.filter(r => r.artifact_id).map(r => ({
    ...r, title:doc.title, kind:doc.kind
  })));
}

function qualityView() {
  const files = qualityFiles();
  if (!files.some(f => f.artifact_id === qualityArtifact)) qualityArtifact = files[0]?.artifact_id || "";
  return `<section class="panel"><div class="heading"><div><h2>逐页核对提取结果</h2>
    <p>程序提示帮助你定位可疑页，人工核对仍须打开原件。</p></div></div>
    ${files.length ? `<label>检查文件版本<select id="quality-file" aria-label="质量检查文件版本">${files.map(f =>
      `<option value="${esc(f.artifact_id)}" ${f.artifact_id===qualityArtifact?"selected":""}>${esc(f.title)} · 第 ${f.revision_no} 版 · ${labels[f.kind]}</option>`).join("")}</select></label>
      <div id="quality-body">正在读取质量检查结果…</div>` : empty("先在资料页上传并解析 PDF，再进行逐页检查。")}</section>`;
}

async function loadQualityView() {
  const container = $("#quality-body");
  if (!container || !qualityArtifact) return;
  const sequence = ++qualitySequence, artifact = qualityArtifact;
  container.innerHTML = `<p class="muted">正在读取冻结原文及核对历史…</p>`;
  try {
    const report = await api(`/api/v1/artifacts/${artifact}/quality`);
    if (sequence !== qualitySequence || !$("#quality-body") || artifact !== qualityArtifact) return;
    qualityReport = report;
    if (!report.pages.some(p => p.page === qualityPage)) qualityPage = 1;
    renderQualityReport();
  } catch (error) {
    if (sequence === qualitySequence && $("#quality-body")) {
      $("#quality-body").innerHTML = `<div class="hint warning">质量报告未能读取。请刷新重试；不会把读取失败显示成没有问题。</div>`;
      notice(explain(error), true);
    }
  }
}

function renderQualityReport() {
  const r = qualityReport;
  $("#quality-body").innerHTML = `<div class="quality-summary">
    <span>规则警示 ${r.warning_page_count} 页</span><span>人工已核对 ${r.reviewed_page_count}/${r.page_count} 页</span>
    <span>人工标需处理 ${r.needs_reprocess_page_count} 页</span></div>
    <div class="hint">无规则提示不等于没有漏字；“解析完成”也不等于质量通过。${r.limitations.map(esc).join(" ")}</div>
    <div class="quality-layout"><div><h3>选择页面</h3>
      <label class="quality-toggle"><input type="checkbox" id="quality-filter" ${qualityOnlyAttention?"checked":""}>只看规则提醒或待处理页</label>
      <div id="quality-pages" class="quality-pages"></div></div><section id="quality-detail"></section></div>`;
  showQualityPages();
  showQualityPage();
}

function showQualityPages() {
  const pages = qualityReport.pages.filter(p => !qualityOnlyAttention || p.findings.length || p.latest_review?.decision === "NEEDS_REPROCESS");
  $("#quality-pages").innerHTML = pages.map(p => `<button class="quality-page ${p.page===qualityPage?"active":""}" data-quality-page="${p.page}">
    <strong>第 ${p.page} 页</strong> · ${p.block_count} 处文字<small>${p.findings.length?`${p.findings.length} 项规则提示`:"这些规则未发现明显异常"}</small>
    <small>${esc(p.latest_review?qualityDecisions[p.latest_review.decision]:"尚未人工核对")}</small></button>`).join("") || empty("当前没有符合筛选的页面。其余页面仍需人工核对。");
}

function showQualityPage() {
  const r = qualityReport, page = r.pages.find(p => p.page === qualityPage);
  if (!page) return;
  qualityTextOffset = 0;
  const review = page.latest_review, canWrite = ["OWNER","EDITOR","REVIEWER"].includes(data.workspace.my_role);
  $("#quality-detail").innerHTML = `<div class="heading"><div><h2>第 ${page.page} 页</h2><small>${page.character_count} 个非空白字符 · ${page.block_count} 处文字</small></div>
    <a class="button small" target="_blank" rel="noopener" href="${esc(r.original_url)}#page=${page.page}">打开本页原件 ↗</a></div>
    ${page.findings.map(f=>`<div class="finding ${f.severity==="INFO"?"info":""}"><strong>${esc(f.message)}</strong><p>${esc(f.suggestion)}</p>${f.affected_block_count?`<small>涉及 ${f.affected_block_count} 处文字，下方标出其中最多20处。</small>`:""}</div>`).join("") || `<div class="hint">这些规则未发现明显异常。表格、跨栏顺序和漏字仍未自动验证。</div>`}
    <h3>提取的原文</h3><div id="quality-text" class="quality-text">正在读取本页文字…</div>
    <div id="quality-text-actions" class="quality-text-actions"></div><div class="divider"></div>
    <h3>回看原件后的人工记录</h3>${review?`<div class="history"><strong>${esc(qualityDecisions[review.decision])}</strong><small> · ${esc(review.reviewer_name)}</small><p>${esc(review.note)}</p></div>`:`<p class="muted">此页还没有人工记录。</p>`}
    ${canWrite?`<form id="quality-review-form"><label>核对结果<select name="decision" required aria-label="本页质量核对结果">
      <option value="" selected disabled>请选择本次核对结果</option>
      <option value="TEXT_USABLE" ${!page.block_count?"disabled":""}>已回看原件，文字可用</option>
      <option value="NEEDS_REPROCESS">需要重新处理</option>
      <option value="BLANK_CONFIRMED" ${page.block_count?"disabled":""}>已确认原件这一页为空白</option></select></label>
      <label>核对说明<textarea name="note" maxlength="4000" required placeholder="说明核对了什么、是否有遗漏、需怎样处理"></textarea></label>
      <button class="primary" type="submit">保存本页核对记录</button></form>`:`<p class="hint">只读成员可查看，由负责人、编写人或审查人记录核对结果。</p>`}
    <p class="muted">检查记录仅适用于此文件此解析版本，不会自动启动 OCR 或改变业务审查结论。</p>
    <button class="small" data-quality-history="true">查看本页核对历史</button><div id="quality-history"></div>`;
  loadQualityText().catch(e=>notice(explain(e),true));
}

async function loadQualityText() {
  const artifact = qualityArtifact, page = qualityPage, offset = qualityTextOffset;
  const blocks = await api(`/api/v1/artifacts/${artifact}/blocks?page=${page}&offset=${offset}&limit=100`);
  if (tab!=="quality" || page!==qualityPage || artifact!==qualityArtifact || offset!==qualityTextOffset || !$("#quality-text")) return;
  const flagged = new Set(qualityReport.pages.find(p=>p.page===page).findings.flatMap(f=>f.block_ids));
  $("#quality-text").innerHTML = blocks.map(b=>`<div class="quality-line ${flagged.has(b.block_id)?"flagged":""}">${esc(b.text)}</div>`).join("") || empty("本页没有可提取文字，请打开原件检查内容。");
  $("#quality-text-actions").innerHTML = `${offset?`<button class="small" data-quality-offset="${Math.max(0,offset-100)}">上一组文字</button>`:""}${blocks.length===100?`<button class="small" data-quality-offset="${offset+100}">下一组文字</button>`:""}`;
}

document.addEventListener("change", event => {
  if (busy) {
    if (event.target.id === "quality-file") event.target.value = qualityArtifact;
    if (event.target.id === "quality-filter") event.target.checked = qualityOnlyAttention;
    return;
  }
  if (event.target.id === "quality-file") {
    qualityArtifact = event.target.value; qualityPage = 1; qualityReport = null;
    loadQualityView();
  }
  if (event.target.id === "quality-filter") {
    qualityOnlyAttention = event.target.checked; showQualityPages();
  }
});

document.addEventListener("click", event => {
  const button = event.target.closest("button"); if (!button || busy) return;
  if (button.dataset.qualityArtifact) {
    qualityArtifact=button.dataset.qualityArtifact; qualityPage=1; tab="quality"; draft=null;
    resetPicker(); render();
  }
  if (button.dataset.qualityPage) {
    qualityPage=Number(button.dataset.qualityPage); showQualityPages(); showQualityPage();
  }
  if (button.dataset.qualityOffset !== undefined) {
    qualityTextOffset=Number(button.dataset.qualityOffset); act(loadQualityText,null,false);
  }
  if (button.dataset.qualityHistory) act(async()=>{
    const rows=await api(`/api/v1/artifacts/${qualityArtifact}/pages/${qualityPage}/quality-reviews?limit=50`);
    $("#quality-history").innerHTML=`<p class="muted">最近50条，按版本从新到旧。</p>`+rows.map(r=>
      `<div class="history"><strong>${esc(qualityDecisions[r.decision])}</strong> · ${esc(r.reviewer_name)}<small> · 第 ${r.version} 次记录</small><p>${esc(r.note)}</p></div>`).join("");
  },null,false);
});

document.addEventListener("submit", event => {
  if (event.target.id !== "quality-review-form") return;
  event.preventDefault(); if (busy) return;
  const values=Object.fromEntries(new FormData(event.target)), page=qualityReport.pages.find(p=>p.page===qualityPage);
  act(async()=>{
    try {
      await write(`/api/v1/artifacts/${qualityArtifact}/pages/${qualityPage}/quality-reviews`,{
        ...values, expected_version:page.latest_review?.version || 0,
        expected_diagnostic_profile:qualityReport.diagnostic_profile
      });
    } catch(error) {
      if(error.status===409) await loadQualityView();
      throw error;
    }
    await loadQualityView();
  },"本页核对已记录，历史意见保留。",false);
});
