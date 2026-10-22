"use strict";
let dirty=false,unreadCount=0;
const listStates=new Map();
const sectionInfo=[
  ["overview","项目概览","概览"],["files","资料与版本","准备资料"],["quality","原文质量","准备资料"],
  ["ai","要求候选","准备资料"],["requirements","要求台账","审查工作"],["retrieval","证据检索","审查工作"],
  ["assistant","辅助检查","审查工作"],["review","逐项审查","审查工作"],["tasks","整改复核","协作交付"],
  ["changes","更正影响","协作交付"],["report","审查报告","协作交付"],["members","成员权限","项目管理"],
  ["audit","操作记录","项目管理"],["operations","运行维护","项目管理"]
];
Object.assign(labels,{CANCELLED:"已撤销",WITHDRAWN:"已撤销",RETIRED:"已退休",PENDING:"待处理",REVISED:"已修订",NO_CHANGE:"确认不改",SUPPORTED:"有支持依据",SUSPECTED_ISSUE:"疑似问题",INSUFFICIENT_EVIDENCE:"证据不足"});
function icon(name="file") {
  const shapes={file:'<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6"/>',
    check:'<path d="m5 12 4 4L19 6"/>',search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
    bell:'<path d="M6 9a6 6 0 0 1 12 0v7l2 2H4l2-2zM10 21h4"/>',arrow:'<path d="M4 12h15m-6-6 6 6-6 6"/>'};
  return `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${shapes[name]||shapes.file}</svg>`;
}
function skeleton(text="正在读取项目资料") {
  return `<div class="skeleton" role="status" aria-label="${esc(text)}"><span>${esc(text)}…</span><i></i><i></i><i></i></div>`;
}
function emptyState(title,description,action="") {
  return `<div class="empty-state" role="status">${icon()}<h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;
}
function failureState(message,action="refresh") {
  return `<div class="error-state" role="alert"><h3>暂时未能读取内容</h3><p>${esc(message)}</p><button data-action="${esc(action)}">重新读取</button></div>`;
}
function focusContent(target) {
  requestAnimationFrame(()=>{const el=$(target||"#section h2, #workspace h1");if(el){el.tabIndex=-1;el.focus({preventScroll:false});}});
}
function formatDate(value,withTime=false) {
  if(!value)return "未设置";
  if(/^\d{4}-\d{2}-\d{2}$/.test(value))return value;
  const date=new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value)?value:value+"Z");
  return Number.isNaN(date.getTime())?String(value):new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",...(withTime?{hour:"2-digit",minute:"2-digit"}:{})}).format(date);
}
function notice(message,error=false) {
  const box=$("#notice");box.innerHTML=`<span>${esc(message)}</span><button class="plain" aria-label="关闭提示" data-dismiss-notice>×</button>`;
  box.className=error?"error":"";box.setAttribute("role",error?"alert":"status");box.setAttribute("aria-live",error?"assertive":"polite");box.hidden=false;
  if(error&&$("#workspace-dialog")?.open)$("#dialog-error").textContent=message;
  clearTimeout(notice.timer);notice.timer=setTimeout(()=>{box.hidden=true;},error?15000:6000);
}
function clearViewTimers() {
  clearTimeout(filterTimer);
  clearTimeout(pollTimer);clearTimeout(aiTimer);clearTimeout(retrievalTimer);clearTimeout(assistantTimer);
  qualitySequence++;aiSequence++;retrievalSequence++;assistantSequence++;
}
function guardUnsaved(work) {
  if(!dirty){work();return;}
  openDialog({title:"放弃未保存的内容？",description:"已保存的记录会保留，当前表单和未提交的引用将被清空。",submitLabel:"放弃并继续",danger:true,
    onSubmit:async()=>{dirty=false;work();return true;}});
}
function openDialog({title,description="",body="",submitLabel="保存",danger=false,onSubmit}) {
  const dialog=$("#workspace-dialog"),previous=document.activeElement;
  if(dialog.open)return;
  dialog.innerHTML=`<form id="dialog-form"><div class="dialog-heading"><h2 id="dialog-title">${esc(title)}</h2><button type="button" class="plain" data-close-dialog aria-label="关闭对话框">×</button></div><p id="dialog-description">${esc(description)}</p>${body}<p id="dialog-error" role="alert"></p><div class="dialog-actions"><button type="button" data-close-dialog>取消</button><button class="${danger?"danger":"primary"}" type="submit">${esc(submitLabel)}</button></div></form>`;
  dialog.showModal();
  requestAnimationFrame(()=>dialog.querySelector(danger?"[data-close-dialog]":"input,textarea,select,button[type=submit]")?.focus());
  dialog.onclose=()=>{if(previous?.isConnected)previous.focus();else focusContent();};
  dialog.querySelector("form").onsubmit=async event=>{
    event.preventDefault();event.stopPropagation();if(busy)return;
    const result=await onSubmit(Object.fromEntries(new FormData(event.target)));
    if(result!==false)dialog.close();
  };
}
function stateFor(name) {
  const key=`${projectId||"home"}:${name}`;
  if(!listStates.has(key))listStates.set(key,{q:"",filter:"",page:1,size:10,total:0});
  return listStates.get(key);
}
function listToolbar(name,filters=[],placeholder="搜索标题或内容") {
  const s=stateFor(name);
  return `<form class="list-toolbar" data-list-toolbar="${name}" role="search"><label class="search-control">${icon("search")}<input type="search" data-list-q="${name}" value="${esc(s.q)}" maxlength="100" placeholder="${esc(placeholder)}" aria-label="${esc(placeholder)}"></label>${filters.length?`<select data-list-filter="${name}" aria-label="筛选列表状态">${filters.map(([v,n])=>`<option value="${v}" ${s.filter===v?"selected":""}>${n}</option>`).join("")}</select>`:""}<button type="button" class="small" data-list-reset="${name}">清除筛选</button></form>`;
}
function pageItems(name,rows) {
  const state=stateFor(name);state.total=rows.length;
  state.page=Math.min(state.page,Math.max(1,Math.ceil(rows.length/state.size)));
  return rows.slice((state.page-1)*state.size,state.page*state.size);
}
function pager(name) {
  const s=stateFor(name),pages=Math.max(1,Math.ceil(s.total/s.size));
  return `<div class="pagination"><span aria-live="polite">共 ${s.total} 条 · 第 ${s.page}/${pages} 页</span><div class="row"><button class="small" data-list-page="${name}" data-direction="-1" ${s.page<=1?"disabled":""}>上一页</button><button class="small" data-list-page="${name}" data-direction="1" ${s.page>=pages?"disabled":""}>下一页</button></div></div>`;
}
function matches(text,q){return String(text).toLocaleLowerCase().includes(q.trim().toLocaleLowerCase());}
document.addEventListener("click",event=>{
  const close=event.target.closest("[data-close-dialog]");if(close){$("#workspace-dialog").close();return;}
  if(event.target.closest("[data-dismiss-notice]"))$("#notice").hidden=true;
});
document.addEventListener("input",event=>{
  const form=event.target.closest("form");
  if(form&&!form.matches("[data-list-toolbar],#dialog-form,#login-form,#retrieval-form,#member-search-form,#notification-filter,#account-key-form")&&!event.target.matches("[type=search]"))dirty=true;
});
window.addEventListener("beforeunload",event=>{if(dirty){event.preventDefault();event.returnValue="";}});
