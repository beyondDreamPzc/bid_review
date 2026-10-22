"use strict";
function reasonField(label="操作原因"){return `<label>${label}<textarea name="note" minlength="5" maxlength="2000" required placeholder="写明具体原因，至少5个字符"></textarea></label>`;}
function lifecycleDialog({title,description,body="",submitLabel="保存",danger=false,path,payload,message}) {
  openDialog({title,description,body:body+reasonField(),submitLabel,danger,onSubmit:values=>act(()=>write(path,{...payload,...values}),message)});
}
document.addEventListener("click",event=>{
  const el=event.target.closest("button");if(!el||busy||!data)return;
  if(el.dataset.reassign){
    const task=data.issues.find(i=>i.task.id===el.dataset.reassign).task;
    return openDialog({title:"转派任务或调整期限",description:"提交与复核记录会保留；转派不会变成验收通过。",body:`<label>新负责人<select name="assignee_id">${data.members.filter(m=>["OWNER","EDITOR"].includes(m.role)).map(m=>`<option value="${esc(m.user_id)}" ${m.user_id===task.assignee_id?"selected":""}>${esc(m.name)}</option>`).join("")}</select></label><label>整改期限<input type="date" name="due_date" value="${esc(task.due_date||"")}"></label>${reasonField("调整说明")}`,onSubmit:values=>act(()=>write(base()+`/tasks/${task.id}/assignment`,{...values,due_date:values.due_date||null,expected_version:task.version}),"任务负责人和期限已更新。")});
  }
  if(el.dataset.withdrawIssue){const issue=data.issues.find(i=>i.id===el.dataset.withdrawIssue),withdrawn=issue.task.status!=="CANCELLED";
    return lifecycleDialog({title:withdrawn?"撤销这项问题？":"恢复整改问题",description:withdrawn?"撤销后不再阻塞当前报告，但会让旧判断失效。历史不删除，需要重新判断。":"恢复后进入待整改；原负责人需仍具备编辑权限，否则先转派。",submitLabel:withdrawn?"确认撤销":"恢复问题",danger:withdrawn,path:base()+`/issues/${issue.id}/lifecycle`,payload:{expected_version:issue.task.version,withdrawn},message:withdrawn?"问题已撤销，请重新判断对应要求。":"问题已恢复。"});}
  if(el.dataset.retireRequirement){const req=[...data.requirements,...(data.retired_requirements||[])].find(r=>r.requirement_id===el.dataset.retireRequirement),retired=el.dataset.retired==="true";
    return lifecycleDialog({title:retired?"退休这条要求？":"恢复这条要求",description:"保留全部历史。先处理关联问题，再通过重新发布基线明确本轮要求范围。",submitLabel:retired?"退休要求":"恢复要求",danger:retired,path:base()+`/requirements/${req.requirement_id}/lifecycle`,payload:{expected_revision_no:req.revision_no,retired},message:"要求状态已更新，请核对并重新发布要求基线。"});}
  if(el.dataset.memberRole){const member=data.members.find(m=>m.user_id===el.dataset.memberRole);
    return openDialog({title:"调整项目角色",description:`${member.name}的新角色只影响本项目；降为非编辑角色前需先转派任务。`,body:`<label>角色<select name="role">${["EDITOR","REVIEWER","READER"].map(role=>`<option value="${role}" ${member.role===role?"selected":""}>${labels[role]}</option>`).join("")}</select></label>`,onSubmit:values=>act(()=>write(base()+"/members",{user_id:member.user_id,role:values.role,expected_role:member.role}),"项目角色已更新。")});}
  if(el.dataset.memberRemove){const member=data.members.find(m=>m.user_id===el.dataset.memberRemove);
    return lifecycleDialog({title:"移除项目成员？",description:`完成${member.name}的任务交接后撤销本项目访问。历史署名保留。`,submitLabel:"移除成员",danger:true,path:base()+`/members/${member.user_id}/remove`,payload:{},message:"该成员的项目权限已移除。"});}
  if(el.dataset.impactDecision){const impact=data.change_impacts.find(i=>i.id===el.dataset.impactDecision),disposition=el.dataset.disposition;
    return lifecycleDialog({title:disposition==="REVISED"?"确认更正已经落实到要求":"确认更正不需修改此要求",description:disposition==="REVISED"?"最新要求修订须已确认，且包含这份更正的原文出处。":"请说明对照了哪些条件、为什么不需要修改。处理后仍需重新核对响应。",path:base()+`/change-impacts/${impact.id}/decision`,payload:{expected_version:impact.version,disposition},message:"更正影响已处理，请继续核对当前要求。"});}
  if(el.dataset.retryConversion)return act(()=>write(base()+`/conversions/${el.dataset.retryConversion}/retry`,{}),"已重新登记转换任务。");
});
document.addEventListener("submit",event=>{
  if(event.target.id!=="impact-form")return;event.preventDefault();if(busy)return;
  const values=Object.fromEntries(new FormData(event.target));
  act(async()=>{if(!picks.length)throw new Error("请选择至少一处更正原文。");await write(base()+"/change-impacts",{...values,sources:refs()});resetPicker();},"已关联更正，相关要求需要重新核对。");
});
