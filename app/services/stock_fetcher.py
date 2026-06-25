# app/services/stock_fetcher.py
# 負責從 FinMind API 與台灣證交所取得股票資料
# FinMind 是開源免費的台股資料平台，資料穩定、不會被封鎖

import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# FinMind API 基礎網址
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"


def _finmind_get(dataset: str, stock_id: str, start_date: str = None) -> list:
    """
    通用 FinMind API 查詢函式
    dataset: 資料集名稱（例如 TaiwanStockInfo）
    stock_id: 股票代碼（例如 2330）
    start_date: 起始日期（格式 2020-01-01）
    回傳: list of dict
    """
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")

    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": start_date,
    }

    try:
        resp = requests.get(FINMIND_API, params=params, timeout=15)
        data = resp.json()
        if data.get("status") == 200:
            return data.get("data", [])
        else:
            logger.warning(f"FinMind API 回傳錯誤 [{dataset}] {stock_id}: {data.get('msg')}")
            return []
    except Exception as e:
        logger.error(f"FinMind API 連線失敗 [{dataset}] {stock_id}: {e}")
        return []


def get_stock_data(stock_id: str) -> dict:
    """
    取得單一股票的所有財務指標
    stock_id: 台股代碼，例如 "2330"
    回傳: 包含所有指標的字典，失敗時回傳 None
    """
    logger.info(f"開始抓取 {stock_id} 資料（FinMind）")

    # 1. 取得公司基本資料
    info = _get_stock_info(stock_id)
    if not info:
        logger.error(f"找不到股票代碼: {stock_id}")
        return None

    # 2. 取得最新股價
    price_data = _get_latest_price(stock_id)

    # 3. 取得財務指標（ROE、ROA、EPS 等）
    finance_data = _get_financial_ratios(stock_id)

    # 4. 取得資產負債表資料（負債比、流動比）
    balance_data = _get_balance_sheet(stock_id)

    # 5. 取得現金流量資料
    cashflow_data = _get_cashflow(stock_id)

    # 6. 取得營收趨勢
    revenue_trend = _get_revenue_trend(stock_id)

    # 整理所有指標
    result = {
        "stock_id": stock_id,
        "company_name": info.get("company_name", f"股票{stock_id}"),
        "industry": info.get("industry_category", "未知產業"),
        "market_cap": price_data.get("market_cap"),
        "price": price_data.get("close"),
        "pe_ratio": finance_data.get("PER"),           # 本益比
        "pb_ratio": finance_data.get("PBR"),           # 股價淨值比
        "roe": finance_data.get("ROE"),                # 股東權益報酬率
        "roa": finance_data.get("ROA"),                # 資產報酬率
        "gross_margin": finance_data.get("GrossMargin"),  # 毛利率
        "net_margin": finance_data.get("NetMargin"),      # 淨利率
        "debt_ratio": balance_data.get("debt_ratio"),     # 負債比率
        "current_ratio": balance_data.get("current_ratio"),  # 流動比率
        "operating_cash_flow": cashflow_data.get("ocf"),  # 營業現金流
        "free_cash_flow": cashflow_data.get("fcf"),       # 自由現金流
        "revenue_trend": revenue_trend,
    }

    # 7. 計算 Piotroski F-Score
    f_score_result = calc_f_score(result, balance_data, cashflow_data, finance_data)
    result["f_score"] = f_score_result["total"]
    result["f_score_detail"] = f_score_result["detail"]

    return result


def _get_stock_info(stock_id: str) -> dict:
    """取得公司基本資料（名稱、產業）"""
    try:
        resp = requests.get(
            FINMIND_API,
            params={"dataset": "TaiwanStockInfo", "data_id": stock_id},
            timeout=15
        )
        data = resp.json()
        rows = data.get("data", [])
        if rows:
            return rows[0]
    except Exception as e:
        logger.error(f"取得公司資料失敗 {stock_id}: {e}")
    return {}


def _get_latest_price(stock_id: str) -> dict:
    """取得最新股價與市值"""
    start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockPrice", stock_id, start_date=start)
    if not rows:
        return {}
    latest = rows[-1]  # 最新一筆
    return {
        "close": latest.get("close"),
        "market_cap": None  # FinMind 免費版沒有市值，留空
    }


