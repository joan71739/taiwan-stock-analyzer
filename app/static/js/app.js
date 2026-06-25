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
    document.getElementById("errorMsg").textContent = `❌ 查詢失敗：${err.message}`;
    show("errorMsg");
  } finally {
    hide("loading");
  }
}

// ── 渲染分析結果 ──
function renderResult(d) {
  const bm = d.benchmark || {};  // 產業基準值

  // 公司基本資訊
  setText("companyName", d.company_name || "—");
  setText("stockId", d.stock_id);
  setText("industry", d.industry || "未知產業");
  setText("price", d.price ? `NT$ ${d.price.toFixed(2)}` : "—");
  setText("marketCap", d.market_cap ? `市值 ${d.market_cap} 億` : "");

  // 產業說明
  if (bm.note) {
    setText("industryNote", `📌 ${bm.note}`);
    show("industryNoteBox");
  } else {
    hide("industryNoteBox");
  }

  // 一句話總結
  renderSummary(d, bm);

  // 七大指標
  renderPE(d.pe_ratio, bm);
  renderPB(d.pb_ratio, bm);
  renderROE(d.roe, bm);
  renderDebt(d.debt_ratio, bm);
  renderFCF(d.free_cash_flow);
  setText("revTrend", d.revenue_trend || "無資料");
  renderFScoreCard(d.f_score);

  // F-Score 詳細
  renderFScoreDetail(d.f_score_detail);

  // AI 評語
  setText("aiComment", d.ai_comment || "（需設定 ANTHROPIC_API_KEY 才能產生 AI 評語）");

  // 重置新聞區
  setText("newsArea", "");
  const newsBtn = document.getElementById("newsBtn");
  newsBtn.style.display = "";
  newsBtn.textContent = "載入近期新聞";
}

// ── 一句話總結 ──
function renderSummary(d, bm) {
  const fscore = d.f_score || 0;
  const pe = d.pe_ratio;
  const roe = d.roe;
  const debt = d.debt_ratio;

  let quality = "";
  let price = "";
  let action = "";

  // 體質判斷
  if (fscore >= 7) quality = "體質優良";
  else if (fscore >= 4) quality = "體質普通";
  else quality = "體質較差";

  // 價格判斷
  const peHigh = bm.pe_high || 25;
  const peLow = bm.pe_low || 12;
  if (pe) {
    if (pe < peLow) price = "價格便宜";
    else if (pe > peHigh) price = "價格偏貴";
    else price = "價格合理";
  } else {
    price = "價格未知";
  }

  // 建議動作
  if (fscore >= 7 && pe && pe < peHigh) action = "✅ 值得深入研究";
  else if (fscore >= 7 && pe && pe > peHigh) action = "⏳ 好公司但現在偏貴，可以等回檔";
  else if (fscore < 4) action = "⚠️ 財務體質較弱，建議謹慎";
  else action = "👀 普通，需要再觀察";

  setText("summaryText", `${quality}・${price}　${action}`);
}

// ── PE 本益比 ──
function renderPE(pe, bm) {
  const el = document.getElementById("pe");
  const noteEl = document.getElementById("pe-note");
  const card = document.getElementById("card-pe");

  if (!pe) { el.textContent = "—"; noteEl.textContent = "無資料"; return; }

  el.textContent = pe.toFixed(1);
  const low = bm.pe_low || 12;
  const high = bm.pe_high || 25;

  if (pe < low) {
    card.className = "card metric-card good";
    noteEl.textContent = `低於${low}，本產業算便宜 👍`;
  } else if (pe > high) {
    card.className = "card metric-card bad";
    noteEl.textContent = `高於${high}，本產業算偏貴 ⚠️`;
  } else {
    card.className = "card metric-card ok";
    noteEl.textContent = `${low}~${high} 之間，本產業算合理`;
  }
}

