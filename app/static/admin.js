const AUTH_KEY = "campusharbor.auth";

const state = {
  profile: null,
  modelName: "mock",
  dashboard: {
    reports: [],
    cases: [],
    excel: [],
    alerts: []
  }
};

const els = {
  serviceState: document.querySelector("#serviceState"),
  modelState: document.querySelector("#modelState"),
  activeAccount: document.querySelector("#activeAccount"),
  switchAccount: document.querySelector("#switchAccount"),
  refreshAdmin: document.querySelector("#refreshAdmin"),
  metricReports: document.querySelector("#metricReports"),
  metricHigh: document.querySelector("#metricHigh"),
  metricCases: document.querySelector("#metricCases"),
  metricExcel: document.querySelector("#metricExcel"),
  metricAlerts: document.querySelector("#metricAlerts"),
  metricHighMeta: document.querySelector("#metricHighMeta"),
  metricCasesMeta: document.querySelector("#metricCasesMeta"),
  metricExcelMeta: document.querySelector("#metricExcelMeta"),
  metricAlertsMeta: document.querySelector("#metricAlertsMeta"),
  lastUpdated: document.querySelector("#lastUpdated"),
  trendTotal: document.querySelector("#trendTotal"),
  activityTrend: document.querySelector("#activityTrend"),
  riskDistribution: document.querySelector("#riskDistribution"),
  emotionDistribution: document.querySelector("#emotionDistribution"),
  intentDistribution: document.querySelector("#intentDistribution"),
  toolDistribution: document.querySelector("#toolDistribution"),
  casesCount: document.querySelector("#casesCount"),
  reportsCount: document.querySelector("#reportsCount"),
  excelCount: document.querySelector("#excelCount"),
  alertCount: document.querySelector("#alertCount"),
  cases: document.querySelector("#cases"),
  reports: document.querySelector("#reports"),
  excelRecords: document.querySelector("#excelRecords"),
  alertRecords: document.querySelector("#alertRecords"),
  adminGatePanel: document.querySelector("#adminGatePanel"),
  rosterPanel: document.querySelector("#rosterPanel"),
  advisorPanel: document.querySelector("#advisorPanel"),
  rosterImportForm: document.querySelector("#rosterImportForm"),
  rosterFile: document.querySelector("#rosterFile"),
  downloadRosterTemplate: document.querySelector("#downloadRosterTemplate"),
  downloadStaffTemplate: document.querySelector("#downloadStaffTemplate"),
  accessState: document.querySelector("#accessState"),
  advisorAlerts: document.querySelector("#advisorAlerts"),
  conversationState: document.querySelector("#conversationState"),
  conversationDetail: document.querySelector("#conversationDetail"),
  classCreateForm: document.querySelector("#classCreateForm"),
  className: document.querySelector("#className"),
  classCollege: document.querySelector("#classCollege"),
  adminClasses: document.querySelector("#adminClasses"),
  classApplications: document.querySelector("#classApplications"),
  orgScope: document.querySelector("#orgScope"),
  orgState: document.querySelector("#orgState"),
  studentSearch: document.querySelector("#studentSearch"),
  searchStudents: document.querySelector("#searchStudents"),
  studentSearchResults: document.querySelector("#studentSearchResults")
};

function readAuth() {
  try {
    return JSON.parse(sessionStorage.getItem(AUTH_KEY) || "null");
  } catch {
    return null;
  }
}

function clearAuth() {
  sessionStorage.removeItem(AUTH_KEY);
}

function authHeader() {
  const auth = readAuth();
  if (!auth?.token) {
    window.location.replace("/");
    return "";
  }
  return `Basic ${auth.token}`;
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), Authorization: authHeader() };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const body = await response.text();
    let message = body;
    try { message = JSON.parse(body).detail || body; } catch {}
    throw new Error(typeof message === "string" ? message : "请求参数不正确");
  }
  return response;
}

function setPill(el, text, tone = "ok") {
  el.textContent = text;
  el.className = `pill ${tone}`;
}

function isAdmin(profile) {
  return profile.roles?.some((role) => role.authority === "ROLE_ADMIN");
}

function displayModel(model) {
  return (model || "").includes("qwen2.5-7b-ft") ? "微调 Qwen2.5-7B" : model;
}

function parseServerTime(value) {
  if (!value) return null;
  // The database stores UTC. FastAPI serializes legacy naive datetimes without
  // a timezone suffix, so make the UTC meaning explicit before parsing.
  const normalized = typeof value === "string"
    && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value)
    && !/(Z|[+-]\d{2}:?\d{2})$/i.test(value)
    ? `${value.replace(" ", "T")}Z`
    : value;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function displayTime(value) {
  const date = parseServerTime(value);
  return date ? new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(date) : "";
}

