/* 演示交互调用真实后端；浏览器只保存视图偏好，不保存 API Key 或业务结论。 */
const main = document.getElementById("main");
const modal = document.getElementById("modal");
const modalContent = document.getElementById("modal-content");
let model = null;
let view = "workbench";
let actor = "reviewer";
let selected = 0;
let busy = false;
let toastTimer;
let preview = null;
const confirmations = new Set();
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const quote = (text) => escapeHtml(text).replace(/(\d+)(小时|次|名)/g, "<mark>$1 $2</mark>");
const task = () => model?.issue?.task;
const isStale = () => task()?.effective_status === "NEEDS_RECHECK";
const complete = () => Boolean(model?.report.manual_review_complete);
const button = (text, attributes, kind = "primary") => `<button type="button" class="button ${kind}" ${attributes} ${busy ? "disabled" : ""}>${busy && kind === "primary" ? '<span class="spinner" aria-hidden="true"></span>' : ""}${text}</button>`;
const chip = (text, color = "") => `<span class="status ${color}">${text}</span>`;

function toast(message, error = false) {
  const element = document.getElementById("toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.hidden = true; }, error ? 7000 : 4200);
}

async function request(path, options = {}) {
  const response = await fetch(`/demo/api${path}`, {credentials: "same-origin", ...options,
    headers: {"Content-Type": "application/json", ...options.headers}});
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : "请检查输入内容后再试");
    error.status = response.status;
    throw error;
  }
  return data;
}

async function begin(reset = false) {
  busy = true;
  render();
  try {
    model = await request("/session", {method: "POST", body: JSON.stringify({reset})});
    view = "workbench";
    actor = "reviewer";
    selected = 0;
    confirmations.clear();
    if (reset) toast("新的演示已准备好，可以从头体验。");
  } catch (error) {
    toast(error.message, true);
  } finally {
    busy = false;
    render();
  }
}

async function perform(action, extra = {}, success = "已保存") {
  if (!model || busy) return;
  const body = {expected_epoch: model.versions.epoch,
    expected_material_set_id: model.versions.material_set_id,
    expected_task_version: task()?.version ?? null,
    submission_id: task()?.current_submission?.id ?? null, ...extra};
  const key = crypto.randomUUID();
  const options = {method: "POST", headers: {"Idempotency-Key": key, "X-Demo-Actor": actor}, body: JSON.stringify(body)};
  busy = true;
  render();
  try {
    try { await request(`/actions/${action}`, options); }
    catch (error) {
      if (error.status) throw error;
      await request(`/actions/${action}`, options); // Network retry keeps the original key and payload.
    }
    model = await request("/session");
    confirmations.clear();
    toast(success);
  } catch (error) {
    if (error.status === 409) toast("材料或任务已经更新，已为你刷新。请核对当前内容后再操作。", true);
    else if (error.status === 403) toast("请使用这一步对应的演示角色操作。", true);
    else toast(/[A-Za-z]{4,}/.test(error.message) ? "操作未完成，请检查当前任务状态后重试。" : error.message, true);
    try { model = await request("/session"); } catch { /* Keep the existing view if the service is briefly unreachable. */ }
  } finally {
    busy = false;
    render();
  }
}

function stage() {
  if (complete()) return 4;
  if (isStale()) return 1;
  if (!model.issue) return 0;
  if (["TODO", "IN_PROGRESS", "RETURNED"].includes(task().status)) return 1;
  if (task().status === "SUBMITTED") return 2;
  return 3;
}

function actorControl() {
  const current = model.actors.find((person) => person.key === actor);
  return `<div class="actor-switch"><span class="avatar">${current.name[0]}</span><div><div class="label">你正在扮演</div>
    <select id="actor" aria-label="切换演示角色" ${busy ? "disabled" : ""}>${model.actors.map((person) =>
      `<option value="${person.key}" ${person.key === actor ? "selected" : ""}>${person.title} · ${person.name}</option>`).join("")}</select></div></div>`;
}

function pageTitle(title, description) {
  return `<div class="page-title"><div><h1>${title}</h1><p>${description}</p></div>${actorControl()}</div>`;
}

function steps() {
  const current = stage();
  return `<div class="steps" aria-label="体验进度">${["看清要求与承诺", "登记问题并修改", "由另一人复核", "确认本轮结果"].map((label, index) =>
    `<div class="step ${current === index ? "current" : current > index ? "done" : ""}"><span class="step-number">${current > index ? "✓" : index + 1}</span>${label}</div>`).join("")}</div>`;
}