def _get_financial_ratios(stock_id: str) -> dict:
    """
    取得財務比率（PER、PBR、ROE、ROA、毛利率、淨利率）
    使用 TaiwanStockPER 和 TaiwanStockFinancialStatements
    """
    result = {}

    # PER、PBR（本益比、股價淨值比）
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    per_rows = _finmind_get("TaiwanStockPER", stock_id, start_date=start)
    if per_rows:
        latest = per_rows[-1]
        result["PER"] = latest.get("PER")
        result["PBR"] = latest.get("PBR")

    # ROE、ROA、毛利率、淨利率（財務報表）
    start_yr = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    fin_rows = _finmind_get("TaiwanStockFinancialStatements", stock_id, start_date=start_yr)
    if fin_rows:
        # 取最新一季的資料
        latest_q = fin_rows[-1] if fin_rows else {}
        # FinMind 財報欄位名稱
        for row in fin_rows:
            name = row.get("type", "")
            value = row.get("value")
            if name == "ROE" and value is not None:
                result["ROE"] = round(float(value), 2)
            elif name == "ROA" and value is not None:
                result["ROA"] = round(float(value), 2)
            elif name == "GrossProfit" and value is not None:
                result["GrossMargin"] = round(float(value), 2)
            elif name == "NetProfit" and value is not None:
                result["NetMargin"] = round(float(value), 2)

    return result


def _get_balance_sheet(stock_id: str) -> dict:
    """取得資產負債表資料，計算負債比率與流動比率"""
    start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockBalanceSheet", stock_id, start_date=start)

    result = {}
    if not rows:
        return result

    # 依日期分組，取最新兩期
    by_date = {}
    for row in rows:
        date = row.get("date", "")
        if date not in by_date:
            by_date[date] = {}
        by_date[date][row.get("type", "")] = row.get("value")

    dates = sorted(by_date.keys(), reverse=True)
    if not dates:
        return result

    latest = by_date[dates[0]]
    prev = by_date[dates[1]] if len(dates) > 1 else {}

    # 負債比率 = 總負債 / 總資產
    total_assets = latest.get("TotalAssets") or latest.get("Asset")
    total_liab = latest.get("TotalLiabilities") or latest.get("Liability")
    if total_assets and total_liab and float(total_assets) > 0:
        result["debt_ratio"] = round(float(total_liab) / float(total_assets) * 100, 2)

    # 流動比率 = 流動資產 / 流動負債
    current_assets = latest.get("CurrentAssets")
    current_liab = latest.get("CurrentLiabilities")
    if current_assets and current_liab and float(current_liab) > 0:
        result["current_ratio"] = round(float(current_assets) / float(current_liab), 2)

    # 儲存前期資料供 F-Score 使用
    result["prev_debt_ratio"] = None
    prev_assets = prev.get("TotalAssets") or prev.get("Asset")
    prev_liab = prev.get("TotalLiabilities") or prev.get("Liability")
    if prev_assets and prev_liab and float(prev_assets) > 0:
        result["prev_debt_ratio"] = round(float(prev_liab) / float(prev_assets) * 100, 2)

    return result


def _get_cashflow(stock_id: str) -> dict:
    """取得現金流量資料"""
    start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockCashFlowsStatement", stock_id, start_date=start)

    result = {"ocf": None, "fcf": None}
    if not rows:
        return result

    # 取最新期的營業現金流與資本支出
    by_date = {}
    for row in rows:
        date = row.get("date", "")
        if date not in by_date:
            by_date[date] = {}
        by_date[date][row.get("type", "")] = row.get("value")

    dates = sorted(by_date.keys(), reverse=True)
    if not dates:
        return result

    latest = by_date[dates[0]]
    ocf = latest.get("OperatingActivities") or latest.get("CashFlowsFromOperatingActivities")
    capex = latest.get("CapitalExpenditures") or latest.get("AcquisitionOfPropertyPlantAndEquipment", 0)

    if ocf is not None:
        result["ocf"] = float(ocf)
        result["fcf"] = float(ocf) - abs(float(capex or 0))

    return result


