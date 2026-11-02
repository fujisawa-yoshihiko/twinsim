// twinsim の画面。空間の真上の図の上でカメラを動かし、シナリオの値を変えて計算し、結果（要約・確認の図・動画）を見る。
"use strict";

const $ = (id) => document.getElementById(id);
const S = { space: null, spec: null, img: null, runId: null, drag: null, poll: null };

// 設定や結果の名前は利用者が決められるので、HTML に入れる値は全部 esc を通す
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function showError(el, msg) {
  el.textContent = "";
  const span = document.createElement("span");
  span.className = "err";
  span.textContent = msg;
  el.appendChild(span);
}

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
  if (!S.space) return;
  if (!topCam) { draw(); return; }  // 真上の図がない空間
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
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!S.space || !topCam) return;
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
  S.spec.streams.forEach((st, i) => {  // 人の流れの現れる所（緑の四角をドラッグして動かす）
    const pts = originPoints(st).map((p) => W2C(p[0], p[1])).filter(Boolean);
    ctx.strokeStyle = "#0a7a3a"; ctx.lineWidth = 3;
    if (pts.length === 2) { ctx.beginPath(); ctx.moveTo(...pts[0]); ctx.lineTo(...pts[1]); ctx.stroke(); }
    ctx.fillStyle = "#0a7a3a"; ctx.font = "bold 13px sans-serif";
    pts.forEach((p) => ctx.fillRect(p[0] - 6, p[1] - 6, 12, 12));
    if (pts.length) ctx.fillText(`S${i + 1}`, pts[0][0] + 9, pts[0][1] + 15);
    ctx.font = "12px sans-serif";
  });
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

// ---- 人の流れの現れる所 ----
function originPoints(st) {  // 地図に描く点（線なら両端）
  const o = st.origin;
  if (typeof o !== "string") return o?.line || (o?.xy ? [o.xy] : []);
  const p = S.space.pois[o];
  return !p ? [] : p.line || (p.xy ? [p.xy] : []);
}
function customOrigin(st) {  // 場所の名前で書いた流れを、座標の形に直す
  if (typeof st.origin === "string") {
    const pts = originPoints(st).map((p) => [...p]);
    st.origin = pts.length === 2 ? { line: pts } : { xy: pts[0] };
  }
  return st.origin;
}
function snapWalkable(x, y) {  // いちばん近い歩ける点（space.py の cell と同じ格子）
  const g = S.space.grid, ny = g.rows.length;
  const ok = (i, j) => g.rows[ny - 1 - i]?.[j] === ".";
  const i0 = Math.floor((y - g.y0) / g.res + 0.5), j0 = Math.floor((x - g.x0) / g.res + 0.5);
  if (ok(i0, j0)) return [x, y];
  const reach = Math.max(ny, g.rows[0].length);
  for (let r = 1; r < reach; r++) {
    let best = null;
    for (let di = -r; di <= r; di++) for (let dj = -r; dj <= r; dj++) {
      if (Math.max(Math.abs(di), Math.abs(dj)) !== r || !ok(i0 + di, j0 + dj)) continue;
      const d = Math.hypot(di, dj);
      if (!best || d < best.d) best = { d, i: i0 + di, j: j0 + dj };
    }
    if (best) return [+(g.x0 + best.j * g.res).toFixed(2), +(g.y0 + best.i * g.res).toFixed(2)];
  }
  return [x, y];
}

