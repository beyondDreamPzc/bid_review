"use strict";
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
