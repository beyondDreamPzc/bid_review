"use strict";
// 仅操作现有业务 API。登录密钥不进入 URL、localStorage 或 sessionStorage。
const root = document.querySelector("#workspace"), identity = document.querySelector("#identity");
const $ = (selector) => document.querySelector(selector);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const labels = {OWNER:"负责人",EDITOR:"编写人",REVIEWER:"审查人",READER:"只读成员",TENDER:"招标文件",AMENDMENT:"更正文件",RESPONSE:"投标响应",EVIDENCE:"证明材料",DRAFT:"待确认",CONFIRMED:"已确认",TODO:"待整改",IN_PROGRESS:"整改中",SUBMITTED:"待复核",ACCEPTED:"已验收",RETURNED:"已退回",NEEDS_RECHECK:"需重新核对",OPEN:"待整改",RESOLVED:"已解决",UNREVIEWED:"未核对",ISSUES_OPEN:"有未解决问题",NEEDS_REVIEW:"待最终确认",REVIEWED:"已人工确认",NOT_READY:"尚未准备好审查输入",IN_REVIEW:"核对中",REVIEW_COMPLETE:"本轮人工核对完成",QUEUED:"排队中",RUNNING:"解析中",RETRY_WAIT:"等待重试",SUCCEEDED:"解析完成",FAILED:"解析失败",CONFIRMED_SATISFIED:"人工确认满足",CONFIRMED_ISSUE:"人工确认有问题",NOT_APPLICABLE:"不适用",ACCEPT:"验收通过",RETURN:"退回修改"};
const tag = (v) => `<span class="badge ${["REVIEWED","CONFIRMED","ACCEPTED","REVIEW_COMPLETE","SUCCEEDED","RESOLVED"].includes(v)?"green":"amber"}">${esc(labels[v] || v)}</span>`;
let user = null, projects = [], projectId = null, data = null, tab = "overview", busy = false, pollTimer = null;
let draft = null, selectedRequirement = null, selectedTask = null, picks = [], pickerMode = "tender", pickerArtifact = "", pickerPage = 1, pickerOffset = 0, pickerSequence = 0;
const pendingKeys = new Map();
function explain(error) {
  if(error.status===409&&/[\u4e00-\u9fff]/.test(error.message))return error.message+" 请保留未保存内容，核对后刷新。";
  if (error.status === 409) return "项目或任务状态已变化。已刷新资料，请重新核对后再操作。";
  if (error.status === 403) return "当前账号不能执行此操作；整改提交人不能复核自己的提交。";
  if (error.status === 422) return /[\u4e00-\u9fff]/.test(error.message)?error.message:"请检查必填内容、所选原文及文件格式后重试。";
  if (error.status === 413) return "PDF 超过当前 50 MiB 上传上限。";
  if (error.status === 415) return "请上传有效的 PDF 或 DOCX，DOCX不能含宏或外部资源。";
  if(error.status===401)return "登录已失效，请使用有效密钥重新登录。";
  return error.message || "操作未完成，请稍后重试。";
}
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {credentials:"same-origin", cache:"no-store", ...options}); }
  catch { const e = new Error("网络连接中断，请重试同一操作。"); e.transport = true; throw e; }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const e = new Error(typeof body.detail === "string" ? body.detail : "请求未能完成。"); e.status = response.status;
    if (response.status === 401) { user = null; data = null; projectId = null; dirty=false; clearViewTimers(); renderLogin(); }
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
function setBusy(value) {
  busy=value;root.setAttribute("aria-busy",String(value));
  document.querySelectorAll("button").forEach(button=>{
    if(value){button.dataset.wasDisabled=String(button.disabled);button.disabled=true;}
    else if(button.dataset.wasDisabled!==undefined){button.disabled=button.dataset.wasDisabled==="true";delete button.dataset.wasDisabled;}
  });
}
async function act(work,message,reload=true) {
  if(busy)return false;setBusy(true);
  try {
    await work();
    if(reload){dirty=false;if(projectId)await loadProject();}
    if(message)notice(message);
    if(reload)focusContent();
    return true;
  } catch(error) {
    if(error.status===409&&projectId&&!dirty)await loadProject().catch(()=>{});
    notice(explain(error),true);return false;
  } finally {setBusy(false);}
}
const base = () => `/api/v1/projects/${projectId}`;
const canEdit = () => ["OWNER","EDITOR"].includes(data.workspace.my_role);
const canReview = () => ["OWNER","REVIEWER"].includes(data.workspace.my_role);
const who = id => data.members.find(m=>m.user_id===id)?.name || "历史成员";
const empty = text => `<div class="empty">${esc(text)}</div>`;
function resetPicker() { picks = []; pickerArtifact = ""; pickerPage = 1; pickerOffset = 0; pickerSequence++; }
async function openProject(id,section="overview") {
  clearViewTimers();projectId=id;data=null;tab=section;draft=null;selectedRequirement=selectedTask=null;resetPicker();
  globalSequence++;root.innerHTML=skeleton("正在读取项目");
  try{await loadProject();focusContent();}catch(error){if(projectId===id&&user){root.innerHTML=failureState(explain(error),"home");head();}throw error;}
}
function processing() {
  return (data.conversions||[]).some(c=>["QUEUED","RUNNING","RETRY_WAIT"].includes(c.status)) || data.documents.some(d => d.revisions.some(r => r.job_status && !["SUCCEEDED", "FAILED"].includes(r.job_status)));
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
      if(tab==="overview"&&!dirty)$("#section").innerHTML=overviewView();
      if (tab === "files") {
        const list = $("#file-list");
        if (list) list.innerHTML = fileList();
        const conversions=$("#conversion-list");if(conversions)conversions.innerHTML=conversionList();
        const selector = $("#materials-selector");
        if (selector && selector.dataset.dirty !== "true") selector.innerHTML = materialForm();
      }
      if (!processing()) notice("PDF 解析完成，可选择出处与正式版本。");
      schedulePoll(id);
    } catch (error) { notice(explain(error), true); }
  }, 2500);
}
