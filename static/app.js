// twinsim の画面。空間の真上の図の上でカメラを動かし、シナリオの値を変えて計算し、結果（要約・確認の図・動画）を見る。
"use strict";

const $ = (id) => document.getElementById(id);
const S = { space: null, spec: null, img: null, runId: null, drag: null, poll: null };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `${r.status}`);
  return j;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });

// ---- カメラ（USD のカメラと同じ: -Z を見て +Y が上） ----
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const n = Math.hypot(...a) || 1; return a.map((v) => v / n); };

function camModel(c, defaults = {}) {
  const w = c.width || defaults.width || 1280, h = c.height || defaults.height || 720;
  const focal = c.focal_mm || 12.0, ap = c.h_aperture_mm || 20.955;
  const f = norm(sub(c.target, c.eye));
  let s = cross(f, [0, 0, 1]);
  if (Math.hypot(...s) < 1e-9) s = cross(f, [0, 1, 0]);
  s = norm(s);
  const u = cross(s, f);
  const fx = (focal / ap) * w;
  return { eye: c.eye, f, s, u, fx, fy: fx, cx: w / 2, cy: h / 2, w, h };
}
function project(m, p) {
  const r = sub(p, m.eye), depth = dot(r, m.f);
  if (depth <= 0.05) return null;
  return [m.cx + (m.fx * dot(r, m.s)) / depth, m.cy - (m.fy * dot(r, m.u)) / depth];
}
function rayFloor(m, px, py, z, far = 30) {
  const d = [0, 1, 2].map((i) => m.f[i] + m.s[i] * ((px - m.cx) / m.fx) - m.u[i] * ((py - m.cy) / m.fy));
  if (d[2] < -1e-6) {
    const t = (z - m.eye[2]) / d[2];
    if (t > 0 && t < far) return [m.eye[0] + t * d[0], m.eye[1] + t * d[1]];
  }
  const dn = norm(d);
  return [m.eye[0] + far * dn[0], m.eye[1] + far * dn[1]];
}

// ---- 地図 ----
const canvas = $("map"), ctx = canvas.getContext("2d");
let topCam = null, scale = 1;

function W2C(x, y) {
  const p = project(topCam, [x, y, S.space.z]);
  return p ? [p[0] * scale, p[1] * scale] : null;
}
function C2W(cx, cy) { return rayFloor(topCam, cx / scale, cy / scale, S.space.z, 1e4); }

function resize() {
  if (!S.space || !topCam) return;
  const w = canvas.parentElement.clientWidth - 16;
  scale = w / topCam.w;
  canvas.width = w;
  canvas.height = topCam.h * scale;
  draw();
}

function selectedCams() { return (S.spec?.cameras || []).map(resolveCam); }
function resolveCam(c) {
  const base = S.space.cameras[c.name] || {};
  return { ...base, ...c, eye: c.eye || base.eye, target: c.target || base.target };
}

