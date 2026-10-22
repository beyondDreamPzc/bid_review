"use strict";
function welcome() {
  return `<section class="welcome"><div class="welcome-layout"><div class="welcome-copy"><span class="eyebrow">3 分钟，体验一份文件怎样被检查</span><h1>对方要 2 小时，<br>我们却写了 4 小时。</h1><p>你是一家服务商，准备承接一个运维项目。<br>对方写下要求，你的团队提交方案。这个工作台帮你们对照文件、把问题交给人改，再检查是否真的改好了。</p>
      ${button(busy ? "正在生成演示文件和项目…" : "开始这次文件检查 →", 'id="begin"')}<p style="font-size:11px;margin-top:13px">不用懂招标，也不用配置账号。样例文件和两位演示角色已备好。</p></div>
      <div class="welcome-card"><div class="label">城市服务平台运维项目 / 构造样例</div><div class="welcome-quote"><small class="muted">采购方的要求 · 招标文件</small><br>接报后应在 <strong>2 小时</strong> 内响应。</div><div class="welcome-quote difference"><small class="muted">我们的承诺 · 技术响应书</small><br>我们承诺在 <strong>4 小时</strong> 内响应。</div><div class="conflict-line"><span>! 两份文件的承诺不一致</span><span>交给谁改？ →</span></div></div></div>
      <div class="concepts"><div class="concept"><span class="number">01 /</span><h3>先把原文放到一起</h3><p>不是看一个红绿分数，而是看到要求、承诺和具体页码。</p></div><div class="concept"><span class="number">02 /</span><h3>让负责的人修改文件</h3><p>体验审查人和编写人两个角色，问题有去向，修改有说明。</p></div><div class="concept"><span class="number">03 /</span><h3>改完，再由另一人确认</h3><p>看看新版文件、原来的问题和最后的人工检查记录。</p></div></div></section>`;
}

function render() {
  main.setAttribute("aria-busy", String(busy));
  if (!model) main.innerHTML = welcome();
  else main.innerHTML = ({workbench, tasks: tasksView, materials: materialsView, report: reportView}[view] || workbench)();
  if (busy) for (const control of main.querySelectorAll("button,input,select,textarea")) control.disabled = true;
  for (const item of document.querySelectorAll("#navigation [data-nav]")) {
    item.classList.toggle("active", item.dataset.nav === view);
    item.disabled = busy;
    if (item.dataset.nav === view) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  document.getElementById("reset").disabled = busy;
}

function setView(next, nextActor) {
  if (nextActor) actor = nextActor;
  view = next;
  render();
  window.scrollTo({top: 0, behavior: "instant"});
  requestAnimationFrame(()=>{const heading=main.querySelector("h1,h2");if(heading){heading.tabIndex=-1;heading.focus();}});
}

function closeModal() { modal.close(); preview = null; }

function issueModal() {
  modalContent.innerHTML = `<div class="modal-head"><h2 id="modal-title">把这处问题交给编写人</h2><button type="button" class="close-button" data-close aria-label="关闭">×</button></div><div class="modal-body"><p>采购方要求2小时，我们的正式响应写了4小时。登记后，陈工会收到这条整改任务。</p><label class="field-label" for="issue-note">告诉陈工需要改什么</label><textarea id="issue-note" class="textarea">招标文件要求2小时内响应，技术响应书却承诺4小时。请修正承诺并核对相关章节。</textarea><div class="task-facts"><div><small>交给谁</small>陈工 · 编写人</div><div><small>改完谁检查</small>林悦 · 审查人</div></div><p>系统会保留登记时的原文和页码，后续改文件也不会覆盖这条依据。</p></div><div class="modal-foot">${button("取消", "data-close", "")}${button("登记问题，交给陈工 →", 'data-register="true"')}</div>`;
  modal.showModal();
}

async function showSource(revisionId, blockId) {
  try {
    const document = await request(`/documents/${encodeURIComponent(revisionId)}`);
    const highlighted = document.blocks.find((block) => block.id === blockId);
    preview = {document, blockId, page: highlighted?.page || 2};
    renderSource();
    if (!modal.open) modal.showModal();
  } catch (error) { toast(error.message, true); }
}

function renderSource() {
  const {document, page, blockId} = preview;
  modalContent.innerHTML = `<div class="modal-head"><div><h2 id="modal-title">${escapeHtml(document.title)} · 第${document.version}稿</h2><small class="muted">来自实际 PDF 的文字层，可打开原件核对排版与上下文。</small></div><button type="button" class="close-button" data-close aria-label="关闭原文">×</button></div><div class="modal-body"><div class="document-meta"><div>${Array.from({length:document.page_count}, (_, index) => button(`第${index+1}页`, `data-source-page="${index+1}"`, page === index+1 ? "small primary" : "small")).join(" ")}</div><a href="${document.original_url}" class="button small" target="_blank" rel="noopener">打开 PDF 原件 ↗</a></div><section class="document-page" aria-label="PDF第${page}页文字">${document.blocks.filter((block) => block.page === page).map((block) => `<p class="${block.id === blockId ? "highlight" : ""}">${escapeHtml(block.text)}</p>`).join("")}<small>PDF 实际第 ${page} 页 / 共 ${document.page_count} 页</small></section></div>`;
}
