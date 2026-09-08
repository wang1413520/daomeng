/* ===== 到梦空间 · 工作台前端逻辑 V2 ===== */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const TYPE_LABEL = { hit: "命中", signup: "报名", cycle: "轮次", mail: "邮件", state: "状态", error: "异常", log: "日志" };

let state = null;
let lastId = 0;
let paused = false;
const MAX_FEED = 500;

/* ---------- 工具 ---------- */
function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts.replace(" ", "T"));
  if (isNaN(d)) return ts;
  const p = (n) => String(n).padStart(2, "0");
  const hm = p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return hm;
  return (d.getMonth() + 1) + "-" + d.getDate() + " " + hm;
}
function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m > 0 ? m + "分" + String(s).padStart(2, "0") + "秒" : s + "秒";
}
let toastTimer = null;
function toast(msg, cls) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast " + (cls || "ok");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3600);
}

/* ---------- API ---------- */
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.json();
}
const post = (path, body) => api(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

/* ---------- 事件流渲染 ---------- */
function levelOf(ev) {
  if (ev.type === "cycle") return "cycle";
  if (ev.type === "mail") return "mail";
  if (ev.type === "error") return "error";
  if (ev.type === "hit") return "hit";
  if (ev.type === "signup") return ev.level || "info";
  if (ev.type === "state") return "state";
  return ev.level || "log";
}
function addFeedItem(ev) {
  if ($("page-overview").classList.contains("hidden")) return;
  const feed = $("feed");
  const item = document.createElement("div");
  const lv = levelOf(ev);
  item.className = "feed-item lv-" + lv + " tp-" + ev.type;
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = TYPE_LABEL[ev.type] || ev.type;
  const t = document.createElement("span");
  t.className = "ft";
  t.textContent = fmtTime(ev.ts);
  const m = document.createElement("span");
  m.className = "fm";
  let txt = ev.title || "";
  if (ev.type === "signup" && ev.detail && ev.detail.code && !txt.includes("code"))
    txt += (txt ? "  ·  " : "") + "code=" + ev.detail.code;
  m.textContent = txt;
  item.append(tag, t, m);
  feed.appendChild(item);
  while (feed.children.length > MAX_FEED) feed.removeChild(feed.firstChild);
  if (!paused) feed.scrollTop = feed.scrollHeight;
}
function clearView() {
  // 只清空可视区；lastId 保持不动，之后新事件照常追加，旧历史不重灌
  $("feed").innerHTML = "";
  feedCount = 0;
}

/* ---------- 记录页 ---------- */
function tagCls(type, level) {
  if (type === "signup") return level === "success" ? "tc-ok" : (level === "error" ? "tc-err" : "tc-warn");
  if (type === "hit") return "tc-info";
  if (type === "error") return "tc-err";
  if (type === "state") return "tc-info";
  return "tc-mut";
}
async function loadRecords() {
  try {
    const d = await api("/api/records");
    const tb = $("recTable").querySelector("tbody");
    tb.innerHTML = "";
    for (const ev of d.rows) {
      const tr = document.createElement("tr");
      const tdc = document.createElement("td");
      tdc.className = "mono";
      tdc.textContent = fmtTime(ev.ts);
      const tdt = document.createElement("td");
      const span = document.createElement("span");
      span.className = "tc " + tagCls(ev.type, ev.level);
      span.textContent = TYPE_LABEL[ev.type] || ev.type;
      tdt.appendChild(span);
      const tdm = document.createElement("td");
      tdm.textContent = ev.title || "";
      const tdr = document.createElement("td");
      let res = "—";
      if (ev.type === "signup" && ev.detail) {
        const dd = ev.detail;
        res = dd.ok ? "成功" : (dd.dry ? "试运行未提交" : (dd.terminal ? "不可报" : "失败"));
      }
      const rs = document.createElement("span");
      rs.className = "tc " + (res === "成功" ? "tc-ok" : res === "失败" ? "tc-err" : "tc-mut");
      rs.textContent = res;
      tdr.appendChild(rs);
      tr.append(tdc, tdt, tdm, tdr);
      tb.appendChild(tr);
    }
  } catch (e) { console.error(e); }
}

/* ---------- 活动档案页 ---------- */
async function loadArchive() {
  try {
    const d = await api("/api/archive");
    const tb = $("arcTable").querySelector("tbody");
    tb.innerHTML = "";
    for (const r of d.rows) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td");
      td1.className = "mono";
      td1.textContent = fmtTime(r.ts);
      const td2 = document.createElement("td");
      td2.textContent = r.name || ("（未知名） " + r.aid);
      const td3 = document.createElement("td");
      let status = "观察中", cls = "tc-mut";
      if (r.kind === "handled") {
        if (r.ok === 1) { status = "成功"; cls = "tc-ok"; }
        else if (r.code === "2000011" || (r.msg || "").includes("已报名过")) { status = "已报名过"; cls = "tc-ok"; }
        else if (r.attempts >= 3) { status = "放弃"; cls = "tc-err"; }
        else if ((r.msg || "").includes("dry")) { status = "试运行跳过"; cls = "tc-warn"; }
        else { status = "失败/重试中"; cls = "tc-warn"; }
      }
      const sp = document.createElement("span");
      sp.className = "tc " + cls;
      sp.textContent = status;
      td3.appendChild(sp);
      const td4 = document.createElement("td");
      td4.className = "mono";
      td4.textContent = r.code || "—";
      const td5 = document.createElement("td");
      td5.textContent = r.msg && r.msg !== "dry_run" ? r.msg : (r.kind === "seen" ? "符合规则才会处理；标题不含关键词的活动已按详情判定过" : "—");
      tr.append(td1, td2, td3, td4, td5);
      tb.appendChild(tr);
    }
  } catch (e) { console.error(e); }
}