function draw() {
  if (!S.space || !topCam) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (S.img) ctx.drawImage(S.img, 0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "rgba(255,255,255,0.25)";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.font = "12px sans-serif";
  if ($("show-zones").checked) {
    for (const [name, poly] of Object.entries(S.space.zones)) {
      const pts = poly.map((p) => W2C(p[0], p[1])).filter(Boolean);
      if (pts.length < 3) continue;
      ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p))); ctx.closePath();
      ctx.strokeStyle = "rgba(90,90,90,0.8)"; ctx.lineWidth = 1; ctx.stroke();
      const c = pts.reduce((a, p) => [a[0] + p[0] / pts.length, a[1] + p[1] / pts.length], [0, 0]);
      ctx.fillStyle = "#444"; ctx.fillText(name, c[0] - 20, c[1]);
    }
  }
  if ($("show-pois").checked) {
    for (const [name, p] of Object.entries(S.space.pois)) {
      if (p.line) {
        const a = W2C(...p.line[0]), b = W2C(...p.line[1]);
        if (a && b) { ctx.strokeStyle = "#a1452b"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke(); }
      }
      const xy = p.xy || (p.line ? [(p.line[0][0] + p.line[1][0]) / 2, (p.line[0][1] + p.line[1][1]) / 2] : null);
      if (!xy) continue;
      const q = W2C(xy[0], xy[1]); if (!q) continue;
      const col = { spawn: "#2a7a2a", exit: "#2a7a2a", elevator: "#7a2a7a", gate: "#a1452b", spot: "#30587a", prop: "#b07a00" }[p.kind] || "#555";
      ctx.fillStyle = col; ctx.beginPath(); ctx.arc(q[0], q[1], 4, 0, 7); ctx.fill();
      ctx.fillText(name, q[0] + 6, q[1] - 4);
    }
  }
  selectedCams().forEach((c, k) => {
    if (!c.eye || !c.target) return;
    const m = camModel(c, S.spec.render);
    if ($("show-frustum").checked) {
      const corners = [[0, 0], [m.w, 0], [m.w, m.h], [0, m.h]].map(([x, y]) => rayFloor(m, x, y, S.space.z, 25));
      const pts = corners.map((p) => W2C(p[0], p[1])).filter(Boolean);
      if (pts.length === 4) {
        ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p))); ctx.closePath();
        ctx.fillStyle = "rgba(220,40,40,0.12)"; ctx.fill(); ctx.strokeStyle = "rgba(220,40,40,0.6)"; ctx.lineWidth = 1; ctx.stroke();
      }
    }
    const e = W2C(c.eye[0], c.eye[1]), t = W2C(c.target[0], c.target[1]);
    if (!e || !t) return;
    ctx.strokeStyle = "#d02020"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(...e); ctx.lineTo(...t); ctx.stroke();
    ctx.fillStyle = "#d02020"; ctx.beginPath(); ctx.arc(e[0], e[1], 6, 0, 7); ctx.fill();
    ctx.fillRect(t[0] - 5, t[1] - 5, 10, 10);
    ctx.font = "bold 13px sans-serif"; ctx.fillText(c.name, e[0] + 8, e[1] + 4); ctx.font = "12px sans-serif";
  });
}

function handleAt(cx, cy) {
  let best = null;
  selectedCams().forEach((c, k) => {
    for (const which of ["eye", "target"]) {
      if (!c[which]) continue;
      const p = W2C(c[which][0], c[which][1]);
      if (!p) continue;
      const d = Math.hypot(p[0] - cx, p[1] - cy);
      if (d < 12 && (!best || d < best.d)) best = { k, which, d };
    }
  });
  return best;
}
function evPos(ev) { const r = canvas.getBoundingClientRect(); return [(ev.clientX - r.left) * (canvas.width / r.width), (ev.clientY - r.top) * (canvas.height / r.height)]; }
canvas.addEventListener("mousedown", (ev) => { S.drag = handleAt(...evPos(ev)); });
canvas.addEventListener("mousemove", (ev) => {
  const [cx, cy] = evPos(ev);
  if (!topCam) return;
  const w = C2W(cx, cy);
  $("cursor").textContent = `x ${w[0].toFixed(2)}, y ${w[1].toFixed(2)}`;
  if (!S.drag) { canvas.style.cursor = handleAt(cx, cy) ? "grab" : "crosshair"; return; }
  const cam = S.spec.cameras[S.drag.k], r = resolveCam(cam);
  cam.eye = cam.eye || [...r.eye]; cam.target = cam.target || [...r.target];
  cam[S.drag.which] = [+w[0].toFixed(2), +w[1].toFixed(2), cam[S.drag.which][2]];
  renderCameras(); draw(); syncJson();
});
window.addEventListener("mouseup", () => { S.drag = null; });
["show-zones", "show-pois", "show-frustum"].forEach((id) => $(id).addEventListener("change", draw));
window.addEventListener("resize", resize);