function handleAt(cx, cy) {
  let best = null;
  S.spec.streams.forEach((st, i) => originPoints(st).forEach((p, j) => {
    const q = W2C(p[0], p[1]);
    if (!q) return;
    const d = Math.hypot(q[0] - cx, q[1] - cy);
    if (d < 12 && (!best || d < best.d)) best = { stream: i, j, d };
  }));
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
canvas.addEventListener("mousedown", (ev) => { if (topCam) S.drag = handleAt(...evPos(ev)); });
canvas.addEventListener("mousemove", (ev) => {
  const [cx, cy] = evPos(ev);
  if (!topCam) return;
  const w = C2W(cx, cy);
  $("cursor").textContent = `x ${w[0].toFixed(2)}, y ${w[1].toFixed(2)}`;
  if (!S.drag) { canvas.style.cursor = handleAt(cx, cy) ? "grab" : "crosshair"; return; }
  if (S.drag.stream !== undefined) {
    const o = customOrigin(S.spec.streams[S.drag.stream]), xy = [+w[0].toFixed(2), +w[1].toFixed(2)];
    if (o.line) o.line[S.drag.j] = xy; else o.xy = xy;
    draw(); syncJson();
    return;
  }
  const cam = S.spec.cameras[S.drag.k], r = resolveCam(cam);
  cam.eye = cam.eye || [...r.eye]; cam.target = cam.target || [...r.target];
  cam[S.drag.which] = [+w[0].toFixed(2), +w[1].toFixed(2), cam[S.drag.which][2]];
  renderCameras(); draw(); syncJson();
});
window.addEventListener("mouseup", () => {
  if (S.drag?.stream !== undefined) {  // 壁の中に置いたら、近くの歩ける所へ寄せる
    const o = S.spec.streams[S.drag.stream].origin;
    if (typeof o !== "string") {
      if (o.line) o.line[S.drag.j] = snapWalkable(...o.line[S.drag.j]); else o.xy = snapWalkable(...o.xy);
      renderStreams(); draw(); syncJson();
    }
  }
  S.drag = null;
});
["show-zones", "show-pois", "show-frustum"].forEach((id) => $(id).addEventListener("change", draw));
window.addEventListener("resize", resize);

// ---- 設定の画面 ----
function num(v, d = 0) { const x = parseFloat(v); return Number.isFinite(x) ? x : d; }
function rateText(rate) {
  if (typeof rate === "number") return String(rate);
  if (rate.type === "piecewise") return rate.per_min.map(([t, r]) => `${t}:${r}`).join(", ");
  return String(rate.per_min ?? "");
}
function parseRate(text, old) {  // 読めないときは null（前の値のままにする）
  const unit = old && old.unit ? { unit: old.unit } : {};
  if (text.includes(":")) {
    const per_min = text.split(",").map((s) => s.trim().split(":").map(Number));
    return per_min.every((p) => p.length === 2 && p.every(Number.isFinite)) ? { type: "piecewise", per_min, ...unit } : null;
  }
  return text.trim() !== "" && Number.isFinite(Number(text)) ? { type: "constant", per_min: Number(text), ...unit } : null;
}
const isDemand = (r) => r && typeof r === "object" && r.type === "lift_demand";
function demandPerMin(r) {  // literature.lift_demand_per_min と同じ式（表示用）
  const d = { ...(S.spec.demand || {}), ...r };
  const mix = { morning: { incoming: 0.85, outgoing: 0.10 }, lunch: { incoming: 0.45, outgoing: 0.45 } }[d.period || "morning"];
  if (!d.population || !mix) return null;
  return d.population * (d.peak_pct_5min ?? 12) / 100 / 5 * mix[r.flow || "incoming"] * (r.share ?? 1) * (d.level ?? 1);
}

const fixedRate = (r) => isDemand(r) || (r && typeof r === "object" && r.type === "times");  // 画面の 1 つの欄では直せない形
function rateNote(r) {
  if (!isDemand(r)) return `<span class="muted">${tr(`到着: 決めた時刻（${r.times.length} 回）`, `Arrivals: fixed times (${r.times.length})`)}</span>`;
  const n = (demandPerMin(r) ?? 0).toFixed(1), flow = esc(r.flow || "incoming"), share = esc(r.share ?? 1);
  return `<span class="muted">${tr(`到着: 建物の人数から ${n} 人/分（${flow}・割合 ${share}、Peters ら 2011）`,
    `Arrivals: from the building population, ${n} people/min (${flow}, share ${share}; Peters et al. 2011)`)}</span>`;
}

function renderStreams() {
  const box = $("streams"); box.innerHTML = "";
  S.spec.streams.forEach((st, i) => {
    const d = document.createElement("div"); d.className = "stream";
    const lam = esc(st.group_size && st.group_size.lam !== undefined ? st.group_size.lam : "");
    const dflt = S.spec.people?.profile ? tr("文献の既定", "literature default") : tr("なし", "none");
    const unit = st.rate?.unit === "persons" ? tr("人/分", "people/min") : tr("まとまり/分", "groups/min");
    const rateField = fixedRate(st.rate)
      ? rateNote(st.rate)
      : `<label>${tr(`到着（${unit}。時間帯で変えるなら 秒:率, …）`, `Arrivals (${unit}; to vary over time, s:rate, …)`)}<input type="text" data-k="rate" value="${esc(rateText(st.rate))}" style="width:200px"></label>`;
    const places = Object.entries(S.space.pois).filter(([, p]) => ["spawn", "exit"].includes(p.kind)).map(([k]) => k);
    if (typeof st.origin === "string" && !places.includes(st.origin)) places.push(st.origin);
    const mode = typeof st.origin === "string" ? st.origin : st.origin?.line ? "__line" : "__xy";
    const pts = typeof st.origin === "string" ? [] : originPoints(st);
    const coords = pts.map((p, j) => `<span>${pts.length === 2 ? tr(`端 ${j + 1}`, `End ${j + 1}`) : ""} x <input class="xyz" type="number" step="0.1" data-origin="${j}" data-axis="0" value="${(+p[0]).toFixed(2)}"> y <input class="xyz" type="number" step="0.1" data-origin="${j}" data-axis="1" value="${(+p[1]).toFixed(2)}"></span>`).join(" ");
    d.innerHTML = `<h4>S${i + 1}: ${esc(st.name || tr("流れ ", "Stream ") + (i + 1))}</h4>
      <label>${tr("現れる所", "Appears at")} <select data-k="origin">
        ${places.map((k) => `<option value="${esc(k)}" ${k === mode ? "selected" : ""}>${esc(k)}</option>`).join("")}
        <option value="__xy" ${mode === "__xy" ? "selected" : ""}>${tr("座標で指定（点）", "Coordinates (point)")}</option>
        <option value="__line" ${mode === "__line" ? "selected" : ""}>${tr("座標で指定（線）", "Coordinates (line)")}</option>
      </select></label>
      ${coords ? `<div class="row">${coords}</div>` : ""}
      ${rateField}
      <label>${tr("まとまりの λ（0 を除いたポアソン）", "Group size λ (zero-truncated Poisson)")}<input type="number" step="0.05" min="0" data-k="lam" value="${lam}" placeholder="${dflt}"></label>
      <table class="dest"><tr><th>${tr("行き先", "Destination")}</th><th>${tr("重み", "Weight")}</th><th>${tr("種類", "Types")}</th></tr>
      ${(st.destinations || []).map((de, j) => `<tr><td>${esc(typeof de === "string" ? de : de.to)}${de.then ? " → …" : ""}${(de.via || []).length ? tr("（ゲート経由）", " (via gate)") : ""}</td>
        <td><input type="number" step="0.01" min="0" data-dest="${j}" value="${esc(de.p ?? 1)}"></td><td>${esc((de.types || []).join(","))}</td></tr>`).join("")}
      </table>`;
    d.querySelector('[data-k="origin"]').addEventListener("change", (e) => {
      const v = e.target.value, c = originPoints(st)[0] || [0, 0];
      if (v === "__xy") st.origin = { xy: [+c[0], +c[1]] };
      else if (v === "__line") st.origin = { line: [[+c[0] - 1, +c[1]], [+c[0] + 1, +c[1]]] };
      else st.origin = v;
      renderStreams(); draw(); syncJson();
    });
    d.querySelectorAll("[data-origin]").forEach((inp) => inp.addEventListener("change", (e) => {
      const p = st.origin.line ? st.origin.line[+e.target.dataset.origin] : st.origin.xy;
      p[+e.target.dataset.axis] = num(e.target.value); draw(); syncJson();
    }));
    d.querySelector('[data-k="rate"]')?.addEventListener("change", (e) => {
      const rate = parseRate(e.target.value, st.rate);
      if (rate) { st.rate = rate; syncJson(); $("run-msg").textContent = ""; }
      else { e.target.value = rateText(st.rate); showError($("run-msg"), tr("到着の率を読めません", "Cannot read the arrival rate")); }
    });
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

let PROFILES = null;
async function renderPeople() {
  if (!PROFILES) PROFILES = await api("/api/profiles");
  const cur = S.spec.people?.profile || "";
  $("profile").innerHTML = `<option value="">${tr("なし（既定: 速さ・速さと密度・グループの速さと間隔は文献、人数の分布はシナリオ）",
    "None (default: speed, speed–density, and group speed and spacing from the literature; the number of people from the scenario)")}</option>` +
    Object.entries(PROFILES.profiles).map(([k, p]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${tr(`${p.title}（${k}）`, `${p.title_en || p.title} (${k})`)}</option>`).join("");
  const p = PROFILES.profiles[cur];
  $("profile-note").innerHTML = p ? `${tr("根拠", "Sources")}: ${Object.entries(p.sources).map(([k, v]) => `${k} = ${v}`).join(tr("、", ", "))}<br>${tr(p.notes, p.notes_en || p.notes).join("<br>")}` : "";
  const d = S.spec.demand || {};
  const uses = S.spec.streams.some((st) => isDemand(st.rate)) || isDemand(S.spec.elevator?.alight?.count);
  $("demand-row").classList.toggle("hidden", !uses && !S.spec.demand);
  $("demand-pop").value = d.population ?? ""; $("demand-period").value = d.period || "morning"; $("demand-pct").value = d.peak_pct_5min ?? 12;
}
$("profile").addEventListener("change", (e) => {
  // 前の組から写った値（速さ・グループなど）を残すと新しい組の既定より優先されるので、組と人物モデルだけにする
  S.spec.people = { models: S.spec.people?.models ?? "all", ...(e.target.value ? { profile: e.target.value } : {}) };
  syncJson(); renderPeople(); renderStreams(); renderGates();
});
["demand-pop", "demand-period", "demand-pct"].forEach((id) => $(id).addEventListener("change", () => {
  S.spec.demand = { ...(S.spec.demand || {}), population: num($("demand-pop").value, 600), period: $("demand-period").value,
    peak_pct_5min: num($("demand-pct").value, 12) };
  syncJson(); renderStreams();
}));

function renderEv() {
  const ev = S.spec.elevator;
  $("ev-box").classList.toggle("hidden", !ev);
  if (!ev) return;
  const sch = ev.schedule, fixed = sch && sch.type !== "interval";  // interval 以外の運行は JSON で直す
  const iv = sch?.interval || { min: 35, max: 60 };
  $("ev-min").value = fixed ? "" : iv.min ?? ""; $("ev-max").value = fixed ? "" : iv.max ?? "";
  $("ev-min").disabled = $("ev-max").disabled = !!fixed || (iv.type && iv.type !== "uniform");
  $("ev-cap").value = ev.capacity ?? 8;
  const c = ev.alight?.count, simple = c === undefined || typeof c === "number" || c.type === "poisson";
  $("ev-alight").value = simple ? (typeof c === "number" ? c : c?.lam ?? 1) : "";
  $("ev-alight").disabled = !ev.alight || !simple;
  $("ev-alight").placeholder = isDemand(c) ? tr("建物の人数から", "from building population") : "";
}
["ev-min", "ev-max"].forEach((id) => $(id).addEventListener("change", () => {
  const ev = S.spec.elevator; if (!ev) return;
  ev.schedule = { ...(ev.schedule || {}), type: "interval", interval: { type: "uniform", min: num($("ev-min").value, 35), max: num($("ev-max").value, 60) } };
  syncJson();
}));
$("ev-cap").addEventListener("change", () => { if (S.spec.elevator) { S.spec.elevator.capacity = num($("ev-cap").value, 8); syncJson(); } });
$("ev-alight").addEventListener("change", () => {
  const ev = S.spec.elevator; if (!ev?.alight || $("ev-alight").value === "") return;
  ev.alight.count = { type: "poisson", lam: num($("ev-alight").value) };
  syncJson();
});

function renderGates() {
  const gates = Object.entries(S.space.pois).filter(([, p]) => p.kind === "gate");
  $("gate-box").classList.toggle("hidden", !gates.length);
  const dflt = S.spec.people?.profile ? tr("文献の既定（中央 2.0）", "literature default (median 2.0)") : "1.5";
  $("gates").innerHTML = gates.map(([k]) => {
    const v = S.spec.gates?.[k]?.service_s;
    return `<label>${esc(k)}: ${tr("1 人を通す間隔（秒）", "time per person (s)")}<input type="number" step="0.1" min="0.3" data-gate="${esc(k)}" value="${typeof v === "number" ? v : ""}" placeholder="${dflt}" style="width:150px"></label>`;
  }).join("");
  $("gates").querySelectorAll("[data-gate]").forEach((inp) => inp.addEventListener("change", (e) => {
    S.spec.gates = S.spec.gates || {};
    if (e.target.value === "") delete S.spec.gates[e.target.dataset.gate];
    else S.spec.gates[e.target.dataset.gate] = { service_s: num(e.target.value, 1.5) };
    syncJson();
  }));
}

function renderCameras() {
  const box = $("cameras");
  const chosen = new Map(S.spec.cameras.map((c, i) => [c.name, i]));
  const names = [...new Set([...Object.keys(S.space.cameras), ...chosen.keys()])];  // 空間の候補と、設定に書いたカメラ
  box.innerHTML = names.map((n) => {
    const i = chosen.get(n);
    const c = i !== undefined ? resolveCam(S.spec.cameras[i]) : S.space.cameras[n];
    const cand = S.space.cameras[n] || {};
    const xyz = (k) => (c[k] || [0, 0, 0]).map((v, j) => `<input class="xyz" type="number" step="0.1" data-cam="${esc(n)}" data-k="${k}" data-j="${j}" value="${(+v).toFixed(2)}" ${i === undefined ? "disabled" : ""}>`).join("");
    return `<div class="cam"><label><input type="checkbox" data-use="${esc(n)}" ${i !== undefined ? "checked" : ""}> <b>${esc(n)}</b></label>
      <span class="muted">${esc(tr(cand.note || "", cand.note_en || cand.note || ""))}</span>
      <div class="row">${tr("位置", "Position")} ${xyz("eye")}</div><div class="row">${tr("見る点", "Look-at point")} ${xyz("target")}</div>
      <div class="row"><label>${tr("焦点距離（mm）", "Focal length (mm)")} <input class="xyz" type="number" step="0.5" min="1" data-focal="${esc(n)}" value="${esc(c.focal_mm ?? 12)}" ${i === undefined ? "disabled" : ""}></label></div></div>`;
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
  box.querySelectorAll("[data-focal]").forEach((inp) => inp.addEventListener("change", (e) => {
    const c = S.spec.cameras.find((x) => x.name === e.target.dataset.focal); if (!c) return;
    c.focal_mm = num(e.target.value, 12); draw(); syncJson();
  }));
}
$("add-camera").addEventListener("click", () => {  // 図の真ん中に新しいカメラを置く（ドラッグで動かす）
  const [x0, x1, y0, y1] = S.space.bounds, cx = +((x0 + x1) / 2).toFixed(2), cy = +((y0 + y1) / 2).toFixed(2), z = S.space.z;
  const used = new Set([...Object.keys(S.space.cameras), ...S.spec.cameras.map((c) => c.name)]);
  let k = 1; while (used.has(`Cam${k}`)) k++;
  S.spec.cameras.push({ name: `Cam${k}`, eye: [cx, cy, z + 2.7], target: [+(cx + 4).toFixed(2), cy, z + 0.8] });
  renderCameras(); draw(); syncJson();
});

function renderProps() {
  const props = Object.entries(S.space.pois).filter(([, p]) => p.kind === "prop");
  $("props-box").classList.toggle("hidden", !props.length);
  const on = new Set(S.spec.render?.props || []);
  $("props").innerHTML = props.map(([k, p]) => `<label><input type="checkbox" data-prop="${esc(k)}" ${on.has(k) ? "checked" : ""}> ${esc(tr(`${k}（${p.prop}）`, `${k} (${p.prop})`))}</label>`).join("");
  $("props").querySelectorAll("[data-prop]").forEach((cb) => cb.addEventListener("change", (e) => {
    const s = new Set(S.spec.render.props || []);
    e.target.checked ? s.add(e.target.dataset.prop) : s.delete(e.target.dataset.prop);
    S.spec.render.props = [...s]; syncJson();
  }));
}

function renderAll() {
  $("duration").value = S.spec.duration_s; $("seed").value = S.spec.seed;
  renderPeople(); renderStreams(); renderEv(); renderGates(); renderCameras(); renderProps(); syncJson(); draw();
}
$("duration").addEventListener("change", (e) => { S.spec.duration_s = num(e.target.value, 60); syncJson(); });
$("seed").addEventListener("change", (e) => { S.spec.seed = Math.round(num(e.target.value, 0)); syncJson(); });
function syncJson() { $("spec-json").value = JSON.stringify(S.spec, null, 1); }
$("apply-json").addEventListener("click", async () => {  // サーバーで確かめて既定の値を足す。誤りなら今の設定のまま
  try {
    const { scenario } = await post("/api/validate", { scenario: JSON.parse($("spec-json").value) });
    await useSpec(scenario);
    $("run-msg").textContent = tr("JSON を反映しました", "Applied the JSON");
  } catch (e) { showError($("run-msg"), tr("JSON を反映できません: ", "Cannot apply the JSON: ") + e.message); }
});
$("download").addEventListener("click", () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(S.spec, null, 1)], { type: "application/json" }));
  a.download = `${S.spec.name || "scenario"}.json`; a.click();
});

async function useSpec(spec) {  // 設定に合わせて空間も読み直す（読めなければ今の設定のまま）
  if (!S.space || S.space.name !== spec.space) {
    S.space = await api(`/api/spaces/${encodeURIComponent(spec.space)}`);
    topCam = S.space.top_view ? camModel(S.space.top_view) : null;
    S.img = null;
    if (S.space.has_top) {
      const img = new Image();
      img.onload = () => { S.img = img; draw(); };
      img.src = `/api/spaces/${encodeURIComponent(S.space.name)}/top`;
    }
  }
  S.spec = spec;
  $("space-name").textContent = tr(`空間: ${S.space.title || S.space.name}（${S.space.license || ""}）`,
    `Space: ${S.space.title_en || S.space.title || S.space.name} (${S.space.license_en || S.space.license || ""})`);
  resize(); renderAll();
}
async function loadTemplate(name) {
  try { await useSpec(await api(`/api/templates/${encodeURIComponent(name)}`)); }
  catch (e) { showError($("run-msg"), tr("テンプレートを読めません: ", "Cannot load the template: ") + e.message); }
}

// ---- 計算と結果 ----
$("run").addEventListener("click", async () => {
  $("run").disabled = true; $("run-msg").textContent = tr("計算を始めます…", "Starting the simulation…");
  try {
    const { id } = await post("/api/runs", { scenario: S.spec });
    $("run-msg").textContent = tr(`計算中: ${id}`, `Running: ${id}`);
    await waitRun(id);
    switchTab("results"); await refreshRuns(); await showRun(id);
    $("run-msg").textContent = tr(`できました: ${id}`, `Done: ${id}`);
  } catch (e) { showError($("run-msg"), e.message); }
  $("run").disabled = false;
});
async function waitRun(id) {
  for (;;) {
    const r = await api(`/api/runs/${encodeURIComponent(id)}`);
    if (r.job.status === "error") throw new Error(r.job.error);
    if (r.job.status !== "running" && r.summary) return r;
    await new Promise((res) => setTimeout(res, 1000));
  }
}
async function refreshRuns() {
  let runs;
  try { runs = await api("/api/runs"); }
  catch (e) { showError($("run-detail"), tr("結果の一覧を読めません: ", "Cannot load the results: ") + e.message); return; }
  $("runs").innerHTML = runs.map((r) => `<li data-id="${esc(r.id)}" class="${r.id === S.runId ? "active" : ""}"><span>${esc(r.id)}</span>
    <span class="muted">${esc(r.status)}${r.videos.length ? tr("・動画 ", ", videos ") + r.videos.length : ""}</span></li>`).join("");
  $("runs").querySelectorAll("li").forEach((li) => li.addEventListener("click", () => showRun(li.dataset.id)));
}
$("refresh").addEventListener("click", refreshRuns);

// 2 台の間の対応の予測: 方式ごとの採点と、予測した組（○・×）の表。行の時刻を押すと予測の動画がその時刻へ飛ぶ
const fileUrl = (id, path) => `/api/runs/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}`;
const dlUrl = (id, path) => fileUrl(id, path) + "&download=1";
const dlLink = (id, path, label = tr("ダウンロード", "Download")) => `<a class="dl" href="${dlUrl(id, path)}">⬇ ${label}</a>`;
async function showRun(id) {
  S.runId = id;
  $("runs").querySelectorAll("li").forEach((li) => li.classList.toggle("active", li.dataset.id === id));
  let r;
  try { r = await api(`/api/runs/${encodeURIComponent(id)}`); }
  catch (e) { showError($("run-detail"), e.message); return; }
  const s = r.summary || {};
  const ev = s.elevator || {};
  const states = Object.entries(s.state_seconds || {}).map(([k, v]) => tr(`${esc(k)} ${Math.round(v)} 秒`, `${esc(k)} ${Math.round(v)} s`)).join(tr("・", ", "));
  const vids = r.files.filter((f) => f.startsWith("video/") && f.endsWith(".mp4"));
  const ren = r.render;
  $("run-detail").innerHTML = `
    <h3>${esc(id)}</h3>
    ${r.job?.error ? `<div class="err">${esc(r.job.error)}</div>` : ""}
    <div class="chips"><span class="chip">${tr(`${s.people ?? "-"} 人`, `${s.people ?? "-"} people`)}</span><span class="chip">${tr(`同時に最大 ${s.max_present ?? "-"} 人`, `max ${s.max_present ?? "-"} at once`)}</span>
      <span class="chip">${tr(`グループ ${s.groups ?? "-"}`, `groups ${s.groups ?? "-"}`)}</span>
      <span class="chip">${tr(`EV ${ev.arrivals ?? 0} 回・乗った ${ev.boarded ?? 0}・待ち 平均 ${ev.wait_mean_s ?? "-"} 秒`,
        `EV ${ev.arrivals ?? 0} arrivals, boarded ${ev.boarded ?? 0}, mean wait ${ev.wait_mean_s ?? "-"} s`)}</span>
      <span class="chip">${tr(`ゲート 入館 ${(s.gate_passes || {}).in ?? 0}・退館 ${(s.gate_passes || {}).out ?? 0}`,
        `gate entry ${(s.gate_passes || {}).in ?? 0}, exit ${(s.gate_passes || {}).out ?? 0}`)}</span></div>
    <div class="muted">${tr("状態ごとの時間", "Time per state")}: ${states}</div>
    <div class="row"><a class="secondary" href="/api/runs/${encodeURIComponent(id)}/zip">⬇ ${tr("結果をまとめてダウンロード（動画なし、zip）", "Download all results (without videos, zip)")}</a>
      <a class="dl" href="/api/runs/${encodeURIComponent(id)}/zip?videos=1">⬇ ${tr("動画も含める", "Include videos")}</a></div>
    ${r.files.includes("preview.png") ? `<img src="${fileUrl(id, "preview.png")}" alt="${tr("確認の図", "Check figure")}">` : ""}
    ${r.files.includes("validity.png") ? `<h3>${tr("文献との比べ（妥当性）", "Comparison with the literature (validity)")}</h3>
      <div class="muted">${tr("入力の再現（文献の分布を入れた量が崩れていないか）と、出てくる量（入れていない量が文献の範囲か）。表と根拠の台帳は",
        "Reproduction of the inputs (whether quantities given literature distributions are preserved) and the emergent quantities (whether quantities not given are within the literature ranges). The table and the ledger of sources:")}
      <a href="${fileUrl(id, "validity.md")}" target="_blank">validity.md</a></div>
      <img src="${fileUrl(id, "validity.png")}" alt="${tr("文献との比べ", "Comparison with the literature")}">` : ""}
    <h3>${tr("描画（GPU）", "Rendering (GPU)")}</h3>
    <div class="row"><button class="secondary" id="render-test">${tr("いちばん混む 5 秒を試し撮り", "Test render of the busiest 5 s")}</button>
      <button class="secondary" id="render-all">${tr("全部を描画", "Render all")}</button></div>
    <div id="render-msg" class="muted">${ren ? `${tr("描画", "Rendering")}: ${esc(ren.status)}${ren.error ? tr("・", ", ") + esc(ren.error) : ""}${ren.seconds ? tr("・", ", ") + ren.seconds + tr(" 秒", " s") : ""}` : ""}</div>
    ${vids.map((v) => `<div class="muted">${esc(v)} ${dlLink(id, v)}</div><video src="${fileUrl(id, v)}" controls muted loop preload="metadata"></video>`).join("")}
    <h3>${tr("ファイル", "Files")}</h3>
    <div class="files">${r.files.filter((f) => !f.includes("/") || f.startsWith("graph/") || f.startsWith("mot/") || f.startsWith("video/"))
      .map((f) => `<a href="${dlUrl(id, f)}">${esc(f)}</a>`).join("")}</div>`;
  $("render-test").addEventListener("click", () => doRender(id, { window: "busy", seconds: 5 }));
  $("render-all").addEventListener("click", () => doRender(id, {}));
  if (ren && ren.status === "running") pollRender(id);
}
async function doRender(id, body) {
  try {
    const url = `/api/runs/${encodeURIComponent(id)}/render`;
    const est = (await post(url, body)).estimate;
    if (!est.isaac_ready) {
      showError($("render-msg"), tr("Isaac Sim が動いていません。./isaac_up.sh で起動し、1 分ほど待ってからもう一度押してください（終わったら isim down）",
        "Isaac Sim is not running. Start it with ./isaac_up.sh, wait about 1 minute and press again (run isim down when finished)"));
      return;
    }
    const min = Math.ceil(est.estimate_s / 60);
    if (!confirm(tr(`${est.frames} コマ（${est.range[0]}〜${est.range[1]}）を描画します。目安 ${min} 分、GPU ${est.gpu}。共用の GPU なので、空きを確かめてから始めてください。始めますか？`,
      `Render ${est.frames} frames (${est.range[0]}–${est.range[1]}). About ${min} min, GPU ${est.gpu}. The GPUs are shared, so check that one is free before starting. Start?`))) return;
    await post(url, { ...body, confirm: true });
    $("render-msg").textContent = tr(`描画中（目安 ${min} 分）…`, `Rendering (about ${min} min)…`);
    pollRender(id);
  } catch (e) { showError($("render-msg"), e.message); }
}
function pollRender(id) {
  clearInterval(S.poll);
  S.poll = setInterval(async () => {
    const r = await api(`/api/runs/${encodeURIComponent(id)}`);
    if (!r.render || r.render.status === "running") return;
    clearInterval(S.poll);
    if (S.runId === id) showRun(id);
  }, 5000);
}

function switchTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  for (const t of ["settings", "results"]) $(`tab-${t}`).classList.toggle("hidden", name !== t);
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => { switchTab(b.dataset.tab); if (b.dataset.tab === "results") refreshRuns(); }));

(async function init() {
  const tpls = await api("/api/templates");
  $("template").innerHTML = tpls.map((t) => `<option value="${esc(t.name)}">${esc(tr(`${t.name}（${t.space}）`, `${t.name} (${t.space}) `))}${t.title ? "— " + esc(tr(t.title, t.title_en || t.title)) : ""}</option>`).join("");
  $("template").addEventListener("change", (e) => loadTemplate(e.target.value));
  const isaac = await api("/api/isaac");
  $("isaac").textContent = `Isaac Sim: ${isaac.ready ? tr("受け付け中", "ready") : tr("止まっている", "stopped")}`;
  $("isaac").classList.toggle("ok", isaac.ready);
  await loadTemplate(tpls.find((t) => t.name === "office_gate_ev") ? "office_gate_ev" : tpls[0].name);
  $("template").value = S.spec.name;
  try {  // 言語を切り替えたときは、編集していた設定に戻す（i18n.js）
    const saved = sessionStorage.getItem("twinsim-spec");
    if (saved) { sessionStorage.removeItem("twinsim-spec"); await useSpec(JSON.parse(saved)); }
  } catch (e) { /* 戻せなければテンプレートのまま */ }
  refreshRuns();
})();