/* ---------- 7日趋势折线图 ---------- */
let _trendDays = null;

async function loadTrend() {
  try {
    const d = await api("/api/trend?days=7");
    _trendDays = d.days;
    drawTrend($("trendChart"));
  } catch (e) { /* 后台图表不阻塞 */ }
}

function drawTrend(box) {
  if (!box) return;
  const days = _trendDays || [];
  const W = Math.max(360, box.clientWidth - 4), H = 190;
  const PL = 42, PR = 16, PT = 22, PB = 26;
  const iw = W - PL - PR, ih = H - PT - PB;
  const n = days.length;
  if (n === 0) { box.innerHTML = ""; return; }
  const xs = (i) => PL + (n === 1 ? iw / 2 : (i * iw) / (n - 1));
  const maxV = Math.max(1, ...days.map((d) => Math.max(d.signups || 0, d.success || 0)));
  const yv = (v) => PT + ih - (v / maxV) * ih;
  const pathOf = (key) => days.map((d, i) =>
    (i ? "L" : "M") + xs(i).toFixed(1) + "," + yv(d[key] || 0).toFixed(1)).join(" ");
  const area = pathOf("success") + " L" + xs(n - 1).toFixed(1) + "," + (PT + ih) +
    " L" + xs(0).toFixed(1) + "," + (PT + ih) + " Z";

  let grid = "", ymax = maxV;
  const steps = 4;
  for (let g = 0; g <= steps; g++) {
    const v = (maxV * g) / steps;
    const y = yv(v);
    grid += `<line x1="${PL}" y1="${y}" x2="${W - PR}" y2="${y}" stroke="rgba(255,255,255,.06)"/>` +
      `<text x="${PL - 8}" y="${y + 4}" text-anchor="end" class="tg">${Math.round(v)}</text>`;
  }
  const dotsS = days.map((d, i) =>
    `<circle cx="${xs(i).toFixed(1)}" cy="${yv(d.success || 0).toFixed(1)}" r="3.6" fill="var(--ok)">
       <title>${d.date} 成功 ${d.success || 0} / 尝试 ${d.signups || 0}</title></circle>` +
    `<text x="${xs(i).toFixed(1)}" y="${(yv(d.success || 0) - 9).toFixed(1)}" text-anchor="middle" class="tgv">${d.success || 0}</text>`
  ).join("");
  const dotsA = days.map((d, i) =>
    `<circle cx="${xs(i).toFixed(1)}" cy="${yv(d.signups || 0).toFixed(1)}" r="2.6" fill="var(--muted2)"><title>${d.date} 尝试 ${d.signups || 0}</title></circle>`
  ).join("");
  const xl = days.map((d, i) =>
    `<text x="${xs(i).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="tg">${d.date.slice(5)}</text>`
  ).join("");
  const allZero = days.every((d) => !(d.signups || 0) && !(d.success || 0));

  box.innerHTML =
    `<div class="trend-legend">
       <span class="lg-ok"><i></i>报名成功</span>
       <span class="lg-all"><i></i>报名事件（尝试）</span>
       ${allZero ? '<span class="trend-empty">近 7 日暂无报名记录</span>' : ""}
     </div>
     <svg width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg">
       <defs>
         <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
           <stop offset="0%" stop-color="var(--ok)" stop-opacity=".22"/>
           <stop offset="100%" stop-color="var(--ok)" stop-opacity="0"/>
         </linearGradient>
       </defs>
       ${grid}
       <path d="${area}" fill="url(#trendFill)"/>
       <path d="${pathOf("success")}" fill="none" stroke="var(--ok)" stroke-width="2.4" stroke-linejoin="round"/>
       <path d="${pathOf("signups")}" fill="none" stroke="var(--muted2)" stroke-width="1.6" stroke-dasharray="5 4" stroke-linejoin="round" opacity=".75"/>
       ${dotsA}${dotsS}${xl}
     </svg>`;
}

