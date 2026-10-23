// MOPF のタブ: 状態・GPU の表・起動と停止・ライブの映像と集計（正解なら数えるはずの値と並べる）。app.js の $・api・post・fileUrl と i18n.js の tr を使う。
"use strict";

const M = { timer: null, runs: [], expected: null, visible: false, ready: false };

function gpuRows(st) {
  const own = st.own_gpus || {};
  const tag = (i) => [(own.mopf || []).includes(i) ? "MOPF" : "", (own.isaac || []).includes(i) ? "Isaac Sim" : ""].filter(Boolean).join(tr("・", ", "));
  const free = (st.gpus || []).filter((g) => g.memory_used_mib < 2000 && !tag(g.index)).map((g) => g.index);
  const pick = (own.mopf || [])[0] ?? (free.includes(3) ? 3 : free[0]);
  return `<tr><th></th><th>GPU</th><th>${tr("メモリ", "Memory")}</th><th>${tr("使用率", "Utilization")}</th><th>${tr("twinsim・MOPF", "twinsim / MOPF")}</th></tr>` + (st.gpus || []).map((g) =>
    `<tr><td><input type="radio" name="gpu" value="${g.index}" ${g.index === pick ? "checked" : ""}></td><td>${g.index}</td>
     <td class="${g.memory_used_mib >= 2000 && !tag(g.index) ? "warn" : ""}">${g.memory_used_mib} / ${g.memory_total_mib} MiB</td>
     <td>${g.util}%</td><td>${tag(g.index)}</td></tr>`).join("");
}

async function mopfRefresh() {
  try {
    const st = await api("/api/mopf/status");
    M.ready = st.ready;
    const live = st.live && st.live.status === "live";
    $("mopf-state").innerHTML = st.ready
      ? `<span class="pill ok">${tr("動いている", "Running")}</span> ${live ? tr(`ライブ（${st.live.fps ?? "-"} fps・今 ${st.live.count_now ?? "-"} 人）`, `Live (${st.live.fps ?? "-"} fps, ${st.live.count_now ?? "-"} people now)`)
        : tr("動画の処理用（カメラなし）", "For video processing (no camera)")}`
      : `<span class="pill">${tr("止まっている", "Stopped")}</span>`;
    $("mopf-open").href = st.monitor_url;
    $("gpu-table").className = "dest gpus";
    $("gpu-table").innerHTML = gpuRows(st);
    const job = st.job;
    if (job) $("mopf-log").textContent = `${job.kind}: ${job.status}${job.error ? tr("・", ", ") + job.error : ""}\n` + (job.log || []).slice(-30).join("\n");
    const want = M.visible && live ? "/api/mopf/live/stream" : "";
    if ($("live-img").dataset.src !== want) {  // 中継はつなぎ直さない（変わったときだけ）
      $("live-img").dataset.src = want;
      $("live-img").src = want;
    }
    $("live-img").classList.toggle("hidden", !live);
    return st;
  } catch (e) {
    $("mopf-state").textContent = String(e);
  }
}

async function liveRefresh() {
  if (!M.ready) { $("live-summary").textContent = tr("MOPF が止まっている（上の「選んだ動画をライブで起動」で始める）", "MOPF is stopped (start it with \"Start live with the selected video\" above)"); return; }
  try {
    const s = await api("/api/mopf/live/summary");
    if (s.status !== "live") { $("live-summary").textContent = tr("ライブではない（「選んだ動画をライブで起動」で始める）", "Not live (start with \"Start live with the selected video\")"); return; }
    const secs = Math.max(0, (s.now - s.since));
    const ex = M.expected;
    const loops = ex ? secs / ex.seconds : null;
    const exLine = (name) => ex && ex.lines.find((l) => l.name === name);
    const exZone = (name) => ex && ex.zones.find((z) => z.name === name);
    const fmt = (v) => (v == null ? "-" : (Math.round(v * 10) / 10));
    $("live-summary").innerHTML = `${tr(`集計 ${Math.round(secs)} 秒`, `Counted for ${Math.round(secs)} s`)}${ex ? tr(`（動画 ${ex.seconds} 秒の約 ${fmt(loops)} 周）`, ` (about ${fmt(loops)} loops of the ${ex.seconds} s video)`) : ""}${tr(`・今 ${s.count_now} 人`, `, ${s.count_now} people now`)}
      <table class="dest"><tr><th>${tr("線・エリア", "Line / area")}</th><th>MOPF</th><th>${tr("正解なら（この周回分）", "Ground truth (for these loops)")}</th></tr>
      ${(s.lines || []).map((l) => { const e = exLine(l.name);
        return `<tr><td>${l.name}</td><td>${l.pos_label} ${l.to_pos}${tr("・", ", ")}${l.neg_label} ${l.to_neg}</td>
          <td>${e ? `${l.pos_label} ${fmt(e.to_pos * loops)}${tr("・", ", ")}${l.neg_label} ${fmt(e.to_neg * loops)}` : "-"}</td></tr>`; }).join("")}
      ${(s.zones || []).map((z) => { const e = exZone(z.name);
        return `<tr><td>${z.name}</td><td>${tr(`今 ${z.count} 人・出た人 ${z.visits_done ?? "-"}`, `now ${z.count}, left ${z.visits_done ?? "-"}`)}</td>
          <td>${e ? tr(`入った人 ${fmt(e.people_entered * loops)}`, `entered ${fmt(e.people_entered * loops)}`) : "-"}</td></tr>`; }).join("")}</table>`;
  } catch (e) {
    $("live-summary").textContent = String(e);
  }
}

