// app/static/js/screener.js
// Phase 2：基本面篩選器前端邏輯

let allResults = [];       // 儲存所有篩選結果（供前端排序用）
let currentSortBy = "composite_score";

// ── 頁面載入時初始化 ──
window.addEventListener("DOMContentLoaded", async () => {
  await loadStats();       // 先載入統計資訊
  await loadIndustries();  // 載入產業 dropdown
  await loadResults();     // 載入篩選結果
});

// ── 載入統計資訊 ──
async function loadStats() {
  try {
    const res = await fetch("/api/screener/stats");
    const data = await res.json();
    renderStats(data);

    // 如果沒有資料，顯示初始化引導
    if (data.total_stocks_in_db === 0) {
      show("initGuide");
    }
  } catch (e) {
    console.error("載入統計資訊失敗", e);
  }
}

// ── 渲染統計列 ──
function renderStats(data) {
  const total = data.total_stocks_in_db || 0;
  const screened = data.total_screened || 0;
  const passed = data.passed_count || 0;
  const rate = data.pass_rate || 0;

  setText("statCoverage",
    total > 0
      ? `已掃描 ${screened} / ${total} 支（${Math.round(screened/total*100)}% 覆蓋率）`
      : "尚未初始化股票清單"
  );
  setText("statPassed", passed > 0 ? `通過篩選 ${passed} 支（${rate}%）` : "尚無篩選結果");
  setText("statUpdated", data.last_updated
    ? `最後更新 ${formatDate(data.last_updated)}`
    : "從未更新"
  );
}

// ── 載入產業清單到 dropdown ──
async function loadIndustries() {
  try {
    const res = await fetch("/api/screener?limit=1");
    const data = await res.json();
    const select = document.getElementById("f-industry");
    (data.industries || ["全部"]).forEach(ind => {
      const opt = document.createElement("option");
      opt.value = ind;
      opt.textContent = ind;
      select.appendChild(opt);
    });
  } catch (e) {
    console.error("載入產業清單失敗", e);
  }
}

// ── 載入篩選結果 ──
async function loadResults(passedOnly = true) {
  show("loading");
  setText("loadingMsg", "載入篩選結果中...");
  hide("resultSection");
  hide("emptyResult");

  const industry = document.getElementById("f-industry").value;
  const sortBy = document.getElementById("f-sort").value;
  currentSortBy = sortBy;

  try {
    const params = new URLSearchParams({
      passed_only: passedOnly,
      industry,
      sort_by: sortBy,
      limit: 200
    });
    const res = await fetch(`/api/screener?${params}`);
    const data = await res.json();

    allResults = data.results || [];

    if (allResults.length === 0) {
      show("emptyResult");
    } else {
      renderTable(allResults);
      show("resultSection");
    }

    renderStats(data.stats || {});
  } catch (e) {
    setText("loadingMsg", `載入失敗：${e.message}`);
  } finally {
    hide("loading");
  }
}

// ── 套用篩選（前端篩選 + 重新查詢）──
async function applyFilter() {
  const minRoe = parseFloat(document.getElementById("f-roe").value) || 0;
  const maxDebt = parseFloat(document.getElementById("f-debt").value) || 100;
  const minFScore = parseInt(document.getElementById("f-fscore").value) || 0;
  const maxPb = parseFloat(document.getElementById("f-pb").value) || 99;
  const requireFcf = document.getElementById("f-fcf").checked;

  // 先從後端拿所有「基礎通過」的結果，再前端二次篩選
  // 這樣可以讓使用者調條件不用每次等後端重算
  show("loading");
  setText("loadingMsg", "套用篩選條件中...");
  hide("resultSection");
  hide("emptyResult");

  const industry = document.getElementById("f-industry").value;
  const sortBy = document.getElementById("f-sort").value;
  currentSortBy = sortBy;

  try {
    // 拿全部資料（不過濾 passed），在前端套條件
    const params = new URLSearchParams({
      passed_only: false,   // 全部拿回來，讓前端過
      industry,
      sort_by: sortBy,
      limit: 500
    });
    const res = await fetch(`/api/screener?${params}`);
    const data = await res.json();
    const all = data.results || [];

    // 前端套條件
    allResults = all.filter(r => {
      if (r.roe != null && r.roe < minRoe) return false;
      if (r.debt_ratio != null && r.debt_ratio > maxDebt) return false;
      if (r.f_score != null && r.f_score < minFScore) return false;
      if (r.pb_ratio != null && r.pb_ratio > maxPb) return false;
      if (requireFcf && r.free_cash_flow != null && r.free_cash_flow < 0) return false;
      return true;
    });

    if (allResults.length === 0) {
      show("emptyResult");
    } else {
      renderTable(allResults);
      show("resultSection");
    }

    setText("resultTitle", `篩選結果（自訂條件）`);
    renderStats(data.stats || {});
  } catch (e) {
    console.error("篩選失敗", e);
  } finally {
    hide("loading");
  }
}

// ── 重設篩選條件 ──
function resetFilter() {
  document.getElementById("f-roe").value = 12;
  document.getElementById("f-debt").value = 60;
  document.getElementById("f-fscore").value = 6;
  document.getElementById("f-pb").value = 3;
  document.getElementById("f-fcf").checked = true;
  document.getElementById("f-industry").value = "全部";
  document.getElementById("f-sort").value = "composite_score";
  loadResults();
}

