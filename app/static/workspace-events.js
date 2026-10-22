document.addEventListener("submit", async event=>{
  const form=event.target; event.preventDefault(); if(busy)return; const values=Object.fromEntries(new FormData(form));
  if(form.id==="login-form")return act(async()=>{const session=await api("/api/v1/auth/session",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)}); form.reset(); user=session.user; await resumeSessionRoute();refreshUnread();},"登录成功",false);
  if(form.id==="project-form")return act(async()=>{const p=await write("/api/v1/projects",{name:values.name.trim()});await openProject(p.id);},"项目已创建",false);
  if(form.id==="upload-form")return act(async()=>{
    const body=new FormData(),file=form.elements.file.files[0];body.set("file",file);
    const existing=values.document_id?data.documents.find(d=>d.id===values.document_id):null;
    const title=existing?.title||values.title?.trim(),kind=existing?.kind||values.kind;
    if(!title)throw new Error("请填写文档名称。");
    const docx=file.name.toLowerCase().endsWith(".docx");
    if(docx||!existing){body.set("title",title);body.set("kind",kind);}
    if(docx&&existing)body.set("document_id",existing.id);
    await write(docx?base()+"/conversions":existing?`/api/v1/documents/${existing.id}/revisions`:base()+"/documents",body,true);
  },"文件已接收，后台将处理并保留原件。");
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
  if(el.dataset.tab){goSection(el.dataset.tab);return;}
  if(el.dataset.page){pickerPage=Number(el.dataset.page);pickerOffset=0;return act(()=>loadPicker(),null,false);}
  if(el.dataset.offset!==undefined){pickerOffset=Number(el.dataset.offset);return act(()=>loadPicker(),null,false);}
  if(el.dataset.removeRef!==undefined){picks.splice(Number(el.dataset.removeRef),1);renderPicks();return loadPicker().catch(e=>notice(explain(e),true));}
  if(el.dataset.edit){draft=data.requirements.find(r=>r.requirement_id===el.dataset.edit);picks=[...draft.sources];render();$("#requirement-form")?.scrollIntoView({behavior:"smooth",block:"start"});return;}
  if(el.dataset.reparse)return act(async()=>{await write(`/api/v1/revisions/${el.dataset.reparse}/parse`,{retry_failed:true});},"已登记解析任务，旧出处和已发布材料保持原版本。");
  if(el.dataset.confirm){const r=data.requirements.find(r=>r.requirement_id===el.dataset.confirm);return act(()=>write(base()+`/requirements/${r.requirement_id}/confirm`,{expected_revision_no:r.revision_no}),"要求已确认，可以纳入基线。");}
  if(el.dataset.review){tab="review";selectedRequirement=el.dataset.review;resetPicker();render();return;}
  if(el.dataset.task){selectedTask=el.dataset.task;resetPicker();render();focusContent("#task-detail");return;}
  if(el.dataset.start){const t=data.issues.find(i=>i.task.id===el.dataset.start).task;return act(()=>write(base()+`/tasks/${t.id}/transitions`,{action:"START",expected_version:t.version,expected_epoch:data.workspace.review_epoch}),"已开始整改。");}
  if(el.dataset.action==="home")return act(home,null,false);
  if(el.dataset.action==="logout")return act(async()=>{await api("/api/v1/auth/session",{method:"DELETE"});pendingKeys.clear();clearViewTimers();dirty=false;user=null;data=null;projectId=null;setRoute("");renderLogin();},"已退出登录",false);
  if(el.dataset.action==="refresh")return act(loadProject,"项目已刷新",false);
  if(el.dataset.action==="new-requirement"){draft=null;resetPicker();render();return;}
  if(el.dataset.action==="publish-baseline")return act(()=>write(base()+"/baselines",{name:"网页确认要求基线",expected_epoch:data.workspace.review_epoch,expected_current_baseline_id:data.workspace.current_baseline_id,requirement_revision_ids:data.requirements.filter(r=>!r.retired).map(r=>r.revision_id)}),"已发布要求基线；旧结论需按新基线重新核对。");
  if(el.dataset.action==="task-history")return act(async()=>{const history=await api(base()+`/tasks/${selectedTask}/submissions`);$("#task-history").innerHTML=history.map(s=>`<div class="history"><strong>${esc(who(s.submitted_by))}</strong><p>${esc(s.note)}</p>${sourceQuotes(s.evidence)}</div>`).join("")||empty("尚无提交历史。");},null,false);
});
document.addEventListener("change",event=>{
  const el=event.target;if(busy)return;
  if(el.closest("#material-form")) $("#materials-selector").dataset.dirty="true";
  if(el.name==="document_id")$("#new-document-fields").hidden=!!el.value;
  if(el.id==="workspace-step"){goSection(el.value);}
  if(el.id==="picker-file"){pickerArtifact=el.value;pickerPage=1;pickerOffset=0;act(loadPicker,null,false);}
  if(el.id==="picker-page"){pickerPage=Number(el.value)||1;pickerOffset=0;act(loadPicker,null,false);}
  if(el.id==="review-requirement"){selectedRequirement=el.value;resetPicker();render();focusContent();}
  if(el.dataset.block){const idx=picks.findIndex(p=>p.artifact_id===pickerArtifact&&p.block_id===el.dataset.block);if(el.checked&&idx<0){if(picks.length>=20){el.checked=false;notice("每次最多引用 20 处原文。",true);return;}const container=$("#picker-body"),block=container.blocks.find(b=>b.block_id===el.dataset.block);picks.push({...block,artifact_id:pickerArtifact,revision_id:container.file.id});}else if(!el.checked&&idx>=0)picks.splice(idx,1);renderPicks();}
});