function formatShortDate(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric"
  }).format(value);
}

function percentage(value, total) {
  return total ? Math.round((value / total) * 100) : 0;
}

function statusLabel(status) {
  const labels = {
    SUCCESS: "成功",
    FAILED: "失败",
    OPEN: "待跟进",
    ALERT_SENT: "已预警",
    ACKNOWLEDGED: "跟进中",
    REFERRED: "已转介",
    CLOSED: "已关闭"
  };
  return labels[(status || "").toUpperCase()] || status || "未知";
}

function roleLabel(role) {
  const value = (role || "").toUpperCase();
  if (value === "USER") return "学生";
  if (value === "ASSISTANT") return "CampusHarbor";
  if (value === "SYSTEM") return "系统";
  return role || "未知角色";
}

async function checkHealth() {
  try {
    const response = await fetch("/actuator/health");
    const body = await response.json();
    setPill(els.serviceState, body.status === "UP" ? "服务正常" : `服务 ${body.status}`, body.status === "UP" ? "ok" : "danger");
  } catch {
    setPill(els.serviceState, "服务 DOWN", "danger");
  }
}

async function loadProfile() {
  try {
    const response = await api("/api/profile");
    const profile = await response.json();
    if (!isAdmin(profile)) {
      window.location.replace("/student.html");
      return null;
    }
    state.profile = profile;
    els.activeAccount.textContent = profile.displayName || profile.username;
    configureRoleView(profile);
    return profile;
  } catch {
    clearAuth();
    window.location.replace("/");
    return null;
  }
}

function configureRoleView(profile) {
  const roleLabels = { SYSTEM_ADMIN: "系统管理员", COUNSELOR: "心理中心老师", ADVISOR: "辅导员", DEMO_ADMIN: "全权限演示管理员" };
  document.querySelector("#accountBadge span").textContent = roleLabels[profile.adminRole] || "待认证管理员";
  const pending = profile.adminVerificationStatus !== "VERIFIED";
  els.adminGatePanel.classList.toggle("hidden", !pending);
  els.adminGatePanel.textContent = pending
    ? "账号尚未匹配学校导入的教职工名单，请核对姓名、工号和登录账号。系统不再接受人工权限审批。"
    : "";
  const demo = profile.adminRole === "DEMO_ADMIN";
  const system = profile.adminRole === "SYSTEM_ADMIN" || demo;
  const counselor = profile.adminRole === "COUNSELOR" || demo;
  const advisor = profile.adminRole === "ADVISOR" || demo;
  document.querySelectorAll(".counselor-only").forEach(el => el.classList.toggle("hidden", pending || !counselor));
  document.querySelectorAll(".system-only, .organization-only").forEach(el => el.classList.toggle("hidden", pending || !system));
  els.rosterPanel.classList.toggle("hidden", pending || !(system || profile.adminRole === "ADVISOR"));
  els.advisorPanel.classList.toggle("hidden", pending || !advisor);
}

async function loadAgentStatus() {
  const response = await api("/api/agent/status");
  const status = await response.json();
  state.modelName = status.model || "mock";
  if (status.realModelEnabled) {
    setPill(els.modelState, `${status.provider} / ${displayModel(state.modelName)}`, "ok");
  } else {
    setPill(els.modelState, "mock 演示", "warn");
  }
}

