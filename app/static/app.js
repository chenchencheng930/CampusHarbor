const AUTH_KEY = "campusharbor.auth";

const els = {
  serviceState: document.querySelector("#serviceState"),
  modelState: document.querySelector("#modelState"),
  loginForm: document.querySelector("#loginForm"),
  username: document.querySelector("#username"),
  password: document.querySelector("#password"),
  loginState: document.querySelector("#loginState"),
  showRegister: document.querySelector("#showRegister"),
  registerForm: document.querySelector("#registerForm"),
  registerType: document.querySelector("#registerType"),
  adminFields: document.querySelector("#adminFields"),
  registerNameLabel: document.querySelector("#registerNameLabel"),
  registerStudentNumberLabel: document.querySelector("#registerStudentNumberLabel"),
  registerState: document.querySelector("#registerState")
};

const roleEntries = [...document.querySelectorAll(".role-entry")];

function authHeader(token) {
  return `Basic ${token}`;
}

function isAdmin(profile) {
  return profile.roles?.some((role) => role.authority === "ROLE_ADMIN");
}

function setPill(el, text, tone = "ok") {
  if (!el) return;
  el.textContent = text;
  el.className = `pill ${tone}`;
}

async function api(path, token, options = {}) {
  const headers = { ...(options.headers || {}), Authorization: authHeader(token) };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return response;
}

function saveAuth(token, profile) {
  sessionStorage.setItem(AUTH_KEY, JSON.stringify({
    token,
    username: profile.username,
    displayName: profile.displayName,
    roles: profile.roles || []
  }));
}

function readAuth() {
  try {
    return JSON.parse(sessionStorage.getItem(AUTH_KEY) || "null");
  } catch {
    return null;
  }
}

function routeProfile(profile) {
  window.location.assign(isAdmin(profile) ? "/admin.html" : "/student.html");
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

async function resumeExistingLogin() {
  const auth = readAuth();
  if (!auth?.token) {
    setPill(els.modelState, "登录后读取", "warn");
    return;
  }
  try {
    const response = await api("/api/profile", auth.token);
    const profile = await response.json();
    saveAuth(auth.token, profile);
    routeProfile(profile);
  } catch {
    sessionStorage.removeItem(AUTH_KEY);
    setPill(els.modelState, "登录后读取", "warn");
  }
}

async function login(event) {
  event.preventDefault();
  const username = els.username.value.trim();
  const password = els.password.value;
  els.loginState.textContent = "正在登录...";
  try {
    const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) });
    if (!response.ok) {
      let detail = "登录失败";
      try { detail = (await response.json()).detail || detail; } catch {}
      throw new Error(detail);
    }
    const body = await response.json();
    saveAuth(body.token, body.profile);
    els.loginState.textContent = "登录成功，正在进入工作台";
    routeProfile(body.profile);
  } catch (error) {
    sessionStorage.removeItem(AUTH_KEY);
    els.loginState.textContent = `登录失败：${error.message}`;
  }
}

async function register(event) {
  event.preventDefault();
  const type = els.registerType.value;
  const body = {
    username: document.querySelector("#registerUsername").value.trim(),
    password: document.querySelector("#registerPassword").value,
    displayName: document.querySelector("#registerDisplayName").value.trim(),
    studentNumber: type === "student" ? document.querySelector("#registerStudentNumber").value.trim() : "",
    accountType: type,
    employeeNumber: type === "admin" ? document.querySelector("#registerEmployeeNumber").value.trim() : "",
    schoolName: "",
    collegeName: ""
  };
  const phone = body.username;
  if (!/^1[3-9]\d{9}$/.test(phone)) {
    els.registerState.textContent = "请输入有效的 11 位手机号";
    return;
  }
  els.registerState.textContent = "正在注册...";
  try {
    const response = await fetch("/api/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "注册失败");
    saveAuth(result.token, result.profile);
    els.registerState.textContent = result.message || "注册成功";
    routeProfile(result.profile);
  } catch (error) {
    els.registerState.textContent = error.message;
  }
}

function toggleRegistration() {
  els.registerForm.classList.toggle("hidden");
  els.loginForm.classList.toggle("hidden");
  els.showRegister.textContent = els.registerForm.classList.contains("hidden") ? "没有账号？注册新账号" : "返回登录";
}

function toggleAdminFields() {
  const admin = els.registerType.value === "admin";
  els.adminFields.classList.toggle("hidden", !admin);
  els.registerStudentNumberLabel.classList.toggle("hidden", admin);
  document.querySelector("#registerStudentNumber").required = !admin;
  document.querySelector("#registerEmployeeNumber").required = admin;
  els.registerNameLabel.querySelector("span").textContent = "真实姓名";
}

function selectRole(role) {
  const credentials = role === "admin"
    ? { username: "demo_admin", password: "demo12345", label: "全权限演示管理员端" }
    : { username: "student", password: "student123", label: "学生端" };
  els.username.value = credentials.username;
  els.password.value = credentials.password;
  els.loginState.textContent = `正在进入${credentials.label}...`;
  roleEntries.forEach((entry) => entry.classList.toggle("selected", entry.dataset.role === role));
  els.username.focus();
}

els.loginForm.addEventListener("submit", login);
els.registerForm.addEventListener("submit", register);
els.showRegister.addEventListener("click", toggleRegistration);
els.registerType.addEventListener("change", toggleAdminFields);
roleEntries.forEach((entry) => {
  entry.addEventListener("click", () => selectRole(entry.dataset.role));
  entry.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectRole(entry.dataset.role);
    }
  });
});
checkHealth();
toggleAdminFields();
resumeExistingLogin();
