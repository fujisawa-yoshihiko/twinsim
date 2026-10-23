// 画面の言葉の切り替え（日本語・英語）。index.html は日本語を既定に書き、英語を data-en（data-en-placeholder・data-en-title・data-en-alt）に持つ。
// JavaScript で作る文字は tr("日本語", "English")。選んだ言語は localStorage の twinsim-lang に残す。app.js・mopf.js より先に読む。
"use strict";

const LANG = (() => {
  try {
    const v = localStorage.getItem("twinsim-lang");
    if (v === "ja" || v === "en") return v;
  } catch (e) { /* 使えないときはブラウザの言語から */ }
  return (navigator.language || "").toLowerCase().startsWith("ja") ? "ja" : "en";
})();

function tr(ja, en) { return LANG === "en" ? en : ja; }

function applyI18n(root = document) {
  document.documentElement.lang = LANG;
  if (LANG !== "en") return;
  root.querySelectorAll("[data-en]").forEach((el) => { el.textContent = el.dataset.en; });
  for (const a of ["placeholder", "title", "alt"]) {
    root.querySelectorAll(`[data-en-${a}]`).forEach((el) => el.setAttribute(a, el.getAttribute(`data-en-${a}`)));
  }
}

// 見出しの言語の選択。変えたら残して読み直す
(function initLang() {
  applyI18n();
  const sel = document.getElementById("lang");
  if (!sel) return;
  sel.value = LANG;
  sel.addEventListener("change", () => {
    try { localStorage.setItem("twinsim-lang", sel.value); } catch (e) { /* 残せなくても読み直す */ }
    location.reload();
  });
})();