async function loadAdminDashboard() {
  els.refreshAdmin.disabled = true;
  els.refreshAdmin.textContent = "刷新中";
  try {
    const [reportsRes, casesRes, excelRes, alertsRes, statisticsRes] = await Promise.all([
      api("/api/admin/reports"),
      api("/api/admin/cases"),
      api("/api/admin/excel-records"),
      api("/api/admin/alerts"),
      api("/api/admin/risk-statistics")
    ]);
    const reports = await reportsRes.json();
    const cases = await casesRes.json();
    const excel = await excelRes.json();
    const alerts = await alertsRes.json();
    const statistics = await statisticsRes.json();
    state.dashboard = { reports, cases, excel, alerts };

    const reportTotal = Object.values(statistics.totals).reduce((sum, value) => sum + value, 0);
    const highRisk = statistics.totals.HIGH || 0;
    const openCases = cases.filter((item) => ["OPEN", "ALERT_SENT"].includes(item.status)).length;
    const excelSuccess = excel.filter((item) => item.status === "SUCCESS").length;
    const alertSuccess = alerts.filter((item) => item.status === "SUCCESS").length;

    els.metricReports.textContent = reportTotal;
    els.metricHigh.textContent = highRisk;
    els.metricCases.textContent = cases.length;
    els.metricExcel.textContent = excel.length;
    els.metricAlerts.textContent = alerts.length;
    els.metricHighMeta.textContent = `占比 ${percentage(highRisk, reportTotal)}%`;
    els.metricCasesMeta.textContent = `待跟进 ${openCases}`;
    els.metricExcelMeta.textContent = `成功 ${excelSuccess}`;
    els.metricAlertsMeta.textContent = `发送成功 ${alertSuccess}`;
    els.lastUpdated.textContent = `更新于 ${new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).format(new Date())}`;
    els.casesCount.textContent = `${cases.length} 个个案`;
    els.reportsCount.textContent = `${reports.length} 条报告`;
    els.excelCount.textContent = `${excel.length} 条`;
    els.alertCount.textContent = `${alerts.length} 条`;

    renderTrend(reports);
    renderAnalytics(reports, excel, alerts, statistics.totals);
    renderCases(cases);
    renderReports(reports);
    renderToolRecords(els.excelRecords, excel, "excel");
    renderToolRecords(els.alertRecords, alerts, "alert");
  } catch (error) {
    els.lastUpdated.textContent = `刷新失败：${error.message}`;
  } finally {
    els.refreshAdmin.disabled = false;
    els.refreshAdmin.textContent = "刷新数据";
  }
}