function guide() {
  const current = stage();
  let title, description, action = "";
  if (current === 0) {
    title = "先看第一项：对方要 2 小时，我们却写了 4 小时";
    description = "你是提供服务的一方。把这处差异交给编写人修改，而不是直接判整份方案不合格。";
    action = button("查看这处差异 →", 'data-jump="first"', "subtle");
  } else if (isStale()) {
    title = "文件又更新了，旧的“已通过”不能直接沿用";
    description = "历史结论还在，但要针对这份新文件重新检查。先让编写人提交本轮材料，再复核。";
    action = button("切到编写人重新核对 →", 'data-switch="editor" data-target="tasks"', "subtle");
  } else if (current === 1) {
    title = task().status === "RETURNED" ? "审查人退回了整改，请继续修改" : "问题已交给陈工，接下来体验编写人的工作";
    description = model.hours > 2 ? "切换角色后，开始整改，把响应文件中的4小时改成2小时，再提交给别人复核。" : "当前文件已写2小时，请核对本轮原文后重新提交；旧文件的验收不能直接沿用。";
    action = button("切到编写人 →", 'data-switch="editor" data-target="tasks"', "subtle");
  } else if (current === 2) {
    title = "响应文件已提交，现在请另一人来检查";
    description = "提交修改只是第一步。审查人要回看新版原文，确认承诺真的改对，才能验收。";
    action = button("切到审查人复核 →", 'data-switch="reviewer" data-target="tasks"', "subtle");
  } else if (current === 3) {
    title = "这处整改已通过，还有其他要求需要逐项确认";
    description = "没有发现问题，也不代表已经检查过。在报告中核对剩余两项，再明确记录满足。";
    action = button("查看检查报告 →", 'data-switch="reviewer" data-target="report"', "subtle");
  } else {
    title = "本轮 3 项要求都已由人核对，整改也已复核";
    description = "现在可以看到完整结果及修改依据，也可以体验“文件又变了，旧结论怎么办”。";
    action = button("查看本轮结果 →", 'data-nav="report"', "subtle");
  }
  return `<section class="guide ${isStale() ? "warning" : ""}"><div class="guide-icon" aria-hidden="true">${complete() ? "✓" : "↗"}</div><div><h3>${title}</h3><p>${description}</p></div>${action}</section>`;
}

function stats() {
  const open = model.report.unresolved_issue_count;
  const differences = !model.issue && model.hours > 2 ? 1 : open;
  return `<div class="stats"><div class="stat"><div class="stat-icon">▤</div><div><div class="stat-value">3<span>项</span></div><div class="stat-label">本轮需要核对的要求</div></div></div>
    <div class="stat"><div class="stat-icon amber">!</div><div><div class="stat-value">${differences}<span>处</span></div><div class="stat-label">${!model.issue ? "预设样例中的疑似差异" : "仍需处理或重核的问题"}</div></div></div>
    <div class="stat"><div class="stat-icon green">✓</div><div><div class="stat-value">${model.report.reviewed_count}<span>/ 3</span></div><div class="stat-label">已针对当前文件人工确认</div></div></div></div>`;
}

function rowStatus(row, index) {
  if (row.report.status === "REVIEWED") return chip("已确认满足", "green");
  if (index === 0 && isStale()) return chip("需要重新核对", "amber");
  if (index === 0 && model.issue) {
    if (task().status === "SUBMITTED") return chip("等待他人复核", "amber");
    if (task().status !== "ACCEPTED") return chip("需要整改", "red");
  }
  if (index === 0 && model.hours > 2) return chip("疑似冲突", "amber");
  return chip("待人工核对");
}

function sources(row) {
  const different = row === model.requirements[0] && model.hours > 2;
  return `<div class="compare">${[row.tender, row.response].map((source, index) =>
    `<section class="source-card ${index && different ? "difference" : ""}"><header><span class="file-letter">PDF</span>${index ? "我们的承诺" : "采购方的要求"}</header>
      <div class="quote">${quote(source.quote)}</div><footer><span>${escapeHtml(source.filename)} · 第${source.page}页${index ? ` · 第${source.revision_no}稿` : ""}</span>
      <button type="button" data-source="${source.revision_id}" data-block="${source.block_id}">看原文 ↗</button></footer></section>`).join("")}</div>`;
}

