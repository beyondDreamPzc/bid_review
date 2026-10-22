"use strict";
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
