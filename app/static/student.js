const AUTH_KEY = "campusharbor.auth";

const state = {
  sessionId: null,
  sending: false,
  profile: null,
  contactLoading: false,
  contactReload: false
};

const els = {
  activeAccount: document.querySelector("#activeAccount"),
  switchAccount: document.querySelector("#switchAccount"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  newSession: document.querySelector("#newSession"),
  sessionBadge: document.querySelector("#sessionBadge"),
  studentGreeting: document.querySelector("#studentGreeting"),
  charCount: document.querySelector("#charCount"),
  classHubState: document.querySelector("#classHubState"),
  classSearchMode: document.querySelector("#classSearchMode"),
  classSearchInput: document.querySelector("#classSearchInput"),
  classSearchButton: document.querySelector("#classSearchButton"),
  classSearchResults: document.querySelector("#classSearchResults"),
  classPendingState: document.querySelector("#classPendingState"),
  classJoinedMode: document.querySelector("#classJoinedMode"),
  joinedClassName: document.querySelector("#joinedClassName"),
  joinedClassMeta: document.querySelector("#joinedClassMeta"),
  leaveClassButton: document.querySelector("#leaveClassButton"),
  historyToggle: document.querySelector("#historyToggle"),
  historyPopover: document.querySelector("#historyPopover"),
  historyList: document.querySelector("#historyList"),
  refreshHistory: document.querySelector("#refreshHistory"),
  identityGate: document.querySelector("#identityGate"),
  identityForm: document.querySelector("#identityForm"),
  identityRealName: document.querySelector("#identityRealName"),
  identityStudentNumber: document.querySelector("#identityStudentNumber"),
  identityState: document.querySelector("#identityState"),
  contactPanel: document.querySelector("#contactPanel"),
  contactRequests: document.querySelector("#contactRequests"),
  refreshContacts: document.querySelector("#refreshContacts")
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

function activeSessionKey() {
  const identity = state.profile?.publicUid || state.profile?.username || "student";
  return `campusharbor.activeSession.${identity}`;
}

function setActiveSession(sessionId) {
  state.sessionId = sessionId || null;
  if (sessionId) sessionStorage.setItem(activeSessionKey(), sessionId);
  else sessionStorage.removeItem(activeSessionKey());
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

function studentDisplayName(profile) {
  if (profile.displayName && profile.displayName !== "Demo Student") return profile.displayName;
  return "待实名";
}

function greetingForNow() {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

function updateCharCount() {
  els.charCount.textContent = `${els.messageInput.value.length} / 1000`;
}

async function loadProfile() {
  try {
    const response = await api("/api/profile");
    const profile = await response.json();
    if (isAdmin(profile)) {
      window.location.replace("/admin.html");
      return null;
    }
    state.profile = profile;
    const displayName = studentDisplayName(profile);
    els.activeAccount.textContent = displayName;
    els.studentGreeting.textContent = `${greetingForNow()}，${displayName}`;
    return profile;
  } catch {
    clearAuth();
    window.location.replace("/");
    return null;
  }
}

function clearWelcome() {
  const empty = els.messages.querySelector(".empty");
  if (empty) empty.remove();
}

function addMessage(role, content) {
  clearWelcome();
  const row = document.createElement("article");
  row.className = `message ${role}`;
  row.innerHTML = `
    <div class="message-role">${role === "user" ? "我" : "CampusHarbor"}</div>
    <div class="bubble"></div>
  `;
  const bubble = row.querySelector(".bubble");
  if (role === "assistant") renderMarkdown(bubble, content);
  else bubble.textContent = content;
  els.messages.append(row);
  els.messages.scrollTop = els.messages.scrollHeight;
  return row.querySelector(".bubble");
}

function startThinkingIndicator(assistantBubble) {
  const row = assistantBubble.closest(".message");
  const indicator = document.createElement("div");
  const startedAt = performance.now();
  indicator.className = "thinking-indicator";
  indicator.setAttribute("role", "status");
  indicator.setAttribute("aria-live", "polite");
  indicator.innerHTML = '<span class="thinking-pulse" aria-hidden="true"><i></i><i></i><i></i></span><span class="thinking-copy">正在思考 · 0 秒</span>';
  row.insertBefore(indicator, assistantBubble);
  assistantBubble.hidden = true;

  const copy = indicator.querySelector(".thinking-copy");
  const timer = window.setInterval(() => {
    const elapsedSeconds = Math.floor((performance.now() - startedAt) / 1000);
    copy.textContent = `正在思考 · ${elapsedSeconds} 秒`;
  }, 250);

  return () => {
    window.clearInterval(timer);
    indicator.remove();
  };
}

function parseSse(buffer, onEvent) {
  const parts = buffer.split("\n\n");
  const rest = parts.pop();
  for (const part of parts) {
    const dataLine = part.split("\n").find((line) => line.startsWith("data: "));
    if (!dataLine) continue;
    onEvent(JSON.parse(dataLine.slice(6)));
  }
  return rest;
}

async function sendMessage(event) {
  event.preventDefault();
  if (state.sending) return;
  const message = els.messageInput.value.trim();
  if (!message) return;
  state.sending = true;
  els.sendButton.disabled = true;
  setPill(els.sessionBadge, "THINKING", "warn");
  els.messageInput.value = "";
  updateCharCount();
  addMessage("user", message);
  const assistant = addMessage("assistant", "");
  const stopThinking = startThinkingIndicator(assistant);
  let thinkingStopped = false;
  const revealAssistant = () => {
    if (!thinkingStopped) {
      stopThinking();
      thinkingStopped = true;
    }
    assistant.hidden = false;
  };
  let raw = "";

  try {
    const response = await api("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: state.sessionId, message })
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let streamFailed = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = parseSse(buffer, (eventData) => {
        if (eventData.type === "meta") setActiveSession(eventData.sessionId);
        if (eventData.type === "token") {
          raw += eventData.content || "";
          revealAssistant();
          renderMarkdown(assistant, raw);
          els.messages.scrollTop = els.messages.scrollHeight;
        }
        if (eventData.type === "error") {
          streamFailed = true;
          if (!raw) {
            revealAssistant();
            assistant.textContent = eventData.message || "MCP 工具调用失败";
          }
          setPill(els.sessionBadge, "ERROR", "danger");
        }
      });
    }
    if (!thinkingStopped) stopThinking();
    if (!streamFailed) {
      setPill(els.sessionBadge, "DONE", "ok");
      await loadHistory();
      loadContactRequests();
    }
  } catch (error) {
    revealAssistant();
    assistant.textContent = `发送失败：${error.message}`;
    setPill(els.sessionBadge, "ERROR", "danger");
  } finally {
    if (!thinkingStopped) stopThinking();
    state.sending = false;
    els.sendButton.disabled = false;
  }
}

async function loadContactRequests() {
  if (!state.profile) return;
  if (state.contactLoading) { state.contactReload = true; return; }
  state.contactLoading = true;
  els.refreshContacts.disabled = true;
  try {
    const response = await api("/api/risk-contact-requests", { cache: "no-store" });
    const requests = await response.json();
    // Preserve an expanded access log until the request state actually changes.
    const snapshot = JSON.stringify(requests);
    if (els.contactRequests.dataset.snapshot === snapshot) return;
    els.contactRequests.dataset.snapshot = snapshot;
    els.contactRequests.replaceChildren();
    els.contactPanel.classList.toggle("hidden", !requests.length);
    for (const item of requests) {
      const card = document.createElement("article");
      card.className = "contact-request";
      const title = document.createElement("strong");
      title.textContent = `个案 #${item.caseId} · ${item.administrator}`;
      const organization = document.createElement("small");
      organization.textContent = item.organization;
      const status = document.createElement("p");
      status.textContent = item.status === "CLOSED" ? "个案已关闭，身份查看权限已停止。"
        : "高风险安全联系：接手该个案的心理中心老师可在说明原因并确认安全用途后查看必要身份；每次访问都会留痕，咨询原文不会共享。";
      const actions = document.createElement("div");
      actions.className = "case-actions";
      const audits = document.createElement("div");
      audits.className = "case-notes";
      const auditButton = contactButton("谁查看过我的身份", "", () => toggleContactAudits(item.caseId, audits, auditButton));
      actions.append(auditButton);
      card.append(title, organization, status, actions, audits);
      els.contactRequests.append(card);
    }
  } catch (error) {
    els.contactPanel.classList.remove("hidden");
    els.contactRequests.dataset.snapshot = "";
    els.contactRequests.textContent = `身份访问记录读取失败：${error.message}。请点击刷新重试。`;
  } finally {
    state.contactLoading = false;
    els.refreshContacts.disabled = false;
    if (state.contactReload) {
      state.contactReload = false;
      loadContactRequests();
    }
  }
}

function contactButton(text, tone, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `case-action ${tone}`.trim();
  button.textContent = text;
  button.addEventListener("click", handler);
  return button;
}

async function changeContactConsent(caseId, decision, actions) {
  const message = decision === "GRANTED"
    ? "同意把姓名、学号、UID 和所属班级提供给该个案的接手人，用于线下联系？咨询原文不会共享。"
    : decision === "REVOKED" ? "撤回后会阻止接手人再次查看身份，但不能收回其已经看到的信息。确认撤回？"
    : "拒绝后，接手人不能查看你的身份。确认拒绝这次联系？";
  if (!window.confirm(message)) return;
  actions.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    await api(`/api/risk-contact-requests/${caseId}/consent`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision })
    });
    // An ongoing refresh completes before the next poll; invalidate its snapshot.
    els.contactRequests.dataset.snapshot = "";
    await loadContactRequests();
  } catch (error) {
    window.alert(`操作失败：${error.message}`);
  } finally {
    actions.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

async function toggleContactAudits(caseId, panel, button) {
  if (panel.dataset.open === "true") {
    panel.replaceChildren();
    panel.dataset.open = "false";
    button.textContent = "谁查看过我的身份";
    return;
  }
  button.disabled = true;
  try {
    const response = await api(`/api/risk-contact-requests/${caseId}/identity-audits`, { cache: "no-store" });
    const records = await response.json();
    panel.replaceChildren();
    if (!records.length) panel.textContent = "还没有人查看过身份信息。";
    for (const record of records) {
      const row = document.createElement("p");
      row.textContent = `${formatHistoryTime(record.createdAt)} · ${record.administrator} · ${record.allowed ? "查看成功" : "系统拒绝了查看"} · 原因：${record.reason}`;
      panel.append(row);
    }
    panel.dataset.open = "true";
    button.textContent = "收起访问记录";
  } catch (error) { window.alert(`读取失败：${error.message}`); }
  finally { button.disabled = false; }
}

function resetSession() {
  setActiveSession(null);
  els.messages.innerHTML = `
    <div class="empty student-welcome">
      <span class="welcome-kicker">A FRESH START</span>
      <strong>新会话已经准备好</strong>
      <p>不用延续刚才的话题，你可以从此刻最想说的一件事重新开始。</p>
    </div>
  `;
  els.messageInput.value = "";
  updateCharCount();
  setPill(els.sessionBadge, "READY");
  renderHistoryActiveState();
}

function formatHistoryTime(value) {
  if (!value) return "";
  const normalized = typeof value === "string"
    && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value)
    && !/(Z|[+-]\d{2}:?\d{2})$/i.test(value)
    ? `${value.replace(" ", "T")}Z`
    : value;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function renderHistoryActiveState() {
  els.historyList.querySelectorAll(".history-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.sessionId === state.sessionId);
  });
}

function toggleHistory() {
  const expanded = els.historyToggle.getAttribute("aria-expanded") === "true";
  els.historyToggle.setAttribute("aria-expanded", String(!expanded));
  els.historyPopover.classList.toggle("hidden", expanded);
}

function closeHistoryOnOutsideClick(event) {
  if (els.historyPopover.classList.contains("hidden")) return;
  if (els.historyPopover.contains(event.target) || els.historyToggle.contains(event.target)) return;
  els.historyToggle.setAttribute("aria-expanded", "false");
  els.historyPopover.classList.add("hidden");
}

function showIdentityGate(profile) {
  if (profile.identityVerified) return;
  els.identityGate.classList.remove("hidden");
  els.identityRealName.value = profile.displayName === "Demo Student" ? "" : (profile.displayName || "");
  els.identityStudentNumber.value = profile.studentNumber || "";
  els.identityState.textContent = "系统将与学校导入名册核验；未录入时请联系学校管理员或辅导员。";
  window.setTimeout(() => els.identityRealName.focus(), 0);
}

async function submitIdentity(event) {
  event.preventDefault();
  els.identityState.textContent = "正在核验…";
  try {
    const response = await api("/api/profile/identity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        realName: els.identityRealName.value.trim(),
        studentNumber: els.identityStudentNumber.value.trim()
      })
    });
    state.profile = await response.json();
    const displayName = studentDisplayName(state.profile);
    els.activeAccount.textContent = displayName;
    els.studentGreeting.textContent = `${greetingForNow()}，${displayName}`;
    const auth = readAuth();
    if (auth) {
      sessionStorage.setItem(AUTH_KEY, JSON.stringify({ ...auth, displayName, studentNumber: state.profile.studentNumber }));
    }
    els.identityGate.classList.add("hidden");
  } catch (error) {
    els.identityState.textContent = `认证失败：${error.message}`;
  }
}

