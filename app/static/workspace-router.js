"use strict";
let lastRoute=location.hash.slice(1),filterTimer=null;
function setRoute(route) {
  lastRoute=route;history.replaceState(null,"",location.pathname+location.search+(route?"#"+route:""));
}
function setProjectRoute() {
  if(!projectId)return;
  const query=new URLSearchParams();
  if(["files","requirements","tasks","audit"].includes(tab)){
    const s=stateFor(tab);if(s.q)query.set("q",s.q);if(s.filter)query.set("status",s.filter);if(s.page>1)query.set("page",s.page);
  }
  setRoute(`/projects/${projectId}/${tab}`+(query.size?"?"+query.toString():""));
}
function goSection(section) {
  if(!data)return;
  guardUnsaved(()=>{clearViewTimers();tab=section;draft=null;resetPicker();render();focusContent();});
}
async function resumeSessionRoute(route=location.hash.slice(1)) {
  if(["/account","/notifications"].includes(route))return showGlobal(route.slice(1));
  const [path,search]=route.split("?"),match=/^\/projects\/([a-f0-9-]{36})\/([a-z]+)$/.exec(path);
  if(match&&sectionInfo.some(([id])=>id===match[2])) {
    projectId=match[1];tab=match[2];const s=stateFor(tab),params=new URLSearchParams(search||"");
    s.q=(params.get("q")||"").slice(0,100);s.filter=(params.get("status")||"").slice(0,30);s.page=Math.max(1,Math.min(100000,Number(params.get("page"))||1));
    return openProject(match[1],match[2]);
  }
  return home();
}
function refreshList(name) {
  const renderers={files:["#file-list",fileList],requirements:["#requirements-list",requirementList],tasks:["#tasks-list",taskList]};
  if(name==="audit"){loadAuditView();setProjectRoute();return;}
  const entry=renderers[name];if(entry&&$(entry[0]))$(entry[0]).innerHTML=entry[1]();setProjectRoute();
}
document.addEventListener("click",event=>{
  const el=event.target.closest("button");if(!el||busy)return;
  const navigation=el.matches("[data-tab],[data-project],[data-task],[data-review],[data-edit],[data-open-task],[data-quality-artifact],[data-quality-page],[data-ai-run],[data-action=home],[data-action=refresh],[data-action=logout],[data-action=new-requirement]");
  if(navigation&&dirty){event.preventDefault();event.stopImmediatePropagation();guardUnsaved(()=>el.click());}
},true);
document.addEventListener("change",event=>{
  const el=event.target,previous={"workspace-step":tab,"quality-file":qualityArtifact,"review-requirement":selectedRequirement}[el.id];
  if(previous!==undefined&&dirty){const next=el.value;event.stopImmediatePropagation();el.value=previous;guardUnsaved(()=>{el.value=next;el.dispatchEvent(new Event("change",{bubbles:true}));});}
},true);
document.addEventListener("click",event=>{
  const el=event.target.closest("button");if(!el||busy)return;
  if(el.hasAttribute("data-new-project"))return openDialog({title:"创建投标项目",description:"同一项目保存招标、响应、要求与审核历史，不与其他项目混用。",body:`<label>项目名称<input name="name" maxlength="200" required placeholder="例如：客户服务平台运维投标"></label>`,submitLabel:"创建项目",onSubmit:values=>act(async()=>{const project=await write("/api/v1/projects",{name:values.name.trim()});await openProject(project.id);},"项目已创建。",false)});
  if(el.dataset.openTask){selectedTask=el.dataset.openTask;tab="tasks";resetPicker();render();focusContent("#task-detail h2");return;}
  if(el.dataset.listPage){const name=el.dataset.listPage,s=stateFor(name);s.page=Math.max(1,s.page+Number(el.dataset.direction));refreshList(name);focusContent(name==="audit"?"#audit-list table":name==="files"?"#file-list h3":`#${name}-list h3`);return;}
  if(el.dataset.listReset){const name=el.dataset.listReset,s=stateFor(name);s.q="";s.filter="";s.page=1;const toolbar=document.querySelector(`[data-list-toolbar="${name}"]`);toolbar.querySelector("input").value="";if(toolbar.querySelector("select"))toolbar.querySelector("select").value="";refreshList(name);}
});
document.addEventListener("input",event=>{
  const name=event.target.dataset.listQ;if(!name)return;const s=stateFor(name);s.q=event.target.value;s.page=1;
  clearTimeout(filterTimer);filterTimer=setTimeout(()=>refreshList(name),180);
});
document.addEventListener("change",event=>{
  const el=event.target;if(el.dataset.listFilter){const s=stateFor(el.dataset.listFilter);s.filter=el.value;s.page=1;refreshList(el.dataset.listFilter);}
  if(el.dataset.block)dirty=true;
});
window.addEventListener("hashchange",()=>{
  const next=location.hash.slice(1);if(next===lastRoute)return;
  const previous=lastRoute;setRoute(previous);
  if(busy){notice("当前操作尚未结束，请稍后切换。",true);return;}
  guardUnsaved(()=>act(()=>resumeSessionRoute(next),null,false));
});
document.addEventListener("keydown",event=>{
  if(event.key==="/"&&!event.ctrlKey&&!event.metaKey&&!event.target.matches("input,textarea,select,[contenteditable]")) {
    const input=root.querySelector("input[type=search]");if(input){event.preventDefault();input.focus();}
  }
});
(async()=>{
  try {const session=await api("/api/v1/auth/session");user=session.user;await resumeSessionRoute();refreshUnread();}
  catch(error){if(error.status!==401){root.innerHTML=failureState(explain(error),"home");head();notice(explain(error),true);}}
  finally{root.setAttribute("aria-busy","false");}
})();
