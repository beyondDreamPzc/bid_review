"use strict";
let globalSequence=0,accountState=null,notificationOffset=0,notificationUnread=false;
async function refreshUnread() {
  const id=user?.id;if(!id)return;
  try {const value=await api("/api/v1/notifications?unread=true&limit=1");if(user?.id===id){unreadCount=value.total;head();}}catch{}
}
async function showGlobal(name) {
  clearViewTimers();projectId=null;data=null;tab=name;dirty=false;setRoute("/"+name);head();
  const sequence=++globalSequence;
  root.innerHTML=`<div class="page-heading"><div><p class="breadcrumb">核标 / ${name==="account"?"账号安全":"站内通知"}</p><h1>${name==="account"?"账号安全":"站内通知"}</h1></div><button data-action="home">返回我的项目</button></div><div id="global-body">${skeleton("正在读取内容")}</div>`;
  try {
    if(name==="account") {
      const value=await api("/api/v1/account");if(sequence!==globalSequence||tab!==name)return;
      accountState=value;renderAccount();
    } else await loadNotifications(sequence);
    focusContent("#workspace h1");
  }catch(error){if(user&&sequence===globalSequence&&$("#global-body"))$("#global-body").innerHTML=failureState(explain(error),"global-retry");}
}
function renderAccount() {
  const value=accountState;
  $("#global-body").innerHTML=`<div class="overview-grid"><section class="panel"><h2>访问密钥</h2><dl class="summary-list"><div><dt>当前账号</dt><dd>${esc(value.name)}</dd></div><div><dt>密钥版本指纹</dt><dd><code>${esc(value.key_fingerprint)}</code></dd></div></dl><p>密钥用于登录及接口访问。怀疑泄露时，生成并安全保存新密钥，再轮换旧凭据。</p><button class="primary" data-prepare-key>更换访问密钥</button><p class="field-help">轮换后所有浏览器会话撤销，需要用新密钥重新登录。页面不会把新密钥写入网址或本地存储。</p></section><section class="panel"><h2>有效浏览器会话</h2>${value.sessions.map(s=>`<div class="session-row"><div><strong>${s.current?"当前浏览器":"其他浏览器会话"}</strong><small>${formatDate(s.expires_at,true)} 到期</small></div><button class="small" data-revoke-session="${esc(s.id)}">撤销${s.current?"当前会话":"此会话"}</button></div>`).join("")||emptyState("没有有效Cookie会话","当前可能使用API Key认证；它不属于浏览器会话。")}</section></div>`;
}
async function loadNotifications(sequence=globalSequence) {
  const result=await api(`/api/v1/notifications?unread=${notificationUnread}&offset=${notificationOffset}&limit=20`);
  if(!user||sequence!==globalSequence||tab!=="notifications"||!$("#global-body"))return;
  $("#global-body").innerHTML=`<section class="panel"><div class="section-heading"><h2>项目通知</h2><label class="checkbox-label"><input id="notification-unread" type="checkbox" ${notificationUnread?"checked":""}>仅看未读</label></div>${result.items.map(n=>`<article class="notification-row ${n.read_at?"":"unread"}"><div><h3>${esc(n.title)}</h3><small>${formatDate(n.created_at,true)}${n.read_at?" / 已读":" / 未读"}</small></div><div class="row"><button class="small" data-notification-open="${esc(n.id)}" data-project-target="${esc(n.project_id)}" data-section-target="${esc(n.section)}">打开项目</button>${!n.read_at?`<button class="plain small" data-notification-read="${esc(n.id)}">标为已读</button>`:""}</div></article>`).join("")||emptyState("当前没有通知",notificationUnread?"没有未读提醒。可取消筛选查看已读记录。":"任务和复核有更新时会出现在这里。通知不代替实际待办清单。")}<div class="pagination"><span>共 ${result.total} 条</span><div class="row"><button class="small" data-notification-page="-1" ${notificationOffset===0?"disabled":""}>上一页</button><button class="small" data-notification-page="1" ${notificationOffset+20>=result.total?"disabled":""}>下一页</button></div></div></section>`;
}
function prepareKeyDialog() {
  openDialog({title:"更换自己的访问密钥",description:"先把新随机密钥保存到安全位置。确认轮换后旧密钥与所有浏览器会话失效。",submitLabel:"已保存，确认轮换",danger:true,
    body:`<label>新访问密钥<input type="password" name="new_key" id="new-account-key" autocomplete="off" minlength="24" maxlength="256" required></label><div class="row"><button type="button" data-generate-key>生成随机密钥</button><button type="button" data-reveal-key>显示 / 隐藏</button><button type="button" data-copy-key>复制新密钥</button></div><label class="checkbox-label"><input type="checkbox" name="saved" required><span>我已安全保存新密钥，知道系统不能恢复其明文。</span></label>`,
    onSubmit:values=>act(async()=>{
      await write("/api/v1/account/key",{new_key:values.new_key,expected_fingerprint:accountState.key_fingerprint});
      user=null;data=null;projectId=null;dirty=false;pendingKeys.clear();setRoute("");renderLogin();
    },"密钥已轮换，请使用你保存的新密钥重新登录。",false)});
}
document.addEventListener("click",event=>{
  const el=event.target.closest("button");if(!el||busy)return;
  if(el.dataset.global)return guardUnsaved(()=>showGlobal(el.dataset.global));
  if(el.hasAttribute("data-prepare-key"))return prepareKeyDialog();
  if(el.hasAttribute("data-generate-key")){const bytes=crypto.getRandomValues(new Uint8Array(32));$("#new-account-key").value=Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join("");return;}
  if(el.hasAttribute("data-reveal-key")){const input=$("#new-account-key");input.type=input.type==="password"?"text":"password";return;}
  if(el.hasAttribute("data-copy-key")){navigator.clipboard.writeText($("#new-account-key").value).then(()=>notice("已复制，请保存到安全位置。"),()=>notice("无法访问剪贴板，请手动复制。",true));return;}
  if(el.dataset.revokeSession)return openDialog({title:"撤销浏览器会话",description:"该会话下次请求需要重新登录；撤销当前会话也会退出本页面。",submitLabel:"确认撤销",danger:true,onSubmit:()=>act(async()=>{
    const result=await api(`/api/v1/account/sessions/${el.dataset.revokeSession}/revoke`,{method:"POST"});
    if(result.login_required){user=null;data=null;projectId=null;dirty=false;setRoute("");renderLogin();}else await showGlobal("account");
  },"会话已撤销。",false)});
  if(el.dataset.notificationRead)return act(async()=>{await api(`/api/v1/notifications/${el.dataset.notificationRead}/read`,{method:"POST"});await loadNotifications();await refreshUnread();},null,false);
  if(el.dataset.notificationOpen)return act(async()=>{await api(`/api/v1/notifications/${el.dataset.notificationOpen}/read`,{method:"POST"});await openProject(el.dataset.projectTarget,el.dataset.sectionTarget);await refreshUnread();},null,false);
  if(el.dataset.notificationPage){notificationOffset=Math.max(0,notificationOffset+Number(el.dataset.notificationPage)*20);return act(()=>loadNotifications(),null,false);}
  if(el.dataset.action==="global-retry")return showGlobal(tab);
});
document.addEventListener("change",event=>{if(event.target.id==="notification-unread"){notificationUnread=event.target.checked;notificationOffset=0;act(()=>loadNotifications(),null,false);}});