function renderHistory(rows) {
  els.historyList.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "还没有历史对话";
    els.historyList.append(empty);
    return;
  }
  for (const item of rows) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    button.dataset.sessionId = item.sessionId;
    const title = document.createElement("strong");
    title.textContent = item.title || "未命名对话";
    const meta = document.createElement("span");
    meta.textContent = `${item.messageCount} 条消息 · ${formatHistoryTime(item.updatedAt)}`;
    button.append(title, meta);
    button.addEventListener("click", () => loadConversation(item.sessionId));
    els.historyList.append(button);
  }
  renderHistoryActiveState();
}

async function loadHistory({ restoreActive = false } = {}) {
  try {
    const response = await api("/api/conversations?limit=30");
    const rows = await response.json();
    renderHistory(rows);
    if (restoreActive) {
      const stored = sessionStorage.getItem(activeSessionKey());
      if (stored && rows.some((item) => item.sessionId === stored)) await loadConversation(stored);
      else if (stored) setActiveSession(null);
    }
  } catch (error) {
    els.historyList.innerHTML = "";
    const message = document.createElement("p");
    message.className = "history-empty";
    message.textContent = `读取失败：${error.message}`;
    els.historyList.append(message);
  }
}

async function loadConversation(sessionId) {
  if (!sessionId || state.sending) return;
  setPill(els.sessionBadge, "LOADING", "warn");
  try {
    const response = await api(`/api/conversations/${encodeURIComponent(sessionId)}`);
    const conversation = await response.json();
    els.messages.replaceChildren();
    for (const message of conversation.messages || []) {
      addMessage(String(message.role).toLowerCase() === "user" ? "user" : "assistant", message.content);
    }
    if (!(conversation.messages || []).length) {
      els.messages.innerHTML = '<div class="empty student-welcome"><strong>这段对话还没有消息</strong></div>';
    }
    setActiveSession(conversation.sessionId);
    renderHistoryActiveState();
    setPill(els.sessionBadge, "CONTINUE", "ok");
    els.messageInput.focus();
  } catch (error) {
    setPill(els.sessionBadge, "ERROR", "danger");
    window.alert(`读取历史对话失败：${error.message}`);
  }
}