function localDateKey(value) {
  const date = value instanceof Date ? value : parseServerTime(value);
  if (!date) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(date);
  const get = (type) => parts.find((part) => part.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function renderTrend(reports) {
  const days = [];
  const today = new Date();
  for (let offset = 6; offset >= 0; offset -= 1) {
    const date = new Date(today.getTime() - offset * 24 * 60 * 60 * 1000);
    days.push({
      date,
      key: localDateKey(date),
      count: 0
    });
  }
  const dayMap = new Map(days.map((item) => [item.key, item]));
  for (const report of reports) {
    const day = dayMap.get(localDateKey(report.createdAt));
    if (day) day.count += 1;
  }
  const max = Math.max(1, ...days.map((item) => item.count));
  const total = days.reduce((sum, item) => sum + item.count, 0);
  els.trendTotal.textContent = `共 ${total} 条`;
  els.activityTrend.innerHTML = "";

  for (const item of days) {
    const column = document.createElement("div");
    column.className = "trend-column";
    column.title = `${formatShortDate(item.date)}：${item.count} 条报告`;

    const value = document.createElement("strong");
    value.textContent = item.count;
    const track = document.createElement("div");
    track.className = "trend-track";
    const bar = document.createElement("span");
    bar.style.height = `${item.count ? Math.max(12, (item.count / max) * 100) : 4}%`;
    track.append(bar);
    const label = document.createElement("small");
    label.textContent = formatShortDate(item.date);

    column.append(value, track, label);
    els.activityTrend.append(column);
  }
}

function countBy(items, key) {
  return items.reduce((result, item) => {
    const value = String(item[key] || "UNKNOWN").toUpperCase();
    result[value] = (result[value] || 0) + 1;
    return result;
  }, {});
}

function renderDistribution(container, definitions, counts) {
  container.innerHTML = "";
  const total = definitions.reduce((sum, item) => sum + (counts[item.key] || 0), 0);
  for (const item of definitions) {
    const count = counts[item.key] || 0;
    const row = document.createElement("div");
    row.className = "distribution-row";

    const label = document.createElement("span");
    label.textContent = item.label;
    const track = document.createElement("div");
    track.className = "distribution-track";
    const fill = document.createElement("span");
    fill.className = `distribution-fill tone-${item.tone}`;
    fill.style.width = `${percentage(count, total)}%`;
    track.append(fill);
    const value = document.createElement("strong");
    value.textContent = count;

    row.append(label, track, value);
    container.append(row);
  }
}

function renderAnalytics(reports, excel, alerts, riskTotals = null) {
  renderDistribution(els.riskDistribution, [
    { key: "LOW", label: "低风险", tone: "teal" },
    { key: "MEDIUM", label: "中风险", tone: "amber" },
    { key: "HIGH", label: "高风险", tone: "red" }
  ], riskTotals || countBy(reports, "riskLevel"));

  renderDistribution(els.emotionDistribution, [
    { key: "NORMAL", label: "平稳", tone: "teal" },
    { key: "ANXIETY", label: "焦虑", tone: "amber" },
    { key: "DEPRESSED", label: "低落", tone: "orange" },
    { key: "HIGH_RISK", label: "高风险", tone: "red" }
  ], countBy(reports, "emotion"));

  renderDistribution(els.intentDistribution, [
    { key: "CHAT", label: "日常交流", tone: "blue" },
    { key: "CONSULT", label: "心理咨询", tone: "amber" },
    { key: "RISK", label: "风险干预", tone: "red" }
  ], countBy(reports, "intent"));

  const toolCounts = {
    EXCEL_SUCCESS: excel.filter((item) => item.status === "SUCCESS").length,
    EXCEL_FAILED: excel.filter((item) => item.status === "FAILED").length,
    ALERT_SUCCESS: alerts.filter((item) => item.status === "SUCCESS").length,
    ALERT_FAILED: alerts.filter((item) => item.status === "FAILED").length
  };
  renderDistribution(els.toolDistribution, [
    { key: "EXCEL_SUCCESS", label: "台账成功", tone: "teal" },
    { key: "EXCEL_FAILED", label: "台账失败", tone: "red" },
    { key: "ALERT_SUCCESS", label: "预警成功", tone: "blue" },
    { key: "ALERT_FAILED", label: "预警失败", tone: "red" }
  ], toolCounts);
}

function renderToolRecords(container, records, kind) {
  container.innerHTML = "";
  if (!records.length) {
    const empty = document.createElement("div");
    empty.className = "delivery-empty";
    empty.textContent = kind === "excel" ? "暂无 Excel 写入记录" : "暂无预警发送记录";
    container.append(empty);
    return;
  }
  for (const item of records.slice(0, 4)) {
    const card = document.createElement("article");
    card.className = "delivery-record";

    const head = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `报告 #${item.reportId}`;
    const badge = document.createElement("span");
    badge.className = `status-badge status-${String(item.status || "").toLowerCase()}`;
    badge.textContent = statusLabel(item.status);
    head.append(title, badge);

    const meta = document.createElement("small");
    meta.textContent = kind === "excel"
      ? `${displayTime(item.createdAt)}${item.filePath ? ` · ${item.filePath}` : ""}`
      : `${item.channel || "通知"} · ${item.recipient || "未配置接收人"} · ${displayTime(item.createdAt)}`;
    const message = document.createElement("p");
    message.textContent = item.message || "无附加信息";
    card.append(head, meta, message);
    container.append(card);
  }
}

function renderCases(cases) {
  clearCaseIdentities();
  els.cases.innerHTML = "";
  if (!cases.length) {
    els.cases.innerHTML = `<div class="empty small"><strong>暂无高风险个案</strong><p>只有 HIGH 高风险报告会自动进入人工处置闭环；中低风险仅参与匿名统计。</p></div>`;
    return;
  }
  for (const item of cases) {
    const card = document.createElement("article");
    card.className = `case-card risk-${item.riskLevel.toLowerCase()}`;

    const head = document.createElement("div");
    head.className = "case-head";
    const titleLine = document.createElement("div");
    titleLine.className = "record-title-line";
    const title = document.createElement("strong");
    title.textContent = `个案 #${item.id}`;
    const badge = document.createElement("span");
    badge.className = `status-badge case-status-${String(item.status || "").toLowerCase()}`;
    badge.textContent = statusLabel(item.status);
    titleLine.append(title, badge);
    const time = document.createElement("span");
    time.textContent = displayTime(item.updatedAt);
    head.append(titleLine, time);

    const meta = document.createElement("small");
    meta.textContent = `报告 #${item.reportId} · ${item.riskLevel} · 负责人：${item.owner || "未分配"}`;
    const summary = document.createElement("p");
    summary.textContent = item.summary || "";
    const handoff = document.createElement("pre");
    handoff.textContent = item.handoffSummary || "";

    const actions = document.createElement("div");
    actions.className = "case-actions";
    const canAcknowledge = item.canClaim;
    const isActive = ["ACKNOWLEDGED", "REFERRED"].includes(item.status);
    if (canAcknowledge) {
      actions.append(caseButton(isActive ? "确认接手旧个案" : "接手个案", "primary", () => acknowledgeCase(item.id)));
    }
    if (isActive && item.canHandle) {
      actions.append(caseButton("添加跟进", "", () => addCaseNote(item.id)));
      if (item.status === "ACKNOWLEDGED") {
        actions.append(caseButton("转介", "", () => updateCaseStatus(item.id, "REFERRED")));
      }
      actions.append(caseButton("关闭", "danger", () => updateCaseStatus(item.id, "CLOSED")));
    }
    const notes = document.createElement("div");
    notes.className = "case-notes";
    const identity = document.createElement("div");
    identity.className = "case-identity hidden";
    const consent = document.createElement("p");
    consent.className = "case-privacy-hint";
    if (isActive && item.canHandle) {
      consent.textContent = "高风险个案接手人可直接查看必要处置身份；必须填写原因，每次访问均写入审计。咨询原文不开放。";
      actions.prepend(caseButton("查看处置身份", "", () => openCaseIdentity(item, identity)));
    } else if (isActive && !item.canClaim) {
      consent.textContent = "已由其他管理员接手；你只能查看匿名状态，不能查看身份或跟进详情。";
    } else if (isActive && item.canClaim) {
      consent.textContent = "旧个案尚未绑定接手账号，请先确认接手。姓名不会作为权限凭据。";
    }
    if (item.canHandle) {
      const notesButton = caseButton("查看跟进记录", "link", () => toggleCaseNotes(item.id, notes, notesButton));
      actions.append(notesButton);
    }
    const audit = document.createElement("div");
    audit.className = "case-notes";
    if (item.canHandle) {
      const auditButton = caseButton("身份访问记录", "link", () => toggleIdentityAudits(item.id, audit, auditButton));
      actions.append(auditButton);
    }

    card.append(head, meta, summary, handoff, consent, actions, identity, notes, audit);
    els.cases.append(card);
  }
}

const identityClosers = new Set();

function clearCaseIdentities() {
  for (const close of [...identityClosers]) close();
}

function openCaseIdentity(item, panel) {
  clearCaseIdentities();
  let timer;
  const close = () => {
    if (timer) window.clearTimeout(timer);
    panel.replaceChildren();
    panel.classList.add("hidden");
    identityClosers.delete(close);
  };
  identityClosers.add(close);
  panel.classList.remove("hidden");
  const form = document.createElement("form");
  form.className = "case-identity-form";
  const title = document.createElement("strong");
  title.textContent = "查看必要处置身份";
  const label = document.createElement("label");
  label.textContent = "查看原因（将写入审计记录，请勿粘贴咨询原文）";
  const reason = document.createElement("textarea");
  reason.required = true;
  reason.maxLength = 1000;
  reason.rows = 2;
  reason.placeholder = "例如：为安排安全联系，核对学校通讯录中的学生";
  label.append(reason);
  const confirmation = document.createElement("input");
  confirmation.type = "checkbox";
  confirmation.required = item.riskLevel === "HIGH";
  const confirmationLabel = document.createElement("label");
  confirmationLabel.className = "identity-confirmation";
  confirmationLabel.append(confirmation, document.createTextNode("我确认仅为高风险安全联系和人工处置查看身份"));
  const hint = document.createElement("p");
  hint.className = "case-privacy-hint";
  hint.textContent = "只展示姓名、学号、UID 和所属班级；30 秒后自动隐藏，切换页面时清除。";
  const actions = document.createElement("div");
  actions.className = "case-actions";
  const submit = caseButton("确认查看", "primary", () => {});
  submit.type = "submit";
  actions.append(submit, caseButton("取消", "", close));
  const error = document.createElement("p");
  error.setAttribute("role", "status");
  form.append(title, label);
  if (item.riskLevel === "HIGH") form.append(confirmationLabel);
  form.append(hint, actions, error);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!reason.value.trim()) { error.textContent = "请填写具体查看原因"; return; }
    submit.disabled = true;
    error.textContent = "正在核验个案接手权限并写入访问审计…";
    try {
      const response = await api(`/api/admin/cases/${item.id}/identity`, {
        method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
        body: JSON.stringify({ reason: reason.value.trim(), emergencyConfirmed: confirmation.checked })
      });
      const identity = await response.json();
      // Ignore an in-flight response if the user has hidden or left this panel.
      if (!identityClosers.has(close) || !panel.isConnected || document.hidden) return;
      const details = document.createElement("dl");
      details.className = "case-identity-details";
      const fields = [
        ["姓名", identity.name], ["学号", identity.studentNumber], ["学生 UID", identity.studentUid],
        ["学校 / 学院", [identity.schoolName, identity.collegeName].filter(Boolean).join(" · ")],
        ["所属班级", identity.classes.join("、") || "暂无已加入班级"], ["查看依据", identity.basis]
      ];
      for (const [name, value] of fields) {
        const term = document.createElement("dt");
        term.textContent = name;
        const detail = document.createElement("dd");
        detail.textContent = value || "未填报";
        details.append(term, detail);
      }
      const notice = document.createElement("p");
      notice.className = "case-privacy-hint";
      notice.textContent = `${identity.identityStatus}。${identity.contactStatus}。身份信息将在 30 秒后隐藏。`;
      panel.replaceChildren(details, notice, caseButton("立即隐藏", "", close));
      timer = window.setTimeout(close, 30000);
    } catch (err) {
      error.textContent = `无法查看：${err.message}。请确认你是当前个案接手人。`;
      submit.disabled = false;
    }
  });
  panel.append(form);
  reason.focus();
}