// ── PB 股價淨值比 ──
function renderPB(pb, bm) {
  const el = document.getElementById("pb");
  const noteEl = document.getElementById("pb-note");
  const card = document.getElementById("card-pb");

  if (!pb) { el.textContent = "—"; noteEl.textContent = "無資料"; return; }

  el.textContent = pb.toFixed(2);
  const low = bm.pb_low || 1;
  const high = bm.pb_high || 3;

  if (pb < low) {
    card.className = "card metric-card good";
    noteEl.textContent = `低於${low}，股價低於帳面價值，便宜 👍`;
  } else if (pb > high) {
    card.className = "card metric-card bad";
    noteEl.textContent = `高於${high}，市場給了很高溢價，偏貴`;
  } else {
    card.className = "card metric-card ok";
    noteEl.textContent = `本產業正常範圍內`;
  }
}

// ── ROE 股東權益報酬率 ──
function renderROE(roe, bm) {
  const el = document.getElementById("roe");
  const noteEl = document.getElementById("roe-note");
  const card = document.getElementById("card-roe");

  if (!roe) { el.textContent = "—"; noteEl.textContent = "無資料"; return; }

  el.textContent = `${roe.toFixed(1)}%`;
  const good = bm.roe_good || 15;
  const min = bm.roe_min || 8;

  if (roe >= good) {
    card.className = "card metric-card good";
    noteEl.textContent = `超過${good}%，幫股東賺錢效率很好 👍`;
  } else if (roe >= min) {
    card.className = "card metric-card ok";
    noteEl.textContent = `${min}~${good}% 之間，普通`;
  } else {
    card.className = "card metric-card bad";
    noteEl.textContent = `低於${min}%，賺錢效率偏低 ⚠️`;
  }
}

// ── 負債比率 ──
function renderDebt(debt, bm) {
  const el = document.getElementById("debt");
  const noteEl = document.getElementById("debt-note");
  const card = document.getElementById("card-debt");

  if (!debt) { el.textContent = "—"; noteEl.textContent = "無資料"; return; }

  el.textContent = `${debt.toFixed(1)}%`;
  const safe = bm.debt_safe || 50;
  const danger = bm.debt_danger || 65;

  if (debt < safe) {
    card.className = "card metric-card good";
    noteEl.textContent = `低於${safe}%，財務很穩健 👍`;
  } else if (debt > danger) {
    card.className = "card metric-card bad";
    noteEl.textContent = `超過${danger}%，負債偏高需注意 ⚠️`;
  } else {
    card.className = "card metric-card ok";
    noteEl.textContent = `本產業正常範圍內`;
  }
}

// ── 自由現金流 ──
function renderFCF(fcf) {
  const el = document.getElementById("fcf");
  const noteEl = document.getElementById("fcf-note");
  const card = document.getElementById("card-fcf");

  if (fcf === null || fcf === undefined) {
    el.textContent = "—"; noteEl.textContent = "無資料"; return;
  }

  el.textContent = `${(fcf / 1e8).toFixed(1)}億`;

  if (fcf > 0) {
    card.className = "card metric-card good";
    noteEl.textContent = "正值，真的有賺到錢 👍";
  } else {
    card.className = "card metric-card bad";
    noteEl.textContent = "負值，現金在流出，需注意 ⚠️";
  }
}

// ── F-Score 總分卡片 ──
function renderFScoreCard(score) {
  const el = document.getElementById("fscore");
  const noteEl = document.getElementById("fscore-note");
  const card = document.getElementById("card-fscore");

  if (score === null || score === undefined) {
    el.textContent = "—"; return;
  }

  el.textContent = `${score}/9`;

  if (score >= 7) {
    card.className = "card metric-card good";
    noteEl.textContent = "體質優良，財報很健康 👍";
  } else if (score >= 4) {
    card.className = "card metric-card ok";
    noteEl.textContent = "體質普通，有些地方需注意";
  } else {
    card.className = "card metric-card bad";
    noteEl.textContent = "體質較差，建議避開 ⚠️";
  }
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
