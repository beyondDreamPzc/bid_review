"use strict";
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