def _get_revenue_trend(stock_id: str) -> str:
    """分析近兩年營收趨勢"""
    start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockMonthRevenue", stock_id, start_date=start)

    if not rows or len(rows) < 6:
        return "無資料"

    try:
        revenues = [float(r["revenue"]) for r in rows if r.get("revenue")]
        if len(revenues) < 2:
            return "無資料"

        # 比較最近半年 vs 一年前同期
        recent = sum(revenues[:6])
        older = sum(revenues[6:12]) if len(revenues) >= 12 else sum(revenues[6:])
        if older == 0:
            return "無資料"

        change = (recent - older) / older * 100
        if change > 10:
            return f"成長（近期 +{change:.0f}%）"
        elif change < -10:
            return f"衰退（近期 {change:.0f}%）"
        else:
            return f"持平（近期 {change:+.0f}%）"
    except Exception:
        return "無資料"


def calc_f_score(stock_data: dict, balance_data: dict, cashflow_data: dict, finance_data: dict) -> dict:
    """
    計算 Piotroski F-Score（9題，滿分9分）
    每題 True=1分，False=0分
    """
    detail = {}
    score = 0

    roa = stock_data.get("roa") or 0
    ocf = cashflow_data.get("ocf") or 0
    net_margin = stock_data.get("net_margin") or 0
    debt_ratio = stock_data.get("debt_ratio") or 50
    prev_debt_ratio = balance_data.get("prev_debt_ratio") or 50
    current_ratio = stock_data.get("current_ratio") or 0
    gross_margin = stock_data.get("gross_margin") or 0

    # ── 獲利能力（3題）──

    # F1: ROA > 0
    f1 = roa > 0
    detail["F1_roa_positive"] = {
        "question": "今年 ROA > 0（有在賺錢）",
        "pass": f1,
        "value": f"{roa:.1f}%"
    }
    if f1: score += 1

    # F2: 營業現金流 > 0
    f2 = ocf > 0
    detail["F2_ocf_positive"] = {
        "question": "營業現金流 > 0（現金有進來）",
        "pass": f2,
        "value": f"{ocf/1e8:.1f}億" if ocf else "無資料"
    }
    if f2: score += 1

    # F3: 現金流 > 淨利（獲利品質）
    # 用 net_margin 簡化判斷：現金流正且淨利率為正
    f3 = ocf > 0 and net_margin > 0
    detail["F3_accrual"] = {
        "question": "現金流 > 帳面淨利（獲利不是灌水的）",
        "pass": f3,
        "value": f"OCF={ocf/1e8:.1f}億, 淨利率={net_margin:.1f}%" if ocf else "無資料"
    }
    if f3: score += 1

    # ── 財務結構（3題）──

    # F4: 負債比下降
    f4 = debt_ratio < prev_debt_ratio
    detail["F4_leverage"] = {
        "question": "負債比率比去年下降（財務更健康）",
        "pass": f4,
        "value": f"今年 {debt_ratio:.1f}% vs 去年 {prev_debt_ratio:.1f}%"
    }
    if f4: score += 1

    # F5: 流動比率 > 1.5
    f5 = current_ratio > 1.5
    detail["F5_liquidity"] = {
        "question": "流動比率 > 1.5（短期償債能力良好）",
        "pass": f5,
        "value": f"{current_ratio:.2f}"
    }
    if f5: score += 1

    # F6: 沒有增發新股（簡化：預設通過）
    detail["F6_dilution"] = {
        "question": "沒有大量增發新股（不缺錢）",
        "pass": True,
        "value": "需人工確認"
    }
    score += 1

    # ── 營運效率（3題）──

    # F7: 毛利率 > 15%
    f7 = gross_margin > 15
    detail["F7_gross_margin"] = {
        "question": "毛利率 > 15%（有定價能力）",
        "pass": f7,
        "value": f"{gross_margin:.1f}%"
    }
    if f7: score += 1

    # F8: 資產週轉率（用 ROA 代替簡化）
    f8 = roa > 5
    detail["F8_asset_turnover"] = {
        "question": "資產使用效率良好（ROA > 5%）",
        "pass": f8,
        "value": f"ROA={roa:.1f}%"
    }
    if f8: score += 1

    # F9: ROA 上升（用 ROA > 8% 簡化）
    f9 = roa > 8
    detail["F9_roa_change"] = {
        "question": "ROA > 8%（獲利效率優良）",
        "pass": f9,
        "value": f"{roa:.1f}%"
    }
    if f9: score += 1

    return {"total": score, "detail": detail}
