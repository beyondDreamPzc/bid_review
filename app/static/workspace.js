"use strict";
// 仅操作现有业务 API。登录密钥不进入 URL、localStorage 或 sessionStorage。
const root = document.querySelector("#workspace"), identity = document.querySelector("#identity");
const $ = (selector) => document.querySelector(selector);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const labels = {OWNER:"负责人",EDITOR:"编写人",REVIEWER:"审查人",READER:"只读成员",TENDER:"招标文件",AMENDMENT:"更正文件",RESPONSE:"投标响应",EVIDENCE:"证明材料",DRAFT:"待确认",CONFIRMED:"已确认",TODO:"待整改",IN_PROGRESS:"整改中",SUBMITTED:"待复核",ACCEPTED:"已验收",RETURNED:"已退回",NEEDS_RECHECK:"需重新核对",OPEN:"待整改",RESOLVED:"已解决",UNREVIEWED:"未核对",ISSUES_OPEN:"有未解决问题",NEEDS_REVIEW:"待最终确认",REVIEWED:"已人工确认",NOT_READY:"尚未准备好审查输入",IN_REVIEW:"核对中",REVIEW_COMPLETE:"本轮人工核对完成",QUEUED:"排队中",RUNNING:"解析中",RETRY_WAIT:"等待重试",SUCCEEDED:"解析完成",FAILED:"解析失败",CONFIRMED_SATISFIED:"人工确认满足",CONFIRMED_ISSUE:"人工确认有问题",NOT_APPLICABLE:"不适用",ACCEPT:"验收通过",RETURN:"退回修改"};
const tag = (v) => `<span class="badge ${["REVIEWED","CONFIRMED","ACCEPTED","REVIEW_COMPLETE","SUCCEEDED","RESOLVED"].includes(v)?"green":"amber"}">${esc(labels[v] || v)}</span>`;
let user = null, projects = [], projectId = null, data = null, tab = "files", busy = false, pollTimer = null;
let draft = null, selectedRequirement = null, selectedTask = null, picks = [], pickerMode = "tender", pickerArtifact = "", pickerPage = 1, pickerOffset = 0, pickerSequence = 0;
const pendingKeys = new Map();
function notice(message, error = false) { const box = $("#notice"); box.textContent = message; box.className = error ? "error" : ""; box.hidden = false; clearTimeout(notice.timer); notice.timer = setTimeout(() => {box.hidden = true;}, error ? 12000 : 5000); }
function explain(error) {
  if (error.status === 409) return "项目或任务状态已变化。已刷新资料，请重新核对后再操作。";
  if (error.status === 403) return "当前账号不能执行此操作；整改提交人不能复核自己的提交。";
  if (error.status === 422) return "请检查必填内容、所选原文及文件格式后重试。";
  if (error.status === 413) return "PDF 超过当前 50 MiB 上传上限。";
  if (error.status === 415) return "目前只接收 PDF 文件。";
  return error.message || "操作未完成，请稍后重试。";
}
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {credentials:"same-origin", cache:"no-store", ...options}); }
  catch { const e = new Error("网络连接中断，请重试同一操作。"); e.transport = true; throw e; }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const e = new Error(typeof body.detail === "string" ? body.detail : "请求未能完成。"); e.status = response.status;
    if (response.status === 401) { user = null; data = null; projectId = null; clearTimeout(pollTimer); renderLogin(); }
    throw e;
  }
  return response.json();
}
async function write(path, body, multipart = false) {
  // 网络失败后用户重试同一内容时保留幂等键，避免登记两次问题/修订。
  const fingerprint = multipart ? JSON.stringify([...body.entries()].map(([k,v]) => [k, v instanceof File ? [v.name,v.size,v.lastModified] : v])) : JSON.stringify(body);
  const scope = path + fingerprint;
  const key = pendingKeys.get(scope) || crypto.randomUUID(); pendingKeys.set(scope, key);
  try {
    const result = await api(path, {method:"POST", headers:{"Idempotency-Key":key, ...(multipart?{}:{"Content-Type":"application/json"})}, body: multipart ? body : fingerprint});
    pendingKeys.delete(scope); return result;
  } catch (error) { if (error.status && error.status < 500) pendingKeys.delete(scope); throw error; }
}
function setBusy(value) { busy = value; root.setAttribute("aria-busy", String(value)); document.querySelectorAll("button").forEach(b => {if (value) {b.dataset.wasDisabled = String(b.disabled); b.disabled = true;} else {b.disabled = b.dataset.wasDisabled === "true"; delete b.dataset.wasDisabled;}}); }
async function act(work, message, reload = true) {
  if (busy) return;
  setBusy(true);
  try { await work(); if (reload && projectId) await loadProject(); if (message) notice(message); }
  catch (e) { if (e.status === 409 && projectId) await loadProject().catch(() => {}); notice(explain(e), true); }
  finally {setBusy(false);}
}
function head() { identity.innerHTML = user ? `<span>${esc(user.name)}</span><button class="plain" data-action="home">我的项目</button><button class="plain" data-action="logout">退出</button>` : `<a href="/">体验样例 →</a>`; }
function renderLogin() {
  head(); root.setAttribute("aria-busy","false");
  root.innerHTML = `<section class="login"><div class="eyebrow">从自己的资料开始</div><h1>进入我的项目</h1><p class="intro">上传招标和响应文件，把每项要求、原文依据与整改结果留在同一个项目里。</p><div class="panel"><form id="login-form"><label>账号访问密钥<input type="password" name="api_key" required autocomplete="off" placeholder="输入管理员提供的访问密钥"></label><button class="primary" type="submit">登录工作台</button></form><div class="divider"></div><details><summary>本地第一次使用，密钥在哪里？</summary><p>项目目录的 .env 文件中，BID_BOOTSTRAP_API_KEY 对应初始负责人账号。只在这里输入它。其他协作账号由管理员使用项目 CLI 创建。</p></details></div><p class="intro"><a href="/">先用构造样例了解流程 →</a></p></section>`;
}
async function home() { clearTimeout(pollTimer); projectId = null; data = null; pickerSequence++; projects = await api("/api/v1/projects"); head(); root.innerHTML = `<div class="heading"><div><div class="eyebrow">项目空间</div><h1>我的项目</h1><p>每个项目独立保存资料、要求、问题和核对记录。</p></div><a class="button" href="/">查看流程演示</a></div><section class="panel"><form id="project-form" class="row"><label>新项目名称<input name="name" maxlength="200" required placeholder="例如：服务平台运维投标"></label><button class="primary" type="submit">创建项目</button></form></section><div class="divider"></div>${projects.length?`<div class="cards">${projects.map(p=>`<button class="panel project-card" data-project="${esc(p.id)}"><h2>${esc(p.name)}</h2><span class="muted">进入项目 →</span></button>`).join("")}</div>`:`<div class="empty">还没有项目。先创建一个，再上传你自己的 PDF。</div>`}`; }
const base = () => `/api/v1/projects/${projectId}`;
const canEdit = () => ["OWNER","EDITOR"].includes(data.workspace.my_role);
const canReview = () => ["OWNER","REVIEWER"].includes(data.workspace.my_role);
const who = id => data.members.find(m=>m.user_id===id)?.name || "历史成员";
const empty = text => `<div class="empty">${esc(text)}</div>`;
function resetPicker() { picks = []; pickerArtifact = ""; pickerPage = 1; pickerOffset = 0; pickerSequence++; }
async function openProject(id) { projectId = id; tab = "files"; draft = null; selectedRequirement = selectedTask = null; resetPicker(); await loadProject(); }
function processing() {
  return data.documents.some(d => d.revisions.some(r => r.job_status && !["SUCCEEDED", "FAILED"].includes(r.job_status)));
}
async function loadProject() {
  clearTimeout(pollTimer);
  const id = projectId;
  const next = await api(`/api/v1/projects/${id}/workbench`);
  if (id !== projectId) return;
  data = next;
  render();
  schedulePoll(id);
}
function schedulePoll(id) {
  clearTimeout(pollTimer);
  if (!processing()) return;
  pollTimer = setTimeout(async () => {
    if (projectId !== id) return;
    if (busy) { schedulePoll(id); return; }
    try {
      const fresh = await api(`/api/v1/projects/${id}/workbench`);
      if (projectId !== id || busy) { if (projectId === id) schedulePoll(id); return; }
      data = fresh;
      // Poll only file progress, leaving unsaved upload/requirement/decision forms intact.
      if (tab === "files") {
        const list = $("#file-list");
        if (list) list.innerHTML = fileList();
        const selector = $("#materials-selector");
        if (selector && selector.dataset.dirty !== "true") selector.innerHTML = materialForm();
      }
      if (!processing()) notice("PDF 解析完成，可选择出处与正式版本。");
      schedulePoll(id);
    } catch (error) { notice(explain(error), true); }
  }, 2500);
}
function fileList() {
  return data.documents.length ? data.documents.map(d => `<article class="file"><h3>${esc(d.title)} <span class="badge">${labels[d.kind]}</span></h3>${versionView(d.revisions[0])}${d.revisions.length > 1 ? `<details><summary>查看 ${d.revisions.length - 1} 个历史版本</summary>${d.revisions.slice(1).map(versionView).join("")}</details>` : ""}</article>`).join("") : empty("尚无文件。先上传招标文件与投标响应。");
}
function render() {
  if (!data) return; head(); pickerSequence++;
  const w = data.workspace, sections = [["files","01 资料与版本"],["quality","解析质量"],["ai","AI 要求候选"],["retrieval","证据检索"],["requirements","02 整理要求"],["review","03 本轮审查"],["tasks","04 整改复核"],["report","05 检查报告"],["members","成员"]];
  root.innerHTML = `<div class="heading"><div><div class="eyebrow">我的项目 / ${esc(labels[w.my_role])}</div><h1>${esc(w.name)}</h1><p>要求基线：${data.baseline?`第 ${data.baseline.version} 版`:"未发布"}　·　正式材料：${data.material_set?`第 ${data.material_set.version} 套`:"未选择"}</p></div><button class="small" data-action="refresh">刷新项目</button></div><div class="project-shell"><nav class="nav" aria-label="项目步骤">${sections.map(([id,label])=>`<button data-tab="${id}" class="${tab===id?"active":""}" ${tab===id?'aria-current="page"':""}>${label}</button>`).join("")}</nav><div class="project-content"><label class="step-select">当前工作步骤<select id="workspace-step">${sections.map(([id,label])=>`<option value="${id}" ${tab===id?"selected":""}>${label}</option>`).join("")}</select></label>${w.pending_requirement_changes?`<div class="hint warning">要求有尚未发布的变化。请先确认最新录入内容，再发布要求基线；当前报告仍按已发布版本核对。</div>`:""}<div id="section">${({files:filesView,quality:qualityView,ai:extractionView,retrieval:retrievalView,requirements:requirementsView,review:reviewView,tasks:tasksView,report:reportView,members:membersView}[tab])()}</div></div></div>`;
  if ($("#source-picker")) loadPicker().catch(e=>notice(explain(e),true));
  if (tab === "quality") loadQualityView();
  if (tab === "ai") loadExtractionView();
  if (tab === "retrieval") loadRetrievalView();
  if (busy) root.querySelectorAll("button").forEach(b=>{b.dataset.wasDisabled=String(b.disabled); b.disabled=true;});
}
function filesView() {
  return `<div class="grid"><section class="panel"><h2>项目资料</h2><p class="muted">保留每次上传的原件。上传新版后，还需要在右侧明确选择本轮采用的版本。</p><div class="divider"></div>${canEdit()?`<details class="upload-panel" ${data.documents.length?"":"open"}><summary>上传 PDF 或追加文件版本</summary><form id="upload-form"><label>保存为<select name="document_id"><option value="">一份新文档</option>${data.documents.map(d=>`<option value="${esc(d.id)}">${esc(d.title)} · 上传新版</option>`).join("")}</select></label><div id="new-document-fields"><label>文档名称<input name="title" maxlength="200" placeholder="例如：招标文件正文"></label><label>资料类型<select name="kind">${["TENDER","AMENDMENT","RESPONSE","EVIDENCE"].map(k=>`<option value="${k}">${labels[k]}</option>`).join("")}</select></label></div><label>选择 PDF<input name="file" type="file" accept="application/pdf,.pdf" required></label><button class="primary" type="submit">上传并解析</button><p class="muted">最大 50 MiB、300 页。新上传使用已配置的 MinerU；扫描件首次运行可能需下载模型，解析后仍须检查文字。</p></form></details><div class="divider"></div>`:""}<div id="file-list">${fileList()}</div></section><section class="panel"><h2>本轮采用哪些响应材料？</h2><p class="muted">至少选择一份正式投标响应。模板、旧文件可以不选；参考材料不能作为满足要求的正式证据。</p><div id="materials-selector">${materialForm()}</div></section></div>`;
}
function versionView(r) { return `<div class="version"><div class="row"><strong>第 ${r.revision_no} 版</strong>${tag(r.job_status || r.status)}${parserControls(r)}<a class="small button" target="_blank" rel="noopener" href="/api/v1/revisions/${esc(r.id)}/original">打开原 PDF ↗</a>${r.artifact_id?`<button class="small" data-quality-artifact="${esc(r.artifact_id)}">检查解析质量</button>`:""}</div><small>${(r.byte_size/1024).toFixed(1)} KiB${r.page_count?` · ${r.page_count} 页 · ${r.block_count} 个文字块`:""}</small>${r.job_status==="FAILED"?`<p class="hint warning">解析未成功：${esc(r.error_detail || "请核对 PDF 是否损坏或加密。")}</p>`:""}${r.block_count===0?`<p class="hint warning">没有提取到文字，暂时不能从此文件选择出处。请提供有文字层的 PDF。</p>`:""}</div>`; }
function parserControls(r) {
  const active=["QUEUED","RUNNING","RETRY_WAIT"].includes(r.job_status);
  return `${canEdit()?`<button class="small" data-reparse="${esc(r.id)}" ${active?"disabled":""}>${r.job_status==="FAILED"?"重试解析":"重新解析"}</button>`:""}<small>产物：${esc(r.parser_profile||"尚未生成")}${r.job_parser_profile&&r.job_parser_profile!==r.parser_profile?` · 本次请求：${esc(r.job_parser_profile)}，历史产物仍可查看`:""}</small>`;
}
function materialOptions(document,current) {
  const revisions=document.revisions.filter(r=>r.artifact_id);
  const frozen=current&&!revisions.some(r=>r.artifact_id===current.artifact_id)?`<option value="${esc(current.artifact_id)}" selected>当前冻结解析 · ${esc(current.parser_profile)}</option>`:"";
  return frozen+revisions.map(r=>`<option value="${esc(r.artifact_id)}" ${current?.artifact_id===r.artifact_id?"selected":""}>第 ${r.revision_no} 版 · ${r.page_count} 页 · ${esc(r.parser_profile||"历史解析")}</option>`).join("");
}
function materialForm() {
  const docs = data.documents.filter(d=>["RESPONSE","EVIDENCE"].includes(d.kind));
  if (!docs.length) return empty("先上传投标响应，再选择本轮材料。");
  return `<form id="material-form">${docs.map(d=>{const current=data.material_set?.items.find(i=>i.document_id===d.id);return `<div class="material"><div><strong>${esc(d.title)}</strong><small> · ${labels[d.kind]}</small><select aria-label="${esc(d.title)}采用版本" name="artifact:${esc(d.id)}"><option value="">不纳入本轮</option>${materialOptions(d,current)}</select></div><label>材料用途<select name="role:${esc(d.id)}"><option value="FORMAL_RESPONSE" ${current?.submission_role==="FORMAL_RESPONSE"?"selected":""} ${d.kind!=="RESPONSE"?"disabled":""}>正式响应</option><option value="FORMAL_ATTACHMENT" ${current?.submission_role==="FORMAL_ATTACHMENT"||(!current&&d.kind==="EVIDENCE")?"selected":""}>正式附件</option><option value="REFERENCE" ${current?.submission_role==="REFERENCE"?"selected":""}>仅供参考</option></select></label></div>`;}).join("")}<div class="hint warning">发布新材料集后，旧审核结果需要重新核对。仅上传文件不会改变当前审查依据。</div><button class="primary" type="submit" ${!canEdit()?"disabled":""}>${data.material_set?"发布调整后的材料集":"确定本轮正式材料"}</button></form>`;
}
function requirementsView() {
  return `<div class="grid"><section class="panel"><div class="heading"><h2>已整理的要求 · ${data.requirements.length}</h2>${canEdit()?`<button class="small" data-action="new-requirement">新增要求</button>`:""}</div>${data.requirements.map(r=>`<article class="req"><h3>${esc(r.title)} ${tag(r.status)}</h3><p>${esc(r.text)}</p><small>第 ${r.revision_no} 版 · 录入人 ${esc(who(r.created_by))}${r.confirmed_by?` · 确认人 ${esc(who(r.confirmed_by))}`:""}</small>${sourceQuotes(r.sources)}<div class="row">${canEdit()?`<button class="small" data-edit="${esc(r.requirement_id)}">修订要求</button>`:""}${canReview()&&r.status==="DRAFT"?`<button class="small" data-confirm="${esc(r.requirement_id)}">核对原文后确认</button>`:""}</div></article>`).join("")||empty("从右侧招标原文开始，整理第一条要求。")}<div class="divider"></div><p class="muted">确认表示“这条要求录入准确”，还没有判断投标响应是否满足。</p><button class="primary" data-action="publish-baseline" ${!canReview()||!data.requirements.length||data.requirements.some(r=>r.status!=="CONFIRMED")||!data.workspace.pending_requirement_changes?"disabled":""}>发布全部已确认要求</button></section><section class="panel"><h2>${draft?"修订要求，保留旧版本":"从招标原文整理一条要求"}</h2>${canEdit()?`<form id="requirement-form"><div class="hint">先勾选招标原文，再写成一条能单独核对的要求。原文由服务端保存，不能自行编造出处。</div>${pickerHtml("tender")}<label>要求标题<input name="title" maxlength="200" required value="${esc(draft?.title||"")}" placeholder="例如：故障响应时限"></label><label>完整要求<textarea name="text" maxlength="8000" required placeholder="保留时间、数量、适用范围和例外条件">${esc(draft?.text||"")}</textarea></label><div class="row"><label>类别<select name="category">${Object.entries({TECHNICAL:"技术",QUALIFICATION:"资质",DELIVERY:"交付",FORMAT:"格式",OTHER:"其他"}).map(([v,n])=>`<option value="${v}" ${draft?.category===v?"selected":""}>${n}</option>`).join("")}</select></label><label>重要性<select name="priority">${Object.entries({MANDATORY:"必须满足",SCORING:"评分项",GENERAL:"一般要求"}).map(([v,n])=>`<option value="${v}" ${draft?.priority===v?"selected":""}>${n}</option>`).join("")}</select></label></div><button class="primary" type="submit">${draft?"保存新修订":"保存待确认要求"}</button></form>`:empty("由负责人或编写人整理要求；你可以核对左侧的待确认内容。")}</section></div>`;
}
function sourceQuotes(refs) {return (refs||[]).map(r=>`<div class="quote">${esc(r.quote||r.text)}<small>第 ${r.page} 页 · <a target="_blank" rel="noopener" href="/api/v1/revisions/${esc(r.revision_id)}/original">打开对应原件 ↗</a></small></div>`).join("");}
function pickerFiles(mode) {
  if(mode==="tender") return data.documents.filter(d=>["TENDER","AMENDMENT"].includes(d.kind)).flatMap(d=>d.revisions.filter(r=>r.artifact_id).map(r=>({...r,title:d.title,document_id:d.id})));
  return (data.material_set?.items||[]).filter(i=>i.submission_role!=="REFERENCE").map(i=>{const r=data.documents.find(d=>d.id===i.document_id)?.revisions.find(r=>r.id===i.revision_id);return {...r,...i,id:i.revision_id};});
}
function pickerHtml(mode) {pickerMode=mode; return `<div class="picker" id="source-picker"><strong>${mode==="tender"?"选择招标出处":"选择当前正式材料中的证据"}</strong><div id="picker-body">正在读取文件…</div><div id="selected-refs" class="selected-refs"></div></div>`;}
async function loadPicker() {
  const files=pickerFiles(pickerMode), container=$("#picker-body"); if(!container)return;
  const sequence=++pickerSequence;
  if(!files.length){container.innerHTML=empty(pickerMode==="tender"?"先上传并解析招标或更正文件。":"先在资料页发布本轮正式材料。");return;}
  if(!files.some(f=>f.artifact_id===pickerArtifact)) {pickerArtifact=files[0].artifact_id; pickerPage=1;pickerOffset=0;}
  const file=files.find(f=>f.artifact_id===pickerArtifact), pages=file.page_count||1; pickerPage=Math.min(pages,Math.max(1,pickerPage));
  const blocks=await api(`/api/v1/artifacts/${pickerArtifact}/blocks?page=${pickerPage}&offset=${pickerOffset}&limit=100`);
  if(sequence!==pickerSequence||!$("#picker-body"))return;
  container.innerHTML=`<label>文件版本<select id="picker-file">${files.map(f=>`<option value="${esc(f.artifact_id)}" ${f.artifact_id===pickerArtifact?"selected":""}>${esc(f.title)} · 第 ${f.revision_no} 版</option>`).join("")}</select></label><div class="picker-head"><button type="button" class="small" data-page="${pickerPage-1}" ${pickerPage<=1?"disabled":""}>上一页</button><label class="muted">页码<input id="picker-page" type="number" min="1" max="${pages}" value="${pickerPage}" aria-label="原文页码"></label><span class="muted">/ ${pages}</span><button type="button" class="small" data-page="${pickerPage+1}" ${pickerPage>=pages?"disabled":""}>下一页</button></div><div class="block-list">${blocks.length?blocks.map(b=>`<label class="block"><input type="checkbox" data-block="${esc(b.block_id)}" ${picks.some(p=>p.artifact_id===pickerArtifact&&p.block_id===b.block_id)?"checked":""}><span class="block-text">${esc(b.text)}</span></label>`).join(""):empty("此页未提取到文字，请打开原 PDF 检查。")}</div><div class="row">${pickerOffset?`<button class="small" type="button" data-offset="${Math.max(0,pickerOffset-100)}">上一组文字</button>`:""}${blocks.length===100?`<button class="small" type="button" data-offset="${pickerOffset+100}">下一组文字</button>`:""}<a class="small" target="_blank" rel="noopener" href="/api/v1/revisions/${esc(file.id)}/original">打开原 PDF ↗</a></div>`;
  container.blocks=blocks; container.file=file; renderPicks();
}
function renderPicks() {const el=$("#selected-refs"); if(el) el.innerHTML=`<p class="muted">已选 ${picks.length}/20 处原文</p>${picks.map((p,i)=>`<div class="selected-ref"><span>第 ${p.page} 页：${esc(p.quote||p.text)}</span><button type="button" class="plain small" data-remove-ref="${i}" aria-label="移除第 ${i+1} 处引用">移除</button></div>`).join("")}`;}
const refs=()=>picks.map(p=>({artifact_id:p.artifact_id,block_id:p.block_id}));
function reviewView() {
  if(!data.baseline||!data.material_set)return `<section class="panel"><h2>先准备本轮审查依据</h2><div class="hint">在“整理要求”确认并发布要求，在“资料与版本”选择正式响应材料，然后逐项核对。</div></section>`;
  const reqs=data.baseline.requirements; selectedRequirement=reqs.some(r=>r.requirement_id===selectedRequirement)?selectedRequirement:reqs[0]?.requirement_id; const r=reqs.find(r=>r.requirement_id===selectedRequirement); if(!r)return empty("基线尚无要求。");
  const report=data.report.requirements.find(row=>row.requirement_id===r.requirement_id);
  return `<div class="grid"><section class="panel"><h2>本轮按什么要求检查？</h2><label>已发布要求<select id="review-requirement">${reqs.map(r=>`<option value="${esc(r.requirement_id)}" ${selectedRequirement===r.requirement_id?"selected":""}>${esc(r.title)}</option>`).join("")}</select></label><h3>${esc(r.title)} ${tag(report.status)}</h3><p class="quote">${esc(r.text)}</p>${sourceQuotes(r.sources)}${report.current_decision?`<div class="hint">最近有效判断：${esc(labels[report.current_decision.decision])}<br>${esc(who(report.current_decision.decided_by))}：${esc(report.current_decision.note)}</div>`:""}<div class="hint">右侧只提供本轮正式材料中的原文。请自行阅读并判断，当前没有 AI 自动比对。</div></section><section class="panel"><h2>核对我们的响应</h2>${pickerHtml("response")}${canReview()?`<form id="decision-form"><label>审核判断<select name="decision"><option value="CONFIRMED_SATISFIED">人工确认满足（须有正式证据）</option><option value="CONFIRMED_ISSUE">确认有问题（先登记下方问题）</option><option value="NOT_APPLICABLE">本项目不适用（须说明原因）</option></select></label><label>审核意见<textarea name="note" maxlength="8000" required></textarea></label><button class="primary" type="submit">保存本项人工判断</button></form><div class="divider"></div><details><summary>发现缺口？登记问题并指派整改</summary><form id="issue-form"><label>问题标题<input name="title" maxlength="200" required></label><label>问题说明<textarea name="description" maxlength="8000" required placeholder="写清招标要求、我们的响应差异，以及需要修改什么"></textarea></label><div class="row"><label>问题类型<select name="kind"><option value="CONFLICT">承诺冲突（须选证据）</option><option value="MISSING_RESPONSE">缺少响应</option><option value="MISSING_EVIDENCE">缺少证明</option><option value="OTHER">其他</option></select></label><label>优先级<select name="severity"><option value="HIGH">高</option><option value="MEDIUM">中</option><option value="LOW">低</option></select></label></div><label>整改负责人<select name="assignee_id">${data.members.filter(m=>["OWNER","EDITOR"].includes(m.role)).map(m=>`<option value="${esc(m.user_id)}">${esc(m.name)} · ${labels[m.role]}</option>`).join("")}</select></label><label>整改期限（可选）<input type="date" name="due_date"></label><p class="muted">使用上方已选的原文作为问题证据。可先在“成员”加入编写同事。</p><button type="submit">登记问题与任务</button></form></details>`:empty("请由负责人或审查人登记问题和判断。")}</section></div>`;
}
function tasksView() {
  const issues=data.issues; const issue=issues.find(i=>i.task.id===selectedTask)||issues[0]; if(issue)selectedTask=issue.task.id;
  return `<div class="grid"><section class="panel"><h2>问题与整改 · ${issues.length}</h2><p class="muted">先修改实际响应文件并发布新版正式材料，再提交修改后的原文供另一人复核。</p><div class="divider"></div>${issues.map(i=>`<article class="issue"><h3>${esc(i.title)} ${tag(i.task.effective_status)}</h3><p>${esc(i.description)}</p><small>负责人：${esc(who(i.task.assignee_id))}${i.task.due_date?` · 期限 ${esc(i.task.due_date)}`:""}</small><p><button class="small" data-task="${esc(i.task.id)}">查看与处理 →</button></p></article>`).join("")||empty("尚无问题。请在本轮审查中按实际缺口登记。")}</section><section class="panel">${issue?taskDetail(issue):empty("选择左侧问题查看整改和复核记录。")}</section></div>`;
}
function taskDetail(issue) {
  const t=issue.task, own=t.assignee_id===user.id, submission=t.current_submission;
  const canStart=own&&canEdit()&&(["TODO","RETURNED"].includes(t.status)||(["SUBMITTED","ACCEPTED"].includes(t.status)&&t.freshness!=="CURRENT"));
  const canDecide=canReview()&&t.status==="SUBMITTED"&&t.freshness==="CURRENT"&&submission?.submitted_by!==user.id;
  const req=data.baseline?.requirements.find(r=>r.requirement_id===t.requirement_id);
  return `<h2>${esc(issue.title)}</h2><p>${tag(t.effective_status)} <small>负责人：${esc(who(t.assignee_id))}</small></p>${req?`<h3>当前要求</h3><p class="quote">${esc(req.text)}</p>`:""}<details><summary>问题登记时的证据</summary>${sourceQuotes(issue.evidence)}</details>${canStart?`<div class="hint">重新打开当前要求与文件核对后开始整改。若要改承诺，请在资料页上传新版并选择为正式材料。</div><button class="primary" data-start="${esc(t.id)}">${t.freshness!=="CURRENT"?"重新核对并开始整改":"开始整改"}</button>`:""}${own&&canEdit()&&t.status==="IN_PROGRESS"?`<form id="task-submit-form">${pickerHtml("response")}<label>整改说明<textarea name="note" maxlength="8000" required placeholder="写清本次修改内容，并选择上方修改后的正式原文"></textarea></label><button class="primary" type="submit">提交整改，等待他人复核</button></form>`:""}${submission?`<div class="divider"></div><h3>最近一次整改提交</h3><small>提交人：${esc(who(submission.submitted_by))} · ${t.freshness==="CURRENT"?"当前版本":"输入已变，需重新提交"}</small><p class="quote">${esc(submission.note)}</p>${sourceQuotes(submission.evidence)}`:""}${canDecide?`<form id="task-decision-form"><label>复核意见<textarea name="note" maxlength="8000" required placeholder="核对修改后的原件，说明通过或退回原因"></textarea></label><div class="row"><button class="primary" type="submit" name="decision" value="ACCEPT">验收通过</button><button type="submit" name="decision" value="RETURN">退回修改</button></div></form>`:""}${t.status==="SUBMITTED"&&submission?.submitted_by===user.id?`<div class="hint warning">你是这次整改的提交人，需要另一位负责人或审查人登录后复核。请在成员页配置实际协作账号。</div>`:""}${t.status==="ACCEPTED"&&t.freshness==="CURRENT"?`<div class="hint">本问题已验收。请回到“本轮审查”对该要求作最终人工判断；验收不会代替逐项审查。</div>`:""}${t.decisions.length?`<div class="divider"></div><h3>复核历史</h3>${t.decisions.map(d=>`<div class="history"><strong>${esc(labels[d.decision])}</strong> · ${esc(who(d.decided_by))}<p>${esc(d.note)}</p></div>`).join("")}`:""}<button class="small" data-action="task-history">查看历次提交</button><div id="task-history"></div>`;
}
function reportView() {
  const r=data.report; return `<div class="heading"><div><h2>${esc(labels[r.status])}</h2><p>只统计本轮基线、正式材料及仍然有效的人工判断。</p></div><a class="button" href="${base()}/review-report/export">下载 Markdown 报告 ↓</a></div><div class="stat-grid"><div class="stat"><small>当前基线要求</small><b>${r.requirement_count}</b></div><div class="stat"><small>已人工确认</small><b>${r.reviewed_count}<small> / ${r.requirement_count}</small></b></div><div class="stat"><small>未解决问题</small><b>${r.unresolved_issue_count}</b></div></div><section class="panel">${r.requirements.map(row=>`<article class="report-row"><div class="row"><h3>${esc(row.title)}</h3>${tag(row.status)}</div>${row.current_decision?`<p>${esc(who(row.current_decision.decided_by))}：${esc(row.current_decision.note)}</p>${sourceQuotes(row.current_decision.evidence)}`:`<p class="muted">尚无适用于当前材料的最终人工判断。</p>`}<button class="plain small" data-review="${esc(row.requirement_id)}">去核对这一项 →</button></article>`).join("")||empty("发布要求基线与正式材料后，报告会显示逐项覆盖情况。")}</section><p class="hint">当前是人工审查流程，尚未接入 RAG 检索或 Agent 自动审查；OCR 是否执行取决于解析配置。</p>`;
}
function membersView() {return `<div class="grid"><section class="panel"><h2>项目成员</h2><p class="muted">编写人整理资料并整改；审查人确认要求并独立复核；负责人可以兼顾两类工作，但不能复核自己的整改提交。</p>${data.members.map(m=>`<div class="req"><h3>${esc(m.name)} ${m.user_id===user.id?"（我）":""}</h3><small>${labels[m.role]}</small></div>`).join("")}</section><section class="panel"><h2>加入协作账号</h2>${data.workspace.my_role==="OWNER"?`<form id="member-search-form"><label>查找已有账号<input name="q" minlength="2" maxlength="80" required placeholder="输入至少两个姓名字符"></label><button type="submit">查找账号</button></form><div id="member-results" class="search-results"></div><div class="hint">这里查找的是管理员已创建的账号。演示人物不会出现在结果中；不会自动创建同事或模拟其他人验收。</div>`:empty("只有项目负责人可以添加或调整成员。")}</section></div>`;}

