"use strict";
function head() {
  identity.innerHTML=user?`<button class="header-notifications" data-global="notifications" aria-label="站内通知，${unreadCount}条未读">${icon("bell")}<span>通知</span>${unreadCount?`<b>${unreadCount}</b>`:""}</button><button class="account-button" data-global="account" aria-label="账号安全：${esc(user.name)}"><span class="avatar">${esc(user.name.slice(0,1))}</span><span>${esc(user.name)}</span></button><button class="plain" data-action="logout">退出</button>`:`<a href="/">了解操作流程</a>`;
}
function renderLogin() {
  head();root.setAttribute("aria-busy","false");
  root.innerHTML=`<section class="login"><div class="login-intro"><span class="document-symbol">${icon("check")}</span><h1>进入核标工作台</h1><p>把要求、响应证据和整改记录，放在同一条可追溯的审查流程里。</p><ul><li>保留文件版本与原文出处</li><li>明确本轮采用的要求和材料</li><li>整改提交由另一人独立复核</li></ul></div><div class="panel login-form"><h2>登录已有账号</h2><form id="login-form"><label for="login-key">账号访问密钥</label><input id="login-key" type="password" name="api_key" required autocomplete="off" placeholder="输入管理员提供的密钥"><p class="field-help">密钥仅用于本次登录，网页不会将它保存在本地存储中。</p><button class="primary" type="submit">登录工作台</button></form><details><summary>第一次使用</summary><p>本地初始账号的密钥位于项目.env的BID_BOOTSTRAP_API_KEY。协作账号由管理员创建，每人使用独立账号。</p></details><a href="/">先体验构造样例</a></div></section>`;
}
async function home() {
  const sequence=++globalSequence,actor=user?.id;clearViewTimers();projectId=null;data=null;resetPicker();head();root.innerHTML=skeleton("正在读取我的项目");setRoute("");
  try {
    const result=await api("/api/v1/projects");
    if(sequence!==globalSequence||user?.id!==actor)return;projects=result;
    root.innerHTML=`<div class="page-heading"><div><p class="breadcrumb">核标 / 我的项目</p><h1>我的项目</h1><p>选择一个项目继续审查，或建立新的资料空间。</p></div><button class="primary" data-new-project>创建项目</button></div><section class="panel"><div class="section-heading"><h2>可访问的项目 <span class="count">${projects.length}</span></h2><a href="/">查看操作演示</a></div>${projects.length?`<div class="project-list">${projects.map(p=>`<button class="project-row" data-project="${esc(p.id)}">${icon()}<span><strong>${esc(p.name)}</strong><small>资料、要求、整改与报告</small></span><span class="row-arrow">${icon("arrow")}</span></button>`).join("")}</div>`:emptyState("还没有项目","先创建项目，再上传招标文件与响应材料。",`<button class="primary" data-new-project>创建第一个项目</button>`)}</section>`;
    root.setAttribute("aria-busy","false");
  } catch(error){if(user&&sequence===globalSequence)root.innerHTML=failureState(explain(error),"home");throw error;}
}
function allowedSections() {
  return sectionInfo.filter(([id])=>id!=="operations"||data.workspace.my_role==="OWNER")
    .filter(([id])=>id!=="audit"||canReview());
}
function render() {
  if(!data)return;head();pickerSequence++;
  const w=data.workspace,sections=allowedSections();
  if(!sections.some(([id])=>id===tab))tab="overview";
  setProjectRoute();
  let group="";
  const nav=sections.map(([id,label,next])=>{const heading=group!==next?`<p class="nav-group">${next}</p>`:"";group=next;return `${heading}<button data-tab="${id}" class="${tab===id?"active":""}" ${tab===id?'aria-current="page"':""}>${label}</button>`;}).join("");
  const views={overview:overviewView,files:filesView,quality:qualityView,ai:extractionView,requirements:requirementsView,
    retrieval:retrievalView,assistant:assistantView,review:reviewView,tasks:tasksView,changes:changesView,
    report:reportView,members:membersView,audit:auditView,operations:operationsView};
  root.innerHTML=`<div class="project-heading"><div><div class="breadcrumb"><button class="plain" data-action="home">我的项目</button><span>/</span><span>${esc(labels[w.my_role])}</span></div><h1>${esc(w.name)}</h1><p class="input-version"><span>要求基线 ${data.baseline?`第${data.baseline.version}版`:"未发布"}</span><span>正式材料 ${data.material_set?`第${data.material_set.version}套`:"未发布"}</span></p></div><button class="small" data-action="refresh">刷新项目</button></div><div class="project-shell"><nav class="nav" aria-label="项目导航">${nav}</nav><div class="project-content"><label class="step-select" for="workspace-step">当前工作板块</label><select class="step-select" id="workspace-step" aria-label="当前工作板块">${sections.map(([id,label])=>`<option value="${id}" ${tab===id?"selected":""}>${label}</option>`).join("")}</select>${w.pending_requirement_changes?`<div class="hint warning"><strong>审查依据还有待处理变化</strong><p>要求变更尚未发布，或更正影响尚待处理。请到要求台账和更正影响核对后再完成报告。</p></div>`:""}<div id="section">${views[tab]()}</div></div></div>`;
  if($("#source-picker"))loadPicker().catch(e=>notice(explain(e),true));
  const loaders={quality:loadQualityView,ai:loadExtractionView,retrieval:loadRetrievalView,assistant:loadAssistantView,audit:loadAuditView,operations:loadOperationsView};
  if(loaders[tab])loaders[tab]();
  if(busy)root.querySelectorAll("button").forEach(button=>{button.dataset.wasDisabled=String(button.disabled);button.disabled=true;});
}
function overviewView() {
  const r=data.report,pending=data.requirements.filter(req=>req.status==="DRAFT").length;
  const next=!data.documents.length?["files","上传项目资料"]:!data.requirements.length?["requirements","整理第一条要求"]:
    pending||!data.baseline?["requirements","确认并发布要求"]:!data.material_set?["files","确定正式材料"]:
    r.unresolved_issue_count?["tasks","处理待整改问题"]:r.reviewed_count<r.requirement_count?["review","继续逐项核对"]:["report","查看本轮报告"];
  const steps=[["files","准备资料",data.documents.some(d=>d.revisions.some(v=>v.artifact_id))],["requirements","冻结要求",!!data.baseline],
    ["files","确定材料",!!data.material_set],["review","逐项核对",r.requirement_count>0&&r.reviewed_count===r.requirement_count],["report","交付报告",r.status==="REVIEW_COMPLETE"]];
  const mine=data.issues.filter(i=>i.task.assignee_id===user.id&&!["ACCEPTED","CANCELLED"].includes(i.task.effective_status));
  return `<section class="overview-focus"><div><span class="badge ${r.status==="REVIEW_COMPLETE"?"green":"amber"}">${esc(labels[r.status])}</span><h2>${r.status==="REVIEW_COMPLETE"?"本轮人工核对已完成":"每一项判断，都对应明确的文件版本"}</h2><p>先确定本轮要求与材料，再核对证据。上传、模型建议和整改验收都不会代替最终人工判断。</p></div><button class="primary" data-tab="${next[0]}">${next[1]}${icon("arrow")}</button></section><ol class="process-track">${steps.map(([id,name,done],i)=>`<li class="${done?"done":""}"><button data-tab="${id}"><span>${done?icon("check"):i+1}</span><strong>${name}</strong><small>${done?"已具备":"待完成"}</small></button></li>`).join("")}</ol><div class="overview-grid"><section class="panel"><div class="section-heading"><h2>本轮核对进度</h2><button class="plain" data-tab="report">查看报告</button></div><div class="coverage"><strong>${r.reviewed_count}<small> / ${r.requirement_count} 项</small></strong><span>已人工确认</span></div><progress max="${Math.max(1,r.requirement_count)}" value="${r.reviewed_count}" aria-label="已人工确认要求覆盖"></progress><dl class="summary-list"><div><dt>未解决问题</dt><dd>${r.unresolved_issue_count}</dd></div><div><dt>待确认要求</dt><dd>${pending}</dd></div><div><dt>待处理更正</dt><dd>${(data.change_impacts||[]).filter(i=>i.disposition==="PENDING").length}</dd></div></dl></section><section class="panel"><div class="section-heading"><h2>我的整改待办</h2><button class="plain" data-tab="tasks">全部任务</button></div>${mine.slice(0,5).map(i=>`<button class="todo-row" data-open-task="${esc(i.task.id)}"><span><strong>${esc(i.title)}</strong><small>${i.task.due_date?`截止 ${formatDate(i.task.due_date)}`:"未设置期限"}</small></span>${tag(i.task.effective_status)}</button>`).join("")||emptyState("当前没有分配给你的整改","可以继续核对要求，或在任务页查看团队进度。")}</section></div><section class="panel"><div class="section-heading"><h2>当前正式材料</h2><button class="plain" data-tab="files">查看与调整</button></div>${data.material_set?data.material_set.items.map(item=>`<div class="material-summary"><span>${icon()}</span><div><strong>${esc(item.title)}</strong><small>${item.submission_role==="REFERENCE"?"仅供参考，不作为满足证据":item.submission_role==="FORMAL_RESPONSE"?"正式投标响应":"正式证明附件"}</small></div><a class="button small" href="/api/v1/revisions/${esc(item.revision_id)}/original" target="_blank" rel="noopener">打开原件</a></div>`).join(""):emptyState("本轮材料还未确定","上传文件后，还需要明确选择实际采用的响应版本。",`<button data-tab="files">选择正式材料</button>`)}</section>`;
}