function logout() {
  clearAuth();
  window.location.assign("/");
}

async function loadMemberships() {
  try {
    const response = await api("/api/classes/mine");
    const rows = await response.json();
    const joined = rows.find((item) => item.status === "APPROVED");
    const pending = rows.find((item) => ["PENDING", "INVITED"].includes(item.status));
    els.classHubState.textContent = joined ? "已加入" : pending ? "申请处理中" : "未加入";
    els.classJoinedMode.classList.toggle("hidden", !joined);
    els.classSearchMode.classList.toggle("hidden", Boolean(joined));
    els.classPendingState.classList.toggle("hidden", !pending || Boolean(joined));
    if (joined) {
      els.joinedClassName.textContent = joined.class.name;
      els.joinedClassMeta.textContent = `${joined.class.collegeName} · ${joined.class.uid}`;
      els.leaveClassButton.dataset.uid = joined.class.uid;
      els.classSearchResults.classList.add("hidden");
      els.classSearchResults.replaceChildren();
    } else {
      els.classPendingState.textContent = pending
        ? `${pending.class.name} · ${pending.status === "PENDING" ? "等待管理员审批" : "管理员已邀请"}`
        : "";
    }
  } catch (error) {
    els.classHubState.textContent = "读取失败";
    els.classPendingState.textContent = error.message;
    els.classPendingState.classList.remove("hidden");
  }
}