function detail(row, index) {
  let explanation, actions;
  const reviewed = row.report.status === "REVIEWED";
  if (index === 0 && !model.issue) {
    explanation = "采购方希望2小时内响应，我们的文件却承诺4小时。先请人确认这处差异，再交给编写人修改。";
    actions = actor === "reviewer" ? button("确认这处问题并指派 →", 'data-open-issue="true"') : button("切到审查人登记问题", 'data-switch="reviewer" data-target="workbench"');
  } else if (index === 0 && model.issue && !reviewed) {
    explanation = isStale() ? "这项要求曾经通过，但响应文件又更新了。需要针对当前版本重新核对。" : "问题登记时的原文和修改后的原文分别保留。请到整改页查看负责人和本次提交。";
    actions = button(task().status === "SUBMITTED" ? "查看整改并复核 →" : "查看整改任务 →", 'data-nav="tasks"');
  } else if (reviewed) {
    explanation = "这一项已经有人对照当前文件确认满足。审核人和来源保留在检查记录中。";
    actions = button("查看检查报告", 'data-nav="report"', "subtle");
  } else {
    explanation = `${row.explanation} 请对照两边原文，检查数量和表述是否一致。`;
    actions = actor === "reviewer" ? button("已核对，确认此项满足 ✓", `data-confirm="${row.id}"`) : button("切到审查人确认", 'data-switch="reviewer" data-target="workbench"');
  }
  return `<section class="panel" id="requirement-detail"><div class="detail-title"><div><h2>${row.title}</h2><p>要求 ${row.number} · ${row.explanation}</p></div>${rowStatus(row, index)}</div>${sources(row)}
    <div class="comparison-caption">原文与页码来自实际演示 PDF，可点击“看原文”核对上下文。</div>
    <div class="explanation ${index || reviewed ? "neutral" : ""}">${explanation}</div>
    <div class="detail-actions">${actions}<span class="muted">${actor === "reviewer" ? "当前：审查人 林悦" : "当前：编写人 陈工"}</span></div></section>`;
}

function workbench() {
  const row = model.requirements[selected];
  return `${pageTitle("要求核对", "把对方的要求与我们文件里的承诺放在一起看。")}${guide()}${steps()}${stats()}
    <div class="workbench-grid"><section class="panel"><div class="panel-heading"><h2>本次检查清单</h2><small>3 项要求</small></div>
      ${model.requirements.map((item, index) => `<button type="button" class="requirement-row ${index === selected ? "selected" : ""}" data-select="${index}" aria-pressed="${index === selected}">
        <div class="row-top"><span class="requirement-number">${item.number}</span>${rowStatus(item, index)}</div><h3>${item.title}</h3><p>${item.target}</p></button>`).join("")}</section>${detail(row, selected)}</div>
    <p class="below-note">这里的3条要求已为体验预先整理好。真实工作中，需要先从招标文件整理并确认完整要求。</p>`;
}

function historyPanel() {
  const formatTime = (value) => new Date(value.endsWith("Z") ? value : value + "Z").toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"});
  return `<section class="panel"><div class="panel-heading"><h2>处理记录</h2><small>操作自动保存</small></div><ol class="task-history">${model.history.slice(-9).map((event) =>
    `<li><strong>${escapeHtml(event.actor)}</strong> ${escapeHtml(event.text)}<time>${formatTime(event.at)}</time></li>`).join("")}</ol></section>`;
}