document.addEventListener("submit", async event=>{
  const form=event.target; event.preventDefault(); if(busy)return; const values=Object.fromEntries(new FormData(form));
  if(form.id==="login-form")return act(async()=>{const session=await api("/api/v1/auth/session",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)}); form.reset(); user=session.user; await home();},"登录成功",false);
  if(form.id==="project-form")return act(async()=>{const p=await write("/api/v1/projects",{name:values.name.trim()});await openProject(p.id);},"项目已创建",false);
  if(form.id==="upload-form")return act(async()=>{const body=new FormData();body.set("file",form.elements.file.files[0]); if(!values.document_id){if(!values.title.trim())throw new Error("请填写文档名称。");body.set("title",values.title.trim());body.set("kind",values.kind);}await write(values.document_id?`/api/v1/documents/${values.document_id}/revisions`:base()+"/documents",body,true);},"文件已接收，后台正在解析。");
  if(form.id==="material-form")return act(async()=>{const items=data.documents.flatMap(d=>values["artifact:"+d.id]?[{artifact_id:values["artifact:"+d.id],submission_role:values["role:"+d.id]}]:[]);if(!items.some(i=>i.submission_role==="FORMAL_RESPONSE"))throw new Error("至少选择一份正式投标响应。");await write(base()+"/material-sets",{name:"网页选定正式材料",expected_epoch:data.workspace.review_epoch,expected_current_material_set_id:data.workspace.current_material_set_id,items});resetPicker();},"本轮正式材料已发布；请按此版本核对。");
  if(form.id==="requirement-form")return act(async()=>{if(!picks.length)throw new Error("请先选择至少一处招标原文。");const body={...values,sources:refs(),...(draft?{expected_revision_no:draft.revision_no}:{})};await write(base()+`/requirements${draft?`/${draft.requirement_id}/revisions`:""}`,body);draft=null;resetPicker();},"要求已保存，等待确认。");
  if(form.id==="decision-form")return act(async()=>{if(values.decision==="CONFIRMED_SATISFIED"&&!picks.length)throw new Error("确认满足前，请先选择正式响应证据。");const req=data.baseline.requirements.find(r=>r.requirement_id===selectedRequirement);await write(base()+"/requirement-decisions",{...values,expected_epoch:data.workspace.review_epoch,requirement_revision_id:req.revision_id,evidence:refs()});resetPicker();},"本项人工判断已保存。");
  if(form.id==="issue-form")return act(async()=>{if(values.kind==="CONFLICT"&&!picks.length)throw new Error("承诺冲突需要选择正式响应原文。");const req=data.baseline.requirements.find(r=>r.requirement_id===selectedRequirement);await write(base()+"/issues",{...values,due_date:values.due_date||null,expected_epoch:data.workspace.review_epoch,requirement_revision_id:req.revision_id,evidence:refs()});},"问题与整改任务已登记，可在整改复核页处理。");
  if(form.id==="task-submit-form")return act(async()=>{if(!picks.length)throw new Error("请选择修改后正式材料中的原文。");const t=data.issues.find(i=>i.task.id===selectedTask).task;await write(base()+`/tasks/${t.id}/transitions`,{action:"SUBMIT",expected_version:t.version,expected_epoch:data.workspace.review_epoch,note:values.note,evidence:refs()});resetPicker();},"整改已提交，等待另一位成员复核。");
  if(form.id==="task-decision-form")return act(async()=>{const t=data.issues.find(i=>i.task.id===selectedTask).task;await write(base()+`/tasks/${t.id}/decisions`,{expected_version:t.version,submission_id:t.current_submission.id,decision:event.submitter.value,note:values.note});},"复核意见已保存。");
  if(form.id==="member-search-form")return act(async()=>{const users=await api(base()+"/member-candidates?q="+encodeURIComponent(values.q));$("#member-results").innerHTML=users.map(u=>`<form class="req add-member-form"><h3>${esc(u.name)}</h3><input type="hidden" name="user_id" value="${esc(u.id)}"><label>项目角色<select name="role"><option value="EDITOR">编写人</option><option value="REVIEWER">审查人</option><option value="READER">只读成员</option></select></label><button type="submit">加入项目</button></form>`).join("")||empty("没有找到可加入的账号，请联系管理员先创建账号。");},null,false);
  if(form.classList.contains("add-member-form"))return act(()=>write(base()+"/members",values),"成员已加入项目。");
});
document.addEventListener("click", async event=>{
  const el=event.target.closest("button"); if(!el||busy)return;
  if(el.dataset.project)return act(()=>openProject(el.dataset.project),null,false);
  if(el.dataset.tab){tab=el.dataset.tab;draft=null;resetPicker();render();return;}
  if(el.dataset.page){pickerPage=Number(el.dataset.page);pickerOffset=0;return act(()=>loadPicker(),null,false);}
  if(el.dataset.offset!==undefined){pickerOffset=Number(el.dataset.offset);return act(()=>loadPicker(),null,false);}
  if(el.dataset.removeRef!==undefined){picks.splice(Number(el.dataset.removeRef),1);renderPicks();return loadPicker().catch(e=>notice(explain(e),true));}
  if(el.dataset.edit){draft=data.requirements.find(r=>r.requirement_id===el.dataset.edit);picks=[...draft.sources];render();$("#requirement-form")?.scrollIntoView({behavior:"smooth",block:"start"});return;}
  if(el.dataset.reparse)return act(async()=>{await write(`/api/v1/revisions/${el.dataset.reparse}/parse`,{retry_failed:true});},"已登记解析任务，旧出处和已发布材料保持原版本。");
  if(el.dataset.confirm){const r=data.requirements.find(r=>r.requirement_id===el.dataset.confirm);return act(()=>write(base()+`/requirements/${r.requirement_id}/confirm`,{expected_revision_no:r.revision_no}),"要求已确认，可以纳入基线。");}
  if(el.dataset.review){tab="review";selectedRequirement=el.dataset.review;resetPicker();render();return;}
  if(el.dataset.task){selectedTask=el.dataset.task;resetPicker();render();return;}
  if(el.dataset.start){const t=data.issues.find(i=>i.task.id===el.dataset.start).task;return act(()=>write(base()+`/tasks/${t.id}/transitions`,{action:"START",expected_version:t.version,expected_epoch:data.workspace.review_epoch}),"已开始整改。");}
  if(el.dataset.action==="home")return act(home,null,false);
  if(el.dataset.action==="logout")return act(async()=>{await api("/api/v1/auth/session",{method:"DELETE"});pendingKeys.clear();user=null;data=null;projectId=null;clearTimeout(pollTimer);renderLogin();},"已退出登录",false);
  if(el.dataset.action==="refresh")return act(loadProject,"项目已刷新",false);
  if(el.dataset.action==="new-requirement"){draft=null;resetPicker();render();return;}
  if(el.dataset.action==="publish-baseline")return act(()=>write(base()+"/baselines",{name:"网页确认要求基线",expected_epoch:data.workspace.review_epoch,expected_current_baseline_id:data.workspace.current_baseline_id,requirement_revision_ids:data.requirements.map(r=>r.revision_id)}),"已发布要求基线；旧结论需按新基线重新核对。");
  if(el.dataset.action==="task-history")return act(async()=>{const history=await api(base()+`/tasks/${selectedTask}/submissions`);$("#task-history").innerHTML=history.map(s=>`<div class="history"><strong>${esc(who(s.submitted_by))}</strong><p>${esc(s.note)}</p>${sourceQuotes(s.evidence)}</div>`).join("")||empty("尚无提交历史。");},null,false);
});
document.addEventListener("change",event=>{
  const el=event.target;if(busy)return;
  if(el.closest("#material-form")) $("#materials-selector").dataset.dirty="true";
  if(el.name==="document_id")$("#new-document-fields").hidden=!!el.value;
  if(el.id==="workspace-step"){tab=el.value;draft=null;resetPicker();render();}
  if(el.id==="picker-file"){pickerArtifact=el.value;pickerPage=1;pickerOffset=0;act(loadPicker,null,false);}
  if(el.id==="picker-page"){pickerPage=Number(el.value)||1;pickerOffset=0;act(loadPicker,null,false);}
  if(el.id==="review-requirement"){selectedRequirement=el.value;resetPicker();render();}
  if(el.dataset.block){const idx=picks.findIndex(p=>p.artifact_id===pickerArtifact&&p.block_id===el.dataset.block);if(el.checked&&idx<0){if(picks.length>=20){el.checked=false;notice("每次最多引用 20 处原文。",true);return;}const container=$("#picker-body"),block=container.blocks.find(b=>b.block_id===el.dataset.block);picks.push({...block,artifact_id:pickerArtifact,revision_id:container.file.id});}else if(!el.checked&&idx>=0)picks.splice(idx,1);renderPicks();}
});
(async()=>{try {const session=await api("/api/v1/auth/session");user=session.user;await home();}catch(e){if(e.status!==401){renderLogin();notice(explain(e),true);}}finally{root.setAttribute("aria-busy","false");}})();
