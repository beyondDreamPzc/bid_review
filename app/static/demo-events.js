"use strict";
document.addEventListener("change", (event) => {
  if (event.target.id === "actor") { actor = event.target.value; render(); }
  if (event.target.matches("[data-check]")) {
    if (event.target.checked) confirmations.add(event.target.dataset.check);
    else confirmations.delete(event.target.dataset.check);
    const button = document.getElementById("confirm-selected");
    if (button) button.disabled = !confirmations.size || busy;
  }
});

document.addEventListener("click", async (event) => {
  const element = event.target.closest("button, a");
  if (!element || element.disabled) return;
  if (element.hasAttribute("data-close")) return closeModal();
  if (element.id === "begin") return begin();
  if (element.id === "reset") {
    if (!model) return begin();
    modalContent.innerHTML = `<div class="modal-head"><h2 id="modal-title">重新开始这次体验？</h2><button class="close-button" type="button" data-close aria-label="关闭">×</button></div><div class="modal-body"><p>会创建一份新的构造样例，从2小时与4小时的差异重新开始。不会删除已有项目或修改真实数据。</p></div><div class="modal-foot">${button("继续当前进度", "data-close", "")}${button("开始新的体验", 'data-reset="true"')}</div>`;
    return modal.showModal();
  }
  if (element.hasAttribute("data-reset")) { closeModal(); return begin(true); }
  if (element.hasAttribute("data-nav")) {
    if (!model) return toast("先点击“开始这次文件检查”，进入准备好的样例。");
    return setView(element.dataset.nav);
  }
  if (!model) return;
  if (element.hasAttribute("data-switch")) return setView(element.dataset.target || view, element.dataset.switch);
  if (element.hasAttribute("data-jump")) {
    selected = 0;
    setView("workbench");
    document.getElementById("requirement-detail").scrollIntoView({block:"center", behavior:"instant"});
    return;
  }
  if (element.hasAttribute("data-select")) {
    selected = Number(element.dataset.select);
    render();
    if (window.innerWidth < 800) document.getElementById("requirement-detail").scrollIntoView({block:"center", behavior:"instant"});
    return;
  }
  if (element.hasAttribute("data-open-issue")) return issueModal();
  if (element.hasAttribute("data-register")) {
    const note = document.getElementById("issue-note").value.trim();
    if (!note) return toast("请写下需要编写人修改的内容。", true);
    closeModal();
    await perform("open-issue", {note}, "问题已交给陈工，原文依据已保留。");
    return setView("tasks");
  }
  if (element.dataset.action === "start") return perform("start", {}, "已开始整改，可以修改当前响应文件。");
  if (element.hasAttribute("data-submit")) {
    const hours = Number(document.getElementById("hours").value);
    const note = document.getElementById("remediation-note").value.trim();
    if (!note) return toast("请填写整改说明，方便另一人复核。", true);
    return perform("submit", {hours, note}, "新版 PDF 已保存，整改已提交给审查人。");
  }
  if (element.hasAttribute("data-review")) {
    const note = document.getElementById("review-note").value.trim();
    if (!note) return toast("请写下你的复核意见。", true);
    return perform("review", {decision:element.dataset.review, note}, element.dataset.review === "ACCEPT" ? "整改已验收，这一项已人工确认满足。" : "已退回给陈工，原提交和意见仍保留。");
  }
  if (element.hasAttribute("data-confirm")) return perform("confirm", {requirement_ids:[element.dataset.confirm]}, "本项已人工确认，来源已写入记录。");
  if (element.id === "confirm-selected") return perform("confirm", {requirement_ids:[...confirmations]}, "勾选要求已确认，报告已更新。");
  if (element.hasAttribute("data-new-version")) {
    actor = "editor";
    return perform("new-version", {}, "新文件已保存。旧记录仍在，本轮需要重新核对。");
  }
  if (element.hasAttribute("data-source")) return showSource(element.dataset.source, element.dataset.block);
  if (element.hasAttribute("data-source-page") && preview) { preview.page = Number(element.dataset.sourcePage); renderSource(); }
});

modal.addEventListener("click", (event) => { if (event.target === modal) closeModal(); });

(async function initialise() {
  try { model = await request("/session"); }
  catch (error) { if (error.status !== 401) toast(error.status === 404 ? "演示入口尚未启用，请检查本地服务配置。" : "暂时连接不上服务，请稍后重试。", true); }
  render();
})();
