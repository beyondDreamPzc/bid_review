function sourceQuotes(refs) {return (refs||[]).map(r=>`<div class="quote">${esc(r.quote||r.text)}<small>第 ${r.page} 页 · <a target="_blank" rel="noopener" href="/api/v1/revisions/${esc(r.revision_id)}/original#page=${Number(r.page)||1}">打开对应原件 ↗</a></small></div>`).join("");}
function pickerFiles(mode) {
  if(["tender","amendment"].includes(mode)) return data.documents.filter(d=>mode==="amendment"?d.kind==="AMENDMENT":["TENDER","AMENDMENT"].includes(d.kind)).flatMap(d=>d.revisions.filter(r=>r.artifact_id).map(r=>({...r,title:d.title,document_id:d.id})));
  return (data.material_set?.items||[]).filter(i=>i.submission_role!=="REFERENCE").map(i=>{const r=data.documents.find(d=>d.id===i.document_id)?.revisions.find(r=>r.id===i.revision_id);return {...r,...i,id:i.revision_id};});
}
function pickerHtml(mode) {pickerMode=mode; return `<div class="picker" id="source-picker"><strong>${mode==="amendment"?"选择更正原文":mode==="tender"?"选择招标出处":"选择当前正式材料中的证据"}</strong><div id="picker-body">正在读取文件…</div><div id="selected-refs" class="selected-refs"></div></div>`;}
async function loadPicker() {
  const files=pickerFiles(pickerMode), container=$("#picker-body"); if(!container)return;
  const sequence=++pickerSequence;
  if(!files.length){container.innerHTML=empty(["tender","amendment"].includes(pickerMode)?"先上传并解析招标或更正文件。":"先在资料页发布本轮正式材料。");return;}
  if(!files.some(f=>f.artifact_id===pickerArtifact)) {pickerArtifact=files[0].artifact_id; pickerPage=1;pickerOffset=0;}
  const file=files.find(f=>f.artifact_id===pickerArtifact), pages=file.page_count||1; pickerPage=Math.min(pages,Math.max(1,pickerPage));
  const blocks=await api(`/api/v1/artifacts/${pickerArtifact}/blocks?page=${pickerPage}&offset=${pickerOffset}&limit=100`);
  if(sequence!==pickerSequence||!$("#picker-body"))return;
  container.innerHTML=`<label>文件版本<select id="picker-file">${files.map(f=>`<option value="${esc(f.artifact_id)}" ${f.artifact_id===pickerArtifact?"selected":""}>${esc(f.title)} · 第 ${f.revision_no} 版</option>`).join("")}</select></label><div class="picker-head"><button type="button" class="small" data-page="${pickerPage-1}" ${pickerPage<=1?"disabled":""}>上一页</button><label class="muted">页码<input id="picker-page" type="number" min="1" max="${pages}" value="${pickerPage}" aria-label="原文页码"></label><span class="muted">/ ${pages}</span><button type="button" class="small" data-page="${pickerPage+1}" ${pickerPage>=pages?"disabled":""}>下一页</button></div><div class="block-list">${blocks.length?blocks.map(b=>`<label class="block"><input type="checkbox" data-block="${esc(b.block_id)}" ${picks.some(p=>p.artifact_id===pickerArtifact&&p.block_id===b.block_id)?"checked":""}><span class="block-text">${esc(b.text)}</span></label>`).join(""):empty("此页未提取到文字，请打开原 PDF 检查。")}</div><div class="row">${pickerOffset?`<button class="small" type="button" data-offset="${Math.max(0,pickerOffset-100)}">上一组文字</button>`:""}${blocks.length===100?`<button class="small" type="button" data-offset="${pickerOffset+100}">下一组文字</button>`:""}<a class="small" target="_blank" rel="noopener" href="/api/v1/revisions/${esc(file.id)}/original#page=${pickerPage}">打开原 PDF ↗</a></div>`;
  container.blocks=blocks; container.file=file; renderPicks();
}
function renderPicks() {const el=$("#selected-refs"); if(el) el.innerHTML=`<p class="muted">已选 ${picks.length}/20 处原文</p>${picks.map((p,i)=>`<div class="selected-ref"><span>第 ${p.page} 页：${esc(p.quote||p.text)}</span><button type="button" class="plain small" data-remove-ref="${i}" aria-label="移除第 ${i+1} 处引用">移除</button></div>`).join("")}`;}
const refs=()=>picks.map(p=>({artifact_id:p.artifact_id,block_id:p.block_id}));