function renderClassResults(rows) {
  els.classSearchResults.replaceChildren();
  els.classSearchResults.classList.remove("hidden");
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "class-search-empty";
    empty.textContent = "没有找到匹配班级";
    els.classSearchResults.append(empty);
    return;
  }
  for (const item of rows) {
    const result = document.createElement("div");
    result.className = "class-result";
    const info = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = item.name;
    const meta = document.createElement("span");
    meta.textContent = `${item.collegeName} · ${item.uid}`;
    info.append(name, meta);
    const apply = document.createElement("button");
    apply.className = "ghost";
    apply.type = "button";
    apply.textContent = "申请加入";
    apply.addEventListener("click", () => applyClass(item.uid, apply));
    result.append(info, apply);
    els.classSearchResults.append(result);
  }
}

async function searchClasses() {
  const query = els.classSearchInput.value.trim();
  if (query.length < 2) {
    renderClassResults([]);
    els.classSearchResults.querySelector("p").textContent = "请至少输入 2 个字符";
    return;
  }
  els.classSearchButton.disabled = true;
  try {
    const response = await api(`/api/classes/search?query=${encodeURIComponent(query)}`);
    renderClassResults(await response.json());
  } catch (error) {
    renderClassResults([]);
    els.classSearchResults.querySelector("p").textContent = error.message;
  } finally {
    els.classSearchButton.disabled = false;
  }
}

