// app/static/js/app.js
// 前端互動邏輯：呼叫後端 API，渲染分析結果

let currentStockId = null;

// ── 快速選股 ──
function quickSearch(id) {
  document.getElementById("stockInput").value = id;
  searchStock();
}

// ── Enter 鍵觸發搜尋 ──
document.getElementById("stockInput").addEventListener("keydown", function (e) {
  if (e.key === "Enter") searchStock();
});

// ── 主搜尋函式 ──
async function searchStock() {
  const input = document.getElementById("stockInput").value.trim();
  if (!input) return;

  currentStockId = input;

  // UI 狀態切換
  show("loading");
  hide("result");
  hide("errorMsg");

  try {
    const res = await fetch(`/api/stock/${input}`);

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    renderResult(data);
    show("result");

  } catch (err) {
    document.getElementById("errorMsg").textContent =
      `❌ 查詢失敗：${err.message}`;
    show("errorMsg");
  } finally {
    hide("loading");
  }
}

// ── 渲染分析結果 ──
function renderResult(d) {
  // 公司基本資訊
  setText("companyName", d.company_name || "—");
  setText("stockId", d.stock_id);
  setText("industry", d.industry || "未知產業");
  setText("price", d.price ? `NT$ ${d.price.toFixed(2)}` : "—");
  setText("marketCap", d.market_cap ? `市值 ${d.market_cap} 億` : "");

  // 七大指標
  renderMetric("pe", d.pe_ratio, "card-pe", v => v < 15 ? "good" : v > 30 ? "bad" : "ok",
    v => v ? v.toFixed(1) : "—");
  renderMetric("pb", d.pb_ratio, "card-pb", v => v < 1.5 ? "good" : v > 3 ? "bad" : "ok",
    v => v ? v.toFixed(2) : "—");
  renderMetric("roe", d.roe, "card-roe", v => v > 15 ? "good" : v < 5 ? "bad" : "ok",
    v => v ? `${v.toFixed(1)}%` : "—");
  renderMetric("debt", d.debt_ratio, "card-debt", v => v < 40 ? "good" : v > 60 ? "bad" : "ok",
    v => v ? `${v.toFixed(1)}%` : "—");
  renderMetric("fcf", d.free_cash_flow, "card-fcf", v => v > 0 ? "good" : "bad",
    v => v ? `${(v / 1e8).toFixed(1)}億` : "—");
  setText("revTrend", d.revenue_trend || "無資料");
  renderFScoreCard(d.f_score);

  // F-Score 詳細
  renderFScoreDetail(d.f_score_detail);

  // AI 評語
  setText("aiComment", d.ai_comment || "（AI 評語載入中或未設定 API Key）");

  // 重置新聞區
  setText("newsArea", "");
  const newsBtn = document.getElementById("newsBtn");
  newsBtn.style.display = "";
  newsBtn.textContent = "載入近期新聞";
}

// ── 渲染單一指標卡 ──
function renderMetric(elemId, value, cardId, colorFn, formatFn) {
  const el = document.getElementById(elemId);
  const card = document.getElementById(cardId);
  const display = formatFn(value);
  el.textContent = display;

  if (value !== null && value !== undefined) {
    const cls = colorFn(value);
    card.className = `card metric-card ${cls}`;
  }
}

// ── F-Score 總分卡片 ──
function renderFScoreCard(score) {
  const el = document.getElementById("fscore");
  const card = document.getElementById("card-fscore");
  el.textContent = score !== null && score !== undefined ? `${score}/9` : "—";
  if (score >= 7) card.className = "card metric-card good";
  else if (score >= 4) card.className = "card metric-card ok";
  else card.className = "card metric-card bad";
}

// ── F-Score 九題詳細 ──
function renderFScoreDetail(detail) {
  const container = document.getElementById("fscoreDetail");
  if (!detail) {
    container.innerHTML = "<p style='color:var(--text-muted)'>無詳細資料</p>";
    return;
  }

  const html = Object.values(detail).map(item => `
    <div class="fscore-item ${item.pass ? 'pass' : 'fail'}">
      <span class="fscore-icon">${item.pass ? '✅' : '❌'}</span>
      <span class="fscore-q">${item.question}</span>
      <span class="fscore-val">${item.value || ''}</span>
    </div>
  `).join("");

  container.innerHTML = html;
}

// ── 載入新聞 ──
async function loadNews() {
  if (!currentStockId) return;

  const btn = document.getElementById("newsBtn");
  btn.textContent = "載入中...";
  btn.disabled = true;

  try {
    const res = await fetch(`/api/stock/${currentStockId}/news`);
    const data = await res.json();
    renderNews(data.news || []);
    btn.style.display = "none";
  } catch (err) {
    document.getElementById("newsArea").innerHTML =
      `<p style="color:var(--red)">新聞載入失敗：${err.message}</p>`;
    btn.textContent = "重試";
    btn.disabled = false;
  }
}

// ── 渲染新聞列表 ──
function renderNews(newsList) {
  const area = document.getElementById("newsArea");
  if (!newsList.length) {
    area.innerHTML = "<p style='color:var(--text-muted)'>暫無近期新聞</p>";
    return;
  }

  const html = newsList.map(n => `
    <div class="news-item ${n.is_important ? 'news-important' : ''}">
      <div class="news-title">
        ${n.is_important ? '<span class="tag-important">重要</span>' : ''}
        <a href="${n.url}" target="_blank" rel="noopener">${n.title}</a>
      </div>
      <div class="news-meta">${n.source} · ${formatDate(n.published_at)}</div>
      ${n.ai_summary ? `<div class="news-summary">🤖 ${n.ai_summary}</div>` : ''}
    </div>
  `).join("");

  area.innerHTML = html;
}

// ── 關注清單切換 ──
async function toggleWatchlist() {
  if (!currentStockId) return;
  const btn = document.getElementById("watchBtn");
  try {
    const res = await fetch(`/api/watchlist/${currentStockId}`, { method: "POST" });
    const data = await res.json();
    btn.textContent = "✅ 已加入關注清單";
    btn.style.background = "var(--green)";
    btn.style.color = "white";
    btn.style.border = "none";
  } catch (err) {
    alert("加入失敗：" + err.message);
  }
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
  return new Date(iso).toLocaleDateString("zh-TW", {
    year: "numeric", month: "2-digit", day: "2-digit"
  });
}