function approvalCard(title, lines, actions = []) {
  const card = document.createElement("article");
  card.className = "approval-card";
  const heading = document.createElement("strong"); heading.textContent = title;
  card.append(heading);
  for (const line of lines) { const p = document.createElement("p"); p.textContent = line; card.append(p); }
  if (actions.length) { const row = document.createElement("div"); row.className = "case-actions"; row.append(...actions); card.append(row); }
  return card;
}

async function loadAdvisorAlerts() {
  const response = await api("/api/admin/advisor-alerts");
  const rows = await response.json();
  els.advisorAlerts.replaceChildren();
  for (const item of rows) els.advisorAlerts.append(approvalCard(`学生 ${item.studentUid} · ${item.riskLevel}`,
    [`个案 #${item.caseId} · ${statusLabel(item.status)}`, item.action]));
  if (!rows.length) els.advisorAlerts.textContent = "暂无责任学生危机通知";
}

async function toggleIdentityAudits(caseId, panel, button) {
  if (panel.dataset.open === "true") {
    panel.replaceChildren();
    panel.dataset.open = "false";
    button.textContent = "身份访问记录";
    return;
  }
  try {
    const response = await api(`/api/admin/cases/${caseId}/identity-audits`, { cache: "no-store" });
    const records = await response.json();
    panel.replaceChildren();
    if (!records.length) panel.textContent = "暂无身份访问记录";
    for (const record of records) {
      const row = document.createElement("p");
      row.textContent = `${displayTime(record.createdAt)} · ${record.administrator} · ${record.allowed ? "已查看" : "已拒绝"} · ${record.reason}`;
      panel.append(row);
    }
    panel.dataset.open = "true";
    button.textContent = "收起访问记录";
  } catch (error) { window.alert(`读取失败：${error.message}`); }
}