// ---- 設定の画面 ----
function num(v, d = 0) { const x = parseFloat(v); return Number.isFinite(x) ? x : d; }
function rateText(rate) {
  if (typeof rate === "number") return String(rate);
  if (rate.type === "piecewise") return rate.per_min.map(([t, r]) => `${t}:${r}`).join(", ");
  return String(rate.per_min);
}
function parseRate(text) {
  if (text.includes(":")) return { type: "piecewise", per_min: text.split(",").map((s) => s.trim().split(":").map(Number)) };
  return { type: "constant", per_min: num(text, 1) };
}

function renderStreams() {
  const box = $("streams"); box.innerHTML = "";
  S.spec.streams.forEach((st, i) => {
    const d = document.createElement("div"); d.className = "stream";
    const lam = st.group_size && st.group_size.lam !== undefined ? st.group_size.lam : "";
    d.innerHTML = `<h4>${st.name || "流れ " + (i + 1)}（現れる所: ${st.origin}）</h4>
      <label>到着（人/分。時間帯で変えるなら 秒:人/分, …）<input type="text" data-k="rate" value="${rateText(st.rate)}" style="width:200px"></label>
      <label>まとまり（平均）<input type="number" step="0.1" min="0" data-k="lam" value="${lam}" placeholder="なし"></label>
      <table class="dest"><tr><th>行き先</th><th>重み</th><th>種類</th></tr>
      ${(st.destinations || []).map((de, j) => `<tr><td>${typeof de === "string" ? de : de.to}${de.then ? " → …" : ""}${(de.via || []).length ? "（ゲート経由）" : ""}</td>
        <td><input type="number" step="0.01" min="0" data-dest="${j}" value="${de.p ?? 1}"></td><td>${(de.types || []).join(",")}</td></tr>`).join("")}
      </table>`;
    d.querySelector('[data-k="rate"]').addEventListener("change", (e) => { st.rate = parseRate(e.target.value); syncJson(); });
    d.querySelector('[data-k="lam"]').addEventListener("change", (e) => {
      if (e.target.value === "") delete st.group_size; else st.group_size = { type: "zero_truncated_poisson", lam: num(e.target.value) };
      syncJson();
    });
    d.querySelectorAll("[data-dest]").forEach((inp) => inp.addEventListener("change", (e) => {
      st.destinations[+e.target.dataset.dest].p = num(e.target.value); syncJson();
    }));
    box.appendChild(d);
  });
}

function renderEv() {
  const ev = S.spec.elevator;
  $("ev-box").classList.toggle("hidden", !ev);
  if (!ev) return;
  const iv = ev.schedule?.interval || { min: 35, max: 60 };
  $("ev-min").value = iv.min; $("ev-max").value = iv.max; $("ev-cap").value = ev.capacity ?? 8;
  $("ev-alight").value = ev.alight?.count?.lam ?? 0;
}
["ev-min", "ev-max", "ev-cap", "ev-alight"].forEach((id) => $(id).addEventListener("change", () => {
  const ev = S.spec.elevator; if (!ev) return;
  ev.schedule = ev.schedule || { type: "interval" };
  ev.schedule.type = "interval";
  ev.schedule.interval = { type: "uniform", min: num($("ev-min").value, 35), max: num($("ev-max").value, 60) };
  ev.capacity = num($("ev-cap").value, 8);
  if (ev.alight) ev.alight.count = { type: "poisson", lam: num($("ev-alight").value) };
  syncJson();
}));