let _trendResize = null;
window.addEventListener("resize", () => {
  clearTimeout(_trendResize);
  _trendResize = setTimeout(() => drawTrend($("trendChart")), 180);
});

/* ---------- 状态渲染 ---------- */
function renderState(s) {
  state = s;
  if ($("acctNow")) $("acctNow").textContent = acctNowText(s);
  const pill = $("pillRun");
  if (s.running) {
    pill.className = "pill pill-on";
    pill.textContent = "运行中";
  } else {
    pill.className = "pill pill-off";
    pill.textContent = "已停止";
  }
  $("badgeDry").classList.toggle("hidden", !s.dry_run);
  $("badgeFatal").classList.toggle("hidden", !(s.fatal));
  $("btnStart").disabled = s.running;
  $("btnStop").disabled = !s.running;
  $("btnCycle").disabled = !s.running;
  $("kvInterval").textContent = s.interval_sec + "s";
  $("kvAuto").textContent = s.auto ? "开启" : "关闭";
  $("kvMail").textContent = s.mail_ready ? "已就绪" : "未配置";
  $("kvFails").textContent = s.consec_fail;
  $("kvFails").style.color = s.consec_fail > 0 ? "var(--warn)" : "";
  $("kvCycles").textContent = s.cycle_count;
  $("kvSince").textContent = s.started_at ? fmtDur(Date.now() / 1000 - s.started_at) + "前" : "—";
  $("stOk").textContent = s.stats.ok;
  $("stTotal").textContent = s.stats.total;
  $("stSeen").textContent = s.stats.seen;
  $("stToday").textContent = s.stats.ok_today;
  if (s.session && s.session.name) {
    $("acctCard").querySelector(".acct-name").textContent = s.session.name;
    $("acctCard").querySelector(".acct-school").textContent = (s.session.school || "") + " · " + s.account_phone;
    $("sbUser").textContent = s.session.school + " · " + s.session.name;
  }
  $("sbConn").className = "sb-item dot dot-ok";
  $("sbConn").textContent = "已连接";
  if (s.running && !s.next_run_at) $("nextRun").textContent = "准备中…";
  if (s.running && s.next_run_at) $("nextRun").textContent = "下一轮 " + fmtDur(Math.max(0, s.next_run_at - Date.now() / 1000));
  if (!s.running) $("nextRun").textContent = "引擎未运行";
}
setInterval(() => {
  if (!state) return;
  $("nextRun").textContent = state.running
    ? (state.next_run_at ? "下一轮 " + fmtDur(Math.max(0, state.next_run_at - Date.now() / 1000)) : "准备中…")
    : "引擎未运行";
}, 1000);

async function pollState() {
  try {
    renderState(await api("/api/state"));
  } catch (e) {
    $("sbConn").className = "sb-item dot dot-err";
    $("sbConn").textContent = "连接断开";
  }
}
setInterval(pollState, 2000);