async function loadRunsForLive() {
  const runs = (await api("/api/runs")).filter((r) => r.videos.length);
  M.runs = runs;
  $("live-run").innerHTML = runs.map((r) => `<option value="${r.id}">${r.id}</option>`).join("");
  const setCams = () => {
    const r = M.runs.find((x) => x.id === $("live-run").value);
    $("live-cam").innerHTML = (r ? r.videos : []).map((v) => `<option value="${v.replace(/\.mp4$/, "")}">${v.replace(/\.mp4$/, "")}</option>`).join("");
    loadExpected();
  };
  $("live-run").onchange = setCams;
  $("live-cam").onchange = loadExpected;
  setCams();
}

async function loadExpected() {
  M.expected = null;
  const run = $("live-run").value, cam = $("live-cam").value;
  if (!run || !cam) return;
  try {
    const r = await fetch(fileUrl(run, `mopf/${cam}/expected.json`));
    if (r.ok) M.expected = await r.json();
  } catch (e) { /* まだ設定を作っていない */ }
}

function selectedGpu() {
  const g = document.querySelector('input[name="gpu"]:checked');
  return g ? Number(g.value) : null;
}

async function startMopf(live) {
  const gpu = selectedGpu();
  if (gpu == null) { alert(tr("GPU を選んでください", "Select a GPU")); return; }
  const target = live ? { run: $("live-run").value, camera: $("live-cam").value } : null;
  if (live && !(target.run && target.camera)) { alert(tr("ライブに流す動画を選んでください", "Select a video to stream live")); return; }
  const msg = live ? tr(`GPU ${gpu} で MOPF を起動し、${target.run} の ${target.camera} をライブに流します（動いている MOPF は作り直す）。`,
    `Start MOPF on GPU ${gpu} and stream ${target.camera} of ${target.run} live (a running MOPF is recreated).`)
    : tr(`GPU ${gpu} で MOPF を起動します（動画の処理用、カメラなし）。`, `Start MOPF on GPU ${gpu} (for video processing, no camera).`);
  if (!confirm(tr(`${msg}\nGPU は他の利用者と共有です。始めますか？`, `${msg}\nThe GPUs are shared with other users. Start?`))) return;
  try {
    await post("/api/mopf/start", { gpu, live: target, confirm: true });
    $("mopf-log").textContent = tr("起動中…", "Starting…");
  } catch (e) { $("mopf-log").textContent = String(e); }
}

$("mopf-refresh").addEventListener("click", mopfRefresh);
$("mopf-start").addEventListener("click", () => startMopf(false));
$("mopf-start-live").addEventListener("click", () => startMopf(true));
$("mopf-stop").addEventListener("click", async () => {
  if (!confirm(tr("MOPF を止めます（GPU を空ける）。よいですか？", "Stop MOPF (this frees the GPU). OK?"))) return;
  try { await post("/api/mopf/stop", { confirm: true }); $("mopf-log").textContent = tr("停止中…", "Stopping…"); } catch (e) { $("mopf-log").textContent = String(e); }
});
$("live-apply").addEventListener("click", async () => {
  try {
    const r = await post("/api/mopf/live/apply", { run: $("live-run").value, camera: $("live-cam").value });
    M.expected = r.expected;
    $("live-summary").textContent = tr("設定を送った", "Settings sent");
  } catch (e) { $("live-summary").textContent = String(e); }
});
$("live-reset").addEventListener("click", async () => { try { await post("/api/mopf/live/reset", {}); } catch (e) { $("live-summary").textContent = String(e); } });

// app.js の switchTab から呼ばれる。タブを開いている間だけ状態と集計を 3 秒ごとに見る（映像の中継も）
window.mopfTab = async (visible) => {
  M.visible = visible;
  clearInterval(M.timer);
  if (!visible) { $("live-img").src = ""; $("live-img").dataset.src = ""; return; }
  await loadRunsForLive();
  await mopfRefresh();
  liveRefresh();
  M.timer = setInterval(() => { mopfRefresh(); liveRefresh(); }, 3000);
};