function tasksView() {
  let content;
  if (!model.issue) {
    content = `<div class="panel empty-state"><h2>还没有登记问题</h2><p>先到“要求核对”对照2小时与4小时的差异，再明确告诉编写人要改什么。</p>${button("回到原文比对 →", 'data-jump="first"')}</div>`;
  } else {
    const currentTask = task();
    const row = model.requirements[0];
    const labels = {TODO:"待编写人开始", IN_PROGRESS:"正在整改", SUBMITTED:"等待他人复核", ACCEPTED:"已复核通过", RETURNED:"已退回，继续修改", NEEDS_RECHECK:"新文件需要重新核对"};
    let taskAction = "";
    if (["TODO", "RETURNED"].includes(currentTask.status) || isStale()) {
      taskAction = actor === "editor" ? button(isStale() ? "开始重新核对当前文件" : "开始整改", 'data-action="start"') : button("切到编写人处理 →", 'data-switch="editor" data-target="tasks"');
    } else if (currentTask.status === "IN_PROGRESS") {
      taskAction = actor === "editor" ? `<label class="field-label" for="hours">${model.hours > 2 ? "把响应文件中的承诺改为" : "确认本轮文件的响应承诺"}</label><div class="editor-line">我们承诺接报后在 <select class="select" id="hours" aria-label="新的响应时间"><option value="2">2 小时</option><option value="4">4 小时</option></select> 内响应。</div>
        <label class="field-label" for="remediation-note">告诉审查人，你做了什么</label><textarea class="textarea" id="remediation-note">${model.hours > 2 ? "已把响应时限从4小时修正为2小时，并核对了相关章节。" : "已重新核对本轮文件，确认2小时承诺保持一致，提交本轮复核。"}</textarea>
        <p>修改内容会保存为新的真实 PDF；内容未变则沿用当前文件，再提交本轮复核。</p>${button("保存文件并提交复核 →", 'data-submit="true"')}` : `<p>只有任务负责人陈工可以提交整改，林悦负责稍后的复核。</p>${button("切到编写人继续 →", 'data-switch="editor" data-target="tasks"')}`;
    } else if (currentTask.status === "SUBMITTED") {
      taskAction = `<div class="result-list"><div class="result-item"><strong>陈工的整改说明</strong><div class="muted">${escapeHtml(currentTask.current_submission.note)}</div></div></div>`;
      if (actor === "reviewer") {
        taskAction += `<label class="field-label" for="review-note">你的复核意见</label><textarea class="textarea" id="review-note">${model.hours <= 2 ? "已核对新版原文，2小时承诺满足招标要求，接受本次整改。" : "当前文件仍写4小时，不满足2小时要求，请继续修改。"}</textarea><div class="detail-actions" style="padding-left:0;padding-bottom:0;border:0">`;
        if (model.hours <= 2) taskAction += button("验收并确认此项满足 ✓", 'data-review="ACCEPT"');
        taskAction += button("仍需修改，退回", 'data-review="RETURN"', "danger") + "</div>";
        if (model.hours > 2) taskAction += '<p class="danger-note">当前演示文件仍是4小时，请退回修改。这里的提示是样例数字校验，不是模型审查。</p>';
      } else taskAction += `<p>陈工不能自己验收这次提交。请切换到另一位审查人。</p>${button("请审查人复核 →", 'data-switch="reviewer" data-target="tasks"')}`;
    } else {
      taskAction = `<div class="explanation neutral" style="margin:0 0 18px">这次整改已经由林悦验收，原来的4小时和修改后的2小时都有记录。</div>${button("继续核对剩余要求 →", 'data-switch="reviewer" data-target="report"')}`;
    }
    content = `<div class="task-layout"><section class="panel"><div class="panel-heading"><h2>修正响应时限承诺</h2>${chip(labels[currentTask.effective_status], currentTask.effective_status === "ACCEPTED" ? "green" : "amber")}</div>
      <div class="task-body"><h3>登记时的问题</h3><p>${escapeHtml(model.issue.description)}</p><div class="task-facts"><div><small>整改负责人</small>陈工 · 编写人</div><div><small>复核人</small>林悦 · 审查人</div><div><small>原来写了什么</small>${quote(model.issue.evidence[0].quote)}</div><div><small>需要达到什么</small>接报后 2 小时内响应</div></div></div>
      <div class="detail-title" style="padding-top:0"><h3>现在这份正式文件怎么写</h3>${chip(`响应书 · 第${row.response.revision_no}稿`)}</div>${sources(row)}<div class="task-body" style="padding-top:0">${taskAction}</div></section>${historyPanel()}</div>`;
  }
  return `${pageTitle("问题与整改", "一条问题，一个负责人；改完之后，再由另一人检查。")}${guide()}${steps()}${content}`;
}