/* ---------- 账号切换 ---------- */
function acctNowText(s) {
  if (!s || !s.session || !s.session.name) return "未登录（等待引擎启动后自动登录）";
  return "当前绑定：" + s.session.name + " · " + (s.session.school || "") + "（" + s.account_phone + "）";
}
$("btnApplyAcct").onclick = async function () {
  const phone = String($("fPhone").value || "").trim();
  const pwd = String($("fPwd").value || "").trim();
  if (phone.length < 6) { $("acctRes").textContent = "请先填写手机号"; return; }
  this.disabled = true;
  $("acctRes").textContent = "正在验证并切换…";
  try {
    const r = await post("/api/account/apply", { phone, password: pwd });
    if (r.ok) {
      $("acctRes").textContent = "✔ 已切换为 " + (r.session && r.session.name || phone);
      $("fPwd").value = "";
      $("fPwd").placeholder = "留空则保持原密码";
      toast("账号已切换：" + (r.session && r.session.name), "ok");
      setTimeout(pollState, 600);
    } else {
      $("acctRes").textContent = "✘ " + (r.msg || "切换失败");
      toast("账号验证失败：" + (r.msg || ""), "err");
    }
  } catch (e) { $("acctRes").textContent = "请求失败：" + e.message; }
  this.disabled = false;
};
async function ctrl(action) {
  $("btnStart").disabled = true; $("btnStop").disabled = true; $("btnCycle").disabled = true;
  try {
    await post("/api/control", { action });
    toast(action === "start" ? "引擎启动中…" : action === "stop" ? "引擎已停止" : "已触发一轮扫描");
    setTimeout(pollState, 400);
    if (action === "cycle") setTimeout(pollState, 2000);
  } catch (e) { toast("操作失败：" + e.message, "err"); }
}
$("btnStart").onclick = () => ctrl("start");
$("btnStop").onclick = () => ctrl("stop");
$("btnCycle").onclick = () => ctrl("cycle");
$("btnPause").onclick = function () {
  paused = !paused;
  this.classList.toggle("on", paused);
  this.textContent = paused ? "恢复滚动" : "暂停滚动";
  if (!paused) { const f = $("feed"); f.scrollTop = f.scrollHeight; }
};
$("btnClearView").onclick = clearView;

/* ---------- 主题 ---------- */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("dmk-theme", t); } catch (e) { /* ignore */ }
}
$("btnTheme").onclick = function () {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
};

/* ---------- 设置页 ---------- */
const textlist = (v) => String(v || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
async function loadSettings() {
  try {
    const d = await api("/api/config");
    const c = d.cfg;
    $("fInterval").value = (c.poll && c.poll.interval_sec) || 900;
    $("fMaxPages").value = (c.poll && c.poll.max_pages) || 2;
    $("fMaxRetry").value = (c.signup && c.signup.max_fail_retries) || 3;
    $("fAuto").checked = !c.signup || c.signup.auto !== false;
    $("fDry").checked = !!c.dry_run;
    $("fInc").value = ((c.rules && c.rules.name_include) || []).join("\n");
    $("fExc").value = ((c.rules && c.rules.name_exclude) || []).join("\n");
    $("fDetail").checked = !c.rules || c.rules.detail_check !== false;
    $("fDetailKw").value = ((c.rules && c.rules.detail_kw) || ["线上", "online"]).join(",");
    $("fPhone").value = (c.account && c.account.phone) || "";
    $("fPwd").value = "";
    $("fPwd").placeholder = (c.account && c.account.password) ? "已设置，留空不修改" : "未设置";
    $("fMailFrom").value = (c.mail && c.mail.from_addr) || "";
    $("fMailCode").value = "";
    $("fMailCode").placeholder = (c.mail && c.mail.auth_code) ? "已设置，留空不修改" : "16 位授权码";
    $("fMailTo").value = (c.mail && c.mail.to_addr) || "";
    try {
      const a = await api("/api/autostart");
      $("fAutoStart").checked = !!a.enabled;
      $("autoStartHint").textContent = a.enabled
        ? "已启用：登录 Windows 后自动拉起工作台与引擎\n" + (a.cmd || "")
        : "未启用：开机后需手动双击 start_dashboard.bat";
    } catch (e) { $("fAutoStart").checked = false; }
  } catch (e) { toast("读取配置失败", "err"); }
}
async function saveSettings() {
  const num = (id, dft) => { const v = parseInt($(id).value, 10); return isNaN(v) || v <= 0 ? dft : v; };
  const cfg = {
    poll: { interval_sec: num("fInterval", 900), max_pages: num("fMaxPages", 2) },
    signup: { max_fail_retries: num("fMaxRetry", 3), auto: $("fAuto").checked },
    rules: {
      name_include: textlist($("fInc").value),
      name_exclude: textlist($("fExc").value),
      detail_check: $("fDetail").checked,
      detail_kw: String($("fDetailKw").value).split(",").map((s) => s.trim()).filter(Boolean),
    },
    dry_run: $("fDry").checked,
    account: { phone: String($("fPhone").value).trim(), password: String($("fPwd").value).trim() },
    mail: {
      from_addr: String($("fMailFrom").value).trim(),
      auth_code: String($("fMailCode").value).trim(),
      to_addr: String($("fMailTo").value).trim(),
    },
  };
  try {
    await post("/api/config", { cfg });
    toast("配置已保存并热更新");
    setTimeout(pollState, 500);
  } catch (e) { toast("保存失败：" + e.message, "err"); }
}
$("btnSaveCfg").onclick = saveSettings;
$("btnMailTest").onclick = async function () {
  this.disabled = true;
  $("mailTestRes").textContent = "发送中…";
  try {
    const r = await post("/api/mailtest");
    $("mailTestRes").textContent = r.ok ? "已发送，请查收邮箱" : "发送失败";
    toast(r.ok ? "测试邮件已发送" : "测试邮件发送失败", r.ok ? "ok" : "err");
  } catch (e) { $("mailTestRes").textContent = "发送失败"; }
  this.disabled = false;
};
$("fAutoStart").onchange = async function () {
  try {
    const r = await post("/api/autostart", { enabled: this.checked });
    $("autoStartHint").textContent = this.checked
      ? "已启用：登录 Windows 后自动拉起工作台与引擎\n" + (r.cmd || "")
      : "未启用：开机后需手动双击 start_dashboard.bat";
    toast(r.ok ? (this.checked ? "已开启开机自启" : "已关闭开机自启") : "设置失败", r.ok ? "ok" : "err");
  } catch (e) { toast("设置失败：" + e.message, "err"); }
};
$("btnNotifTest").onclick = async function () {
  try {
    const r = await post("/api/notifytest");
    $("notifTestRes").textContent = r.ok ? "已弹出气泡" : "不可用";
    toast(r.ok ? "气泡通知已弹出" : "系统通知不可用（不影响邮箱）", r.ok ? "ok" : "err");
  } catch (e) { $("notifTestRes").textContent = "失败"; }
};

/* ---------- 导航 ---------- */
document.querySelectorAll(".rail-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".rail-item").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
    $("page-" + btn.dataset.page).classList.remove("hidden");
    const pg = btn.dataset.page;
    if (pg === "overview") loadTrend();
    if (pg === "records") loadRecords();
    if (pg === "activity") loadArchive();
    if (pg === "settings") loadSettings();
  });
});
$("btnRefreshRec").onclick = loadRecords;
$("btnRefreshArc").onclick = loadArchive;