function renderGates() {
  const gates = Object.entries(S.space.pois).filter(([, p]) => p.kind === "gate");
  $("gate-box").classList.toggle("hidden", !gates.length);
  $("gates").innerHTML = gates.map(([k]) => `<label>${k}: 1 人を通す間隔（秒）<input type="number" step="0.1" min="0.3" data-gate="${k}" value="${S.spec.gates?.[k]?.service_s ?? 1.5}"></label>`).join("");
  $("gates").querySelectorAll("[data-gate]").forEach((inp) => inp.addEventListener("change", (e) => {
    S.spec.gates = S.spec.gates || {}; S.spec.gates[e.target.dataset.gate] = { service_s: num(e.target.value, 1.5) }; syncJson();
  }));
}

function renderCameras() {
  const box = $("cameras");
  const names = Object.keys(S.space.cameras);
  const chosen = new Map(S.spec.cameras.map((c, i) => [c.name, i]));
  box.innerHTML = names.map((n) => {
    const i = chosen.get(n);
    const c = i !== undefined ? resolveCam(S.spec.cameras[i]) : S.space.cameras[n];
    const xyz = (k) => (c[k] || [0, 0, 0]).map((v, j) => `<input class="xyz" type="number" step="0.1" data-cam="${n}" data-k="${k}" data-j="${j}" value="${(+v).toFixed(2)}" ${i === undefined ? "disabled" : ""}>`).join("");
    return `<div class="cam"><label><input type="checkbox" data-use="${n}" ${i !== undefined ? "checked" : ""}> <b>${n}</b></label>
      <span class="muted">${S.space.cameras[n].note || ""}</span>
      <div class="row">位置 ${xyz("eye")}</div><div class="row">見る点 ${xyz("target")}</div></div>`;
  }).join("");
  box.querySelectorAll("[data-use]").forEach((cb) => cb.addEventListener("change", (e) => {
    const n = e.target.dataset.use;
    if (e.target.checked) S.spec.cameras.push({ name: n }); else S.spec.cameras = S.spec.cameras.filter((c) => c.name !== n);
    renderCameras(); draw(); syncJson();
  }));
  box.querySelectorAll("input.xyz").forEach((inp) => inp.addEventListener("change", (e) => {
    const { cam, k, j } = e.target.dataset;
    const c = S.spec.cameras.find((x) => x.name === cam); if (!c) return;
    const r = resolveCam(c);
    c.eye = c.eye || [...r.eye]; c.target = c.target || [...r.target];
    c[k][+j] = num(e.target.value); draw(); syncJson();
  }));
}

function renderProps() {
  const props = Object.entries(S.space.pois).filter(([, p]) => p.kind === "prop");
  $("props-box").classList.toggle("hidden", !props.length);
  const on = new Set(S.spec.render?.props || []);
  $("props").innerHTML = props.map(([k, p]) => `<label><input type="checkbox" data-prop="${k}" ${on.has(k) ? "checked" : ""}> ${k}（${p.prop}）</label>`).join("");
  $("props").querySelectorAll("[data-prop]").forEach((cb) => cb.addEventListener("change", (e) => {
    const s = new Set(S.spec.render.props || []);
    e.target.checked ? s.add(e.target.dataset.prop) : s.delete(e.target.dataset.prop);
    S.spec.render.props = [...s]; syncJson();
  }));
}

function renderAll() {
  $("duration").value = S.spec.duration_s; $("seed").value = S.spec.seed;
  renderStreams(); renderEv(); renderGates(); renderCameras(); renderProps(); syncJson(); draw();
}
$("duration").addEventListener("change", (e) => { S.spec.duration_s = num(e.target.value, 60); syncJson(); });
$("seed").addEventListener("change", (e) => { S.spec.seed = Math.round(num(e.target.value, 0)); syncJson(); });
function syncJson() { $("spec-json").value = JSON.stringify(S.spec, null, 1); }
$("apply-json").addEventListener("click", () => {
  try { S.spec = JSON.parse($("spec-json").value); renderAll(); $("run-msg").textContent = "JSON を反映しました"; }
  catch (e) { $("run-msg").textContent = "JSON を読めません: " + e.message; }
});
$("download").addEventListener("click", () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(S.spec, null, 1)], { type: "application/json" }));
  a.download = `${S.spec.name || "scenario"}.json`; a.click();
});