function materialsView() {
  const tender = model.requirements[0].tender;
  const current = model.requirements[0].response;
  return `${pageTitle("材料与版本", "这里能回答：这次到底检查的是哪一份文件？")}
    <section class="guide"><div class="guide-icon">▤</div><div><h3>招标文件是对方的要求，响应书是我们的承诺</h3><p>每次改动都保存新文件。旧稿不覆盖，问题和复核记录仍能找回当时的原文。</p></div></section>
    <section class="panel"><div class="panel-heading"><h2>本轮采用的材料</h2>${chip("2 份文件", "green")}</div><div class="materials-list">
      ${[{source:tender, name:"采购方提出要求的文件", tag:"要求依据"}, {source:current,name:"我们准备提交的服务承诺",tag:"本轮正式响应"}].map(({source, name, tag}) =>
      `<div class="file-row"><div class="file-tile">PDF</div><div><h3>${escapeHtml(source.filename)} ${chip(tag, "green")}</h3><p>${name} · 共3页 · 第${source.revision_no}稿</p></div>${button("打开原文 ↗", `data-source="${source.revision_id}"`, "small")}</div>`).join("")}</div></section>
    <section class="panel" style="margin-top:22px"><div class="panel-heading"><h2>技术响应书的修改历史</h2><small>${model.files.length} 个文件版本</small></div><div class="materials-list">
      ${[...model.files].reverse().map((file) => `<div class="file-row"><div class="file-tile">V${file.version}</div><div><h3>技术响应书 · 第${file.version}稿 ${file.revision_id === current.revision_id ? chip("本轮采用", "green") : chip("历史文件")}</h3><p>${file.version === 1 ? "最初的响应书，承诺4小时内响应。" : file.version === 2 ? "整改保存的版本，可回看修改后的实际文字。" : "后续校对版本，仍需针对本轮文件确认。"}</p></div>${button("查看这份原文", `data-source="${file.revision_id}"`, "small")}</div>`).join("")}</div></section>
    <p class="below-note">样例文件均明确标记“人工构造”。文件来自实际PDF解析，页码与原文可追溯。</p>`;
}

function reportView() {
  const count = model.report.reviewed_count;
  const eligible = model.requirements.filter((row, index) => row.report.status !== "REVIEWED" && !(index === 0 && model.report.unresolved_issue_count));
  const unresolvedFirst = model.requirements[0].report.status !== "REVIEWED" && model.report.unresolved_issue_count > 0;
  return `${pageTitle("检查报告", "每一项都要明确检查过；没有问题记录，不等于已经审查完成。")}${guide()}
    <section class="panel"><div class="report-summary"><div class="report-ring" style="--progress:${count / 3 * 360}deg"><strong>${count}/3</strong></div><div><h2>${complete() ? "本轮人工检查已完成" : isStale() ? "文件更新后，需要重新确认" : "本轮尚未完成"}</h2><p>${complete() ? "3项要求都已明确确认，响应时限问题已由另一人复核。" : `${count}项已针对当前文件确认，${3-count}项仍待处理或核对。`}</p></div></div>
      <div class="report-scroll"><table class="report-table"><thead><tr><th>已阅读并核对</th><th>检查要求</th><th>当前响应</th><th>本轮状态</th></tr></thead><tbody>
      ${model.requirements.map((row, index) => {
        const canConfirm = row.report.status !== "REVIEWED" && !(index === 0 && unresolvedFirst);
        return `<tr><td>${row.report.status === "REVIEWED" ? '<span style="color:var(--teal)">✓ 已确认</span>' : canConfirm && actor === "reviewer" ? `<input type="checkbox" data-check="${row.id}" aria-label="已阅读并核对${row.title}" ${confirmations.has(row.id) ? "checked" : ""}>` : `<span class="muted">${canConfirm ? "由审查人确认" : "先完成整改"}</span>`}</td><td><strong>${row.title}</strong><small>${row.target}</small></td><td>${quote(row.response.quote)}<small><button type="button" class="text-button" data-source="${row.response.revision_id}" data-block="${row.response.block_id}">响应书第${row.response.page}页 · 第${row.response.revision_no}稿 ↗</button></small></td><td>${rowStatus(row, index)}</td></tr>`;
      }).join("")}</tbody></table></div>
      <div class="report-footer"><p>${complete() ? "这是人工工作记录，不是AI自动生成的合规保证。" : "先点原文核对，再勾选已经看过的条目并确认。"}</p><div>${complete() ? '<a class="button primary" href="/demo/api/report">下载本轮检查记录 ↓</a>' : actor !== "reviewer" ? button("切到审查人确认", 'data-switch="reviewer" data-target="report"') : eligible.length ? `<button type="button" id="confirm-selected" class="button primary" ${confirmations.size && !busy ? "" : "disabled"}>确认勾选项满足要求 ✓</button>` : button("先处理整改任务 →", 'data-nav="tasks"')}</div></div></section>
      ${complete() ? `<section class="done-banner"><h3>再体验一个真实工作中的小变化</h3><p>如果同事又发来一稿文件，即使只是排版校对，也需要知道旧结论是否还适用。点一下，看看系统怎样提示。</p>${button("模拟：响应文件又更新了一稿 →", 'data-new-version="true"', "subtle")}</section>` : ""}
      <p class="below-note">本例差异由演示预设，最终满足由你明确确认。RAG/Agent 自动发现问题尚未接入。</p>`;
}

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