document.addEventListener("visibilitychange", () => { if (document.hidden) clearCaseIdentities(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape") clearCaseIdentities(); });
window.addEventListener("pagehide", clearCaseIdentities);

function caseButton(label, tone, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `case-action ${tone}`.trim();
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

async function caseMutation(path, body) {
  await api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  await loadAdminDashboard();
}

async function acknowledgeCase(caseId) {
  const note = window.prompt("填写接手说明（可留空）", "已确认接手，将尽快联系并评估后续安排。");
  if (note === null) return;
  try {
    await caseMutation(`/api/admin/cases/${caseId}/acknowledge`, { note });
  } catch (error) {
    window.alert(`接手失败：${error.message}`);
  }
}

async function addCaseNote(caseId) {
  const note = window.prompt("填写本次跟进记录。请只记录必要处置信息，不粘贴学生完整咨询内容。");
  if (!note?.trim()) return;
  try {
    await caseMutation(`/api/admin/cases/${caseId}/notes`, { note: note.trim() });
  } catch (error) {
    window.alert(`保存失败：${error.message}`);
  }
}

async function updateCaseStatus(caseId, status) {
  const action = status === "REFERRED" ? "转介" : "关闭";
  const note = window.prompt(`请填写${action}原因及后续安排（必填）`);
  if (!note?.trim()) return;
  if (status === "CLOSED" && !window.confirm("确认关闭该风险个案？跟进记录仍会保留。")) return;
  try {
    await caseMutation(`/api/admin/cases/${caseId}/status`, { status, note: note.trim() });
  } catch (error) {
    window.alert(`${action}失败：${error.message}`);
  }
}

async function toggleCaseNotes(caseId, container, button) {
  if (container.dataset.open === "true") {
    container.replaceChildren();
    container.dataset.open = "false";
    button.textContent = "查看跟进记录";
    return;
  }
  try {
    const response = await api(`/api/admin/cases/${caseId}/notes`);
    const notes = await response.json();
    container.replaceChildren();
    if (!notes.length) {
      container.textContent = "暂无跟进记录";
    } else {
      for (const item of notes) {
        const row = document.createElement("p");
        const actor = document.createElement("strong");
        actor.textContent = `${item.actor} · ${displayTime(item.createdAt)}`;
        const content = document.createElement("span");
        content.textContent = item.note;
        row.append(actor, content);
        container.append(row);
      }
    }
    container.dataset.open = "true";
    button.textContent = "收起跟进记录";
  } catch (error) {
    window.alert(`读取失败：${error.message}`);
  }
}

function renderReports(reports) {
  els.reports.innerHTML = "";
  if (!reports.length) {
    els.reports.innerHTML = `<div class="empty small"><strong>暂无报告</strong><p>学生咨询或风险场景会在这里沉淀记录。</p></div>`;
    return;
  }
  for (const item of reports) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `report risk-${item.riskLevel.toLowerCase()}`;
    card.dataset.sessionId = item.sessionId;

    const head = document.createElement("div");
    head.className = "report-head";
    const titleLine = document.createElement("div");
    titleLine.className = "record-title-line";
    const title = document.createElement("strong");
    title.textContent = item.displayName || item.username || "未知学生";
    const badge = document.createElement("span");
    badge.className = `risk-badge risk-${String(item.riskLevel || "low").toLowerCase()}`;
    badge.textContent = item.riskLevel || "LOW";
    titleLine.append(title, badge);
    const time = document.createElement("span");
    time.textContent = displayTime(item.createdAt);
    head.append(titleLine, time);

    const summary = document.createElement("p");
    summary.textContent = item.summary;
    const content = document.createElement("small");
    content.textContent = `${item.emotion || "NORMAL"} / ${item.intent || "CHAT"} · ${item.content}`;
    const action = document.createElement("span");
    action.className = "report-action";
    action.textContent = "原始咨询内容已按隐私策略隐藏";

    card.append(head, summary, content, action);
    els.reports.append(card);
  }
}

async function loadConversation(sessionId) {
  if (!sessionId) {
    els.conversationState.textContent = "该报告缺少会话 ID";
    return;
  }
  els.conversationState.textContent = "正在读取...";
  els.conversationDetail.innerHTML = `<div class="empty small"><strong>加载中</strong><p>正在读取历史消息。</p></div>`;
  for (const card of els.reports.querySelectorAll(".report")) {
    card.classList.toggle("active", card.dataset.sessionId === sessionId);
  }
  try {
    const response = await api(`/api/admin/conversations/${encodeURIComponent(sessionId)}`);
    const conversation = await response.json();
    renderConversation(conversation);
  } catch (error) {
    els.conversationState.textContent = "读取失败";
    els.conversationDetail.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "empty small";
    const title = document.createElement("strong");
    title.textContent = "无法查看档案";
    const detail = document.createElement("p");
    detail.textContent = error.message;
    empty.append(title, detail);
    els.conversationDetail.append(empty);
  }
}

function renderConversation(conversation) {
  const messages = conversation.messages || [];
  els.conversationState.textContent = `${conversation.title || conversation.sessionId} · ${messages.length} 条消息`;
  els.conversationDetail.innerHTML = "";
  if (!messages.length) {
    els.conversationDetail.innerHTML = `<div class="empty small"><strong>暂无消息</strong><p>这个会话还没有写入消息记录。</p></div>`;
    return;
  }
  for (const message of messages) {
    const role = (message.role || "").toLowerCase();
    const row = document.createElement("article");
    row.className = `conversation-message ${role}`;

    const meta = document.createElement("div");
    meta.className = "conversation-meta";
    const label = document.createElement("strong");
    label.textContent = roleLabel(message.role);
    const time = document.createElement("span");
    time.textContent = displayTime(message.createdAt);
    meta.append(label, time);

    const bubble = document.createElement("div");
    bubble.className = "conversation-bubble";
    bubble.textContent = message.content || "";

    row.append(meta, bubble);
    els.conversationDetail.append(row);
  }
}

function logout() {
  clearAuth();
  window.location.assign("/");
}

async function loadOrganization() {
  try {
    const profile = state.profile;
    els.orgScope.textContent = `${profile.adminScope === "SCHOOL" ? "校级管理员" : "院级管理员"} · UID ${profile.publicUid || "-"}`;
    const [classesRes, applicationsRes] = await Promise.all([api("/api/admin/classes"), api("/api/admin/class-applications")]);
    const classes = await classesRes.json(); const applications = await applicationsRes.json();
    els.adminClasses.innerHTML = classes.length ? classes.map(item => `<div class="delivery-record"><strong>${item.name}</strong><span>UID：${item.uid} · ${item.schoolName} / ${item.collegeName}</span></div>`).join("") : "<p class='hint'>暂无班级</p>";
    els.classApplications.innerHTML = applications.length ? applications.map(item => `<div class="delivery-record"><strong>${item.student.displayName} · ${item.student.uid}</strong><span>${item.class.name} · ${item.class.uid}</span><button class="ghost application-action" data-id="${item.id}" data-decision="APPROVED">通过</button><button class="ghost application-action" data-id="${item.id}" data-decision="REJECTED">拒绝</button></div>`).join("") : "<p class='hint'>暂无待审批申请</p>";
    document.querySelectorAll(".application-action").forEach(button => button.addEventListener("click", async () => { await api(`/api/admin/class-applications/${button.dataset.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: button.dataset.decision }) }); loadOrganization(); }));
  } catch (error) { els.orgState.textContent = `组织数据读取失败：${error.message}`; }
}

async function createClass(event) { event.preventDefault(); try { await api("/api/admin/classes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: els.className.value, collegeName: els.classCollege.value }) }); els.className.value = ""; els.orgState.textContent = "班级创建成功，UID 已生成"; loadOrganization(); } catch (error) { els.orgState.textContent = error.message; } }
async function searchStudents() { try { const response = await api(`/api/admin/students/search?query=${encodeURIComponent(els.studentSearch.value)}`); const rows = await response.json(); els.studentSearchResults.innerHTML = rows.map(item => `<div class="delivery-record"><strong>${item.displayName} · ${item.uid}</strong><span>${item.schoolName} / ${item.collegeName}</span></div>`).join("") || "<p class='hint'>未找到学生</p>"; } catch (error) { els.orgState.textContent = error.message; } }

async function importRoster(event) {
  event.preventDefault();
  const file = els.rosterFile.files?.[0];
  if (!file) return;
  const data = new FormData();
  data.append("file", file);
  els.accessState.textContent = "正在校验名单并自动归属...";
  try {
    const response = await api("/api/admin/roster/import", { method: "POST", body: data });
    const result = await response.json();
    const errors = result.errors?.length ? `\n${result.errors.length} 行失败；首条：第 ${result.errors[0].line} 行 ${result.errors[0].message}` : "";
    const students = result.created + result.updated;
    const staff = result.staffCreated + result.staffUpdated;
    const summary = [`导入成功：名册已录入 ${result.success}/${result.total} 条。`];
    if (students) {
      summary.push(`学生名册 ${students} 人：已注册并激活 ${result.activated} 人，待学生使用同一姓名和学号注册 ${Math.max(0, students - result.activated)} 人。`);
      summary.push(`已归属辅导员 ${result.assigned} 人，因学院暂无生效辅导员而待归属 ${result.pendingAdvisor || 0} 人。`);
    }
    if (staff) {
      summary.push(`教职工名册 ${staff} 人：已有账号并自动开通 ${result.staffActivated} 人，待本人使用手机号、同一姓名和工号注册 ${Math.max(0, staff - result.staffActivated)} 人。`);
    }
    els.accessState.textContent = summary.join("\n") + errors;
    els.rosterFile.value = "";
    if (["SYSTEM_ADMIN", "DEMO_ADMIN"].includes(state.profile?.adminRole)) loadOrganization();
  } catch (error) { els.accessState.textContent = `导入失败：${error.message}`; }
}

function downloadRosterTemplate() {
  const csv = "\uFEFF学号,姓名,学校,学院,班级\n20260001,张同学,演示大学,计算机学院,2026级软件工程1班\n";
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "CampusHarbor学生名单模板.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function downloadStaffTemplate() {
  const csv = "\uFEFF工号,姓名,手机号,学校,学院,身份\nFDY2026001,王老师,13800002001,演示大学,计算机学院,ADVISOR\n";
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "CampusHarbor辅导员名单模板.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function loadRoleData(profile) {
  if (!profile || profile.adminVerificationStatus !== "VERIFIED") return;
  if (["COUNSELOR", "DEMO_ADMIN"].includes(profile.adminRole)) loadAdminDashboard();
  if (["SYSTEM_ADMIN", "DEMO_ADMIN"].includes(profile.adminRole)) {
    loadOrganization();
  }
  if (["ADVISOR", "DEMO_ADMIN"].includes(profile.adminRole)) loadAdvisorAlerts();
}

els.switchAccount.addEventListener("click", logout);
els.refreshAdmin.addEventListener("click", () => loadRoleData(state.profile));
els.classCreateForm.addEventListener("submit", createClass);
els.searchStudents.addEventListener("click", searchStudents);
els.rosterImportForm.addEventListener("submit", importRoster);
els.downloadRosterTemplate.addEventListener("click", downloadRosterTemplate);
els.downloadStaffTemplate.addEventListener("click", downloadStaffTemplate);

checkHealth();
loadProfile().then((profile) => {
  if (!profile) return;
  loadAgentStatus();
  loadRoleData(profile);
});