async function loadTemplate(name) {
  S.spec = await api(`/api/templates/${name}`);
  if (!S.space || S.space.name !== S.spec.space) {
    S.space = await api(`/api/spaces/${S.spec.space}`);
    topCam = S.space.top_view ? camModel(S.space.top_view) : null;
    S.img = null;
    if (S.space.has_top) {
      const img = new Image();
      img.onload = () => { S.img = img; draw(); };
      img.src = `/api/spaces/${S.space.name}/top`;
    }
  }
  $("space-name").textContent = `空間: ${S.space.title || S.space.name}（${S.space.license || ""}）`;
  resize(); renderAll();
}

// ---- 計算と結果 ----
$("run").addEventListener("click", async () => {
  $("run").disabled = true; $("run-msg").textContent = "計算を始めます…";
  try {
    const { id } = await post("/api/runs", { scenario: S.spec });
    $("run-msg").textContent = `計算中: ${id}`;
    await waitRun(id);
    switchTab("results"); await refreshRuns(); await showRun(id);
    $("run-msg").textContent = `できました: ${id}`;
  } catch (e) { $("run-msg").innerHTML = `<span class="err">${e.message}</span>`; }
  $("run").disabled = false;
});
async function waitRun(id) {
  for (;;) {
    const r = await api(`/api/runs/${id}`);
    if (r.job.status === "error") throw new Error(r.job.error);
    if (r.job.status !== "running" && r.summary) return r;
    await new Promise((res) => setTimeout(res, 1000));
  }
}
async function refreshRuns() {
  const runs = await api("/api/runs");
  $("runs").innerHTML = runs.map((r) => `<li data-id="${r.id}" class="${r.id === S.runId ? "active" : ""}"><span>${r.id}</span>
    <span class="muted">${r.status}${r.videos.length ? "・動画 " + r.videos.length : ""}</span></li>`).join("");
  $("runs").querySelectorAll("li").forEach((li) => li.addEventListener("click", () => showRun(li.dataset.id)));
}
$("refresh").addEventListener("click", refreshRuns);