// ── 渲染結果表格 ──
function renderTable(results) {
  const tbody = document.getElementById("screenerBody");
  const sortBy = currentSortBy;

  setText("resultCount", `共 ${results.length} 支`);

  if (!results.length) {
    tbody.innerHTML = "";
    return;
  }

  tbody.innerHTML = results.map(r => {
    const fClass = r.f_score >= 7 ? "val-good" : r.f_score >= 4 ? "val-ok" : "val-bad";
    const roeClass = r.roe >= 20 ? "val-good" : r.roe >= 12 ? "val-ok" : "val-bad";
    const debtClass = r.debt_ratio <= 40 ? "val-good" : r.debt_ratio <= 60 ? "val-ok" : "val-bad";
    const fcfIcon = r.free_cash_flow > 0 ? "✅" : r.free_cash_flow < 0 ? "❌" : "—";
    const scoreBar = r.composite_score ? Math.round(r.composite_score) : 0;

    return `
    <tr class="screener-row" onclick="goToStock('${r.stock_id}')">
      <td class="stock-cell">
        <span class="stock-id">${r.stock_id}</span>
        <span class="stock-name">${r.company_name || "—"}</span>
        ${r.market === "TPEx" ? '<span class="market-tag otc">上櫃</span>' : '<span class="market-tag twse">上市</span>'}
      </td>
      <td class="industry-cell">${r.industry || "—"}</td>
      <td class="num-col">${r.pe_ratio != null ? r.pe_ratio.toFixed(1) : "—"}</td>
      <td class="num-col">${r.pb_ratio != null ? r.pb_ratio.toFixed(2) : "—"}</td>
      <td class="num-col ${roeClass}">${r.roe != null ? r.roe.toFixed(1) + "%" : "—"}</td>
      <td class="num-col ${debtClass}">${r.debt_ratio != null ? r.debt_ratio.toFixed(1) + "%" : "—"}</td>
      <td class="num-col ${fClass}">${r.f_score != null ? r.f_score + "/9" : "—"}</td>
      <td class="num-col">
        <div class="score-bar-wrap">
          <div class="score-bar" style="width:${scoreBar}%"></div>
          <span class="score-num">${scoreBar}</span>
        </div>
      </td>
      <td class="action-cell" onclick="event.stopPropagation()">
        <button class="btn-action" onclick="goToStock('${r.stock_id}')">健檢</button>
        <button class="btn-action btn-watch-small" onclick="addWatch('${r.stock_id}', '${r.company_name}')">＋關注</button>
      </td>
    </tr>`;
  }).join("");
}

// ── 前端排序 ──
function sortTable(field) {
  currentSortBy = field;
  document.getElementById("f-sort").value = field;

  const sorted = [...allResults].sort((a, b) => {
    const va = a[field] ?? -999;
    const vb = b[field] ?? -999;
    // PE、PB 越低越好（升冪）；其他越高越好（降冪）
    if (field === "pe_ratio" || field === "pb_ratio") return va - vb;
    return vb - va;
  });

  renderTable(sorted);
}

// ── 手動觸發掃描 ──
async function triggerScan(batchSize = 30) {
  const btn = document.getElementById("scanBtn");
  btn.textContent = "掃描中...";
  btn.disabled = true;

  show("loading");
  setText("loadingMsg", `正在分析 ${batchSize} 支股票，請稍候（約 30-60 秒）...`);

  try {
    const res = await fetch(`/api/screener/trigger?batch_size=${batchSize}`, { method: "POST" });
    const data = await res.json();
    alert(`✅ ${data.message}\n下一批從第 ${data.next_offset} 支開始`);
    await loadStats();
    await loadResults();
  } catch (e) {
    alert("掃描失敗：" + e.message);
  } finally {
    btn.textContent = "▶ 掃描下一批";
    btn.disabled = false;
    hide("loading");
  }
}

// ── 初始化資料（第一次使用）──
async function initData() {
  const btn = document.getElementById("initBtn");
  btn.textContent = "初始化中...";
  btn.disabled = true;

  show("loading");
  setText("loadingMsg", "正在從 FinMind 下載台股清單，約需 15-30 秒...");

  try {
    const res = await fetch("/api/screener/sync-stocks", { method: "POST" });
    const data = await res.json();
    alert(`✅ ${data.message}\n\n現在可以點「掃描下一批」開始分析股票了！`);
    hide("initGuide");
    await loadStats();
  } catch (e) {
    alert("初始化失敗：" + e.message);
  } finally {
    btn.textContent = "🔄 初始化資料";
    btn.disabled = false;
    hide("loading");
  }
}

// ── 前往個股健檢頁 ──
function goToStock(stockId) {
  // 開新分頁，保留篩選結果
  window.open(`/?stock=${stockId}`, "_blank");
}

// ── 加入關注清單 ──
async function addWatch(stockId, companyName) {
  try {
    const res = await fetch(`/api/watchlist/${stockId}`, { method: "POST" });
    const data = await res.json();
    // 用 toast 取代 alert（體驗較好）
    showToast(`⭐ ${companyName || stockId} ${data.message}`);
  } catch (e) {
    showToast("加入失敗：" + e.message, "error");
  }
}

// ── Toast 通知（輕量提示，不阻斷操作）──
function showToast(msg, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add("show"), 10);
  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ── 工具函式 ──
function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function show(id) {
  document.getElementById(id)?.classList.remove("hidden");
}

function hide(id) {
  document.getElementById(id)?.classList.add("hidden");
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-TW", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
  });
}

// ── 首頁傳入 stock 參數時自動搜尋（從篩選器點擊健檢時用）──
// 這段放在 app.js 也 OK，這裡備用
if (window.location.pathname === "/" && new URLSearchParams(location.search).get("stock")) {
  const sid = new URLSearchParams(location.search).get("stock");
  window.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("stockInput");
    if (input) {
      input.value = sid;
      searchStock();
    }
  });
}
