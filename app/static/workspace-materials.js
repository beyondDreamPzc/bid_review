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