/* ---------- SSE ---------- */
let sseMissed = false;
function connectSSE() {
  const es = new EventSource("/api/stream");
  es.onopen = async () => {
    if (!sseMissed) return;
    sseMissed = false;
    // 断线期间的事件补拉（只补 lastId 之后的新事件，不重灌历史）
    try {
      const d = await api("/api/events?after=" + lastId);
      d.rows.forEach(addFeedItem);
      if (d.rows.length) lastId = d.next;
    } catch (err) { /* 下轮重连再补 */ }
  };
  es.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      if (ev.id && ev.id > lastId) lastId = ev.id;
      addFeedItem(ev);
      const page = document.querySelector(".rail-item.active").dataset.page;
      if (page === "records" && ["hit", "signup", "cycle", "mail"].includes(ev.type)) loadRecords();
      if (page === "activity" && ["hit", "signup"].includes(ev.type)) loadArchive();
      if (page === "overview" && ["signup", "cycle"].includes(ev.type)) loadTrend();
    } catch (err) { /* ignore */ }
  };
  es.onerror = () => {
    sseMissed = true;
    $("sbConn").className = "sb-item dot dot-err";
    $("sbConn").textContent = "实时流重连中…";
    setTimeout(() => { $("sbConn").className = "sb-item dot dot-ok"; $("sbConn").textContent = "已连接"; }, 1500);
  };
}

/* ---------- 启动 ---------- */
(async function boot() {
  try { applyTheme(localStorage.getItem("dmk-theme") || "dark"); } catch (e) { applyTheme("dark"); }
  pollState();
  connectSSE();
  loadTrend();
  try {
    const d = await api("/api/events?after=0");
    d.rows.forEach(addFeedItem);
    if (d.rows.length) lastId = d.next;
  } catch (e) { /* 服务未就绪由 pollState 兜底 */ }
})();