const fileUrl = (id, path) => `/api/runs/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}`;
async function showRun(id) {
  S.runId = id;
  $("runs").querySelectorAll("li").forEach((li) => li.classList.toggle("active", li.dataset.id === id));
  const r = await api(`/api/runs/${id}`);
  const s = r.summary || {};
  const ev = s.elevator || {};
  const states = Object.entries(s.state_seconds || {}).map(([k, v]) => `${k} ${Math.round(v)} 秒`).join("・");
  const cams = r.files.filter((f) => f.startsWith("mot/") && f.endsWith(".txt")).map((f) => f.slice(4, -4));
  const vids = r.files.filter((f) => f.startsWith("video/") && f.endsWith(".mp4"));
  const ren = r.render;
  $("run-detail").innerHTML = `
    <h3>${id}</h3>
    <div class="chips"><span class="chip">${s.people ?? "-"} 人</span><span class="chip">同時に最大 ${s.max_present ?? "-"} 人</span>
      <span class="chip">グループ ${s.groups ?? "-"}</span>
      <span class="chip">EV ${ev.arrivals ?? 0} 回・乗った ${ev.boarded ?? 0}・待ち 平均 ${ev.wait_mean_s ?? "-"} 秒</span>
      <span class="chip">ゲート 入館 ${(s.gate_passes || {}).in ?? 0}・退館 ${(s.gate_passes || {}).out ?? 0}</span></div>
    <div class="muted">状態ごとの時間: ${states}</div>
    <img src="${fileUrl(id, "preview.png")}" alt="確認の図">
    <h3>描画（GPU）</h3>
    <div class="row"><button class="secondary" id="render-test">いちばん混む 5 秒を試し撮り</button>
      <button class="secondary" id="render-all">全部を描画</button></div>
    <div id="render-msg" class="muted">${ren ? `描画: ${ren.status}${ren.error ? "・" + ren.error : ""}${ren.seconds ? "・" + ren.seconds + " 秒" : ""}` : ""}</div>
    ${vids.map((v) => `<div class="muted">${v}</div><video src="${fileUrl(id, v)}" controls muted loop></video>`).join("")}
    <h3>MOPF の人流モニターの設定</h3>
    <div class="row">${cams.map((c) => `<button class="secondary" data-mopf="${c}">${c}</button>`).join("")}</div>
    <div id="mopf-msg" class="muted"></div>
    <h3>ファイル</h3>
    <div class="files">${r.files.filter((f) => !f.includes("/") || f.startsWith("graph/") || f.startsWith("mot/") || f.startsWith("video/"))
      .map((f) => `<a href="${fileUrl(id, f)}" target="_blank">${f}</a>`).join("")}</div>`;
  $("render-test").addEventListener("click", () => doRender(id, { window: "busy", seconds: 5 }));
  $("render-all").addEventListener("click", () => doRender(id, {}));
  $("run-detail").querySelectorAll("[data-mopf]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const m = await post(`/api/runs/${id}/mopf`, { camera: b.dataset.mopf });
      $("mopf-msg").textContent = `線 ${m.config.lines.length}・エリア ${m.config.zones.map((z) => z.name).join(", ") || "なし"}・対応の点 ${m.info.points}（${m.out}）`;
    } catch (e) { $("mopf-msg").innerHTML = `<span class="err">${e.message}</span>`; }
  }));
  if (ren && ren.status === "running") pollRender(id);
}
async function doRender(id, body) {
  try {
    const est = (await post(`/api/runs/${id}/render`, body)).estimate;
    if (!est.isaac_ready) { $("render-msg").innerHTML = `<span class="err">Isaac Sim が動いていません。ampb で cd ~/twinsim && ./isaac_up.sh <空いている GPU の番号> を実行し、1 分ほど待ってからもう一度押してください（終わったら isim down）</span>`; return; }
    const min = Math.ceil(est.estimate_s / 60);
    if (!confirm(`${est.frames} コマ（${est.range[0]}〜${est.range[1]}）を描画します。目安 ${min} 分、GPU ${est.gpu}。共用の GPU なので、空きを確かめてから始めてください。始めますか？`)) return;
    await post(`/api/runs/${id}/render`, { ...body, confirm: true });
    $("render-msg").textContent = `描画中（目安 ${min} 分）…`;
    pollRender(id);
  } catch (e) { $("render-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}
function pollRender(id) {
  clearInterval(S.poll);
  S.poll = setInterval(async () => {
    const r = await api(`/api/runs/${id}`);
    if (!r.render || r.render.status === "running") return;
    clearInterval(S.poll);
    if (S.runId === id) showRun(id);
  }, 5000);
}

function switchTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $("tab-settings").classList.toggle("hidden", name !== "settings");
  $("tab-results").classList.toggle("hidden", name !== "results");
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => { switchTab(b.dataset.tab); if (b.dataset.tab === "results") refreshRuns(); }));

(async function init() {
  const tpls = await api("/api/templates");
  $("template").innerHTML = tpls.map((t) => `<option value="${t.name}">${t.name}（${t.space}）${t.title ? "— " + t.title : ""}</option>`).join("");
  $("template").addEventListener("change", (e) => loadTemplate(e.target.value));
  const isaac = await api("/api/isaac");
  $("isaac").textContent = `Isaac Sim: ${isaac.ready ? "受け付け中" : "止まっている"}`;
  $("isaac").classList.toggle("ok", isaac.ready);
  await loadTemplate(tpls.find((t) => t.name === "office_gate_ev") ? "office_gate_ev" : tpls[0].name);
  $("template").value = S.spec.name;
  refreshRuns();
})();