async function applyClass(uid, button) {
  button.disabled = true;
  try {
    await api("/api/classes/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ classUid: uid })
    });
    els.classSearchResults.classList.add("hidden");
    await loadMemberships();
  } catch (error) {
    button.disabled = false;
    els.classHubState.textContent = error.message;
  }
}

async function leaveClass() {
  const uid = els.leaveClassButton.dataset.uid;
  if (!uid || !window.confirm("确定退出当前班级吗？退出后需要重新申请才能加入。")) return;
  els.leaveClassButton.disabled = true;
  try {
    await api("/api/classes/leave", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ classUid: uid })
    });
    els.classSearchInput.value = "";
    await loadMemberships();
  } catch (error) {
    els.classHubState.textContent = error.message;
  } finally {
    els.leaveClassButton.disabled = false;
  }
}

document.querySelectorAll("[data-quick]").forEach((button) => {
  button.addEventListener("click", () => {
    els.messageInput.value = button.dataset.quick;
    updateCharCount();
    els.messageInput.focus();
  });
});
els.messageInput.addEventListener("input", updateCharCount);
els.chatForm.addEventListener("submit", sendMessage);
els.newSession.addEventListener("click", resetSession);
els.switchAccount.addEventListener("click", logout);
els.classSearchButton.addEventListener("click", searchClasses);
els.classSearchInput.addEventListener("keydown", (event) => { if (event.key === "Enter") searchClasses(); });
els.leaveClassButton.addEventListener("click", leaveClass);
els.historyToggle.addEventListener("click", toggleHistory);
els.refreshHistory.addEventListener("click", () => loadHistory());
document.addEventListener("click", closeHistoryOnOutsideClick);
els.identityForm.addEventListener("submit", submitIdentity);
els.refreshContacts.addEventListener("click", loadContactRequests);
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadContactRequests(); });
window.setInterval(() => { if (!document.hidden) loadContactRequests(); }, 30000);

loadProfile().then((profile) => {
  if (profile) {
    loadMemberships();
    loadContactRequests();
    loadHistory({ restoreActive: true });
    showIdentityGate(profile);
  }
});
updateCharCount();
