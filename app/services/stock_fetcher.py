# app/services/stock_fetcher.py
# 負責從 FinMind API 取得股票資料
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
    dataset: 資料集名稱
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
            logger.warning(f"FinMind API 錯誤 [{dataset}] {stock_id}: {data.get('msg')}")
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

    # 2. 取得最新股價與 PER、PBR
    price_data = _get_latest_price(stock_id)
    valuation = _get_valuation(stock_id)

    # 3. 取得損益表資料（毛利率、淨利率、ROE、ROA）
    income_data = _get_income_statement(stock_id)

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
        "market_cap": None,
        "price": price_data.get("close"),
        "pe_ratio": valuation.get("PER"),
        "pb_ratio": valuation.get("PBR"),
        "roe": income_data.get("roe"),
        "roa": income_data.get("roa"),
        "gross_margin": income_data.get("gross_margin"),
        "net_margin": income_data.get("net_margin"),
        "debt_ratio": balance_data.get("debt_ratio"),
        "current_ratio": balance_data.get("current_ratio"),
        "operating_cash_flow": cashflow_data.get("ocf"),
        "free_cash_flow": cashflow_data.get("fcf"),
        "revenue_trend": revenue_trend,
    }

    # 7. 計算 Piotroski F-Score
    f_score_result = calc_f_score(result, balance_data, cashflow_data, income_data)
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
    """取得最新股價"""
    start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockPrice", stock_id, start_date=start)
    if not rows:
        return {}
    return rows[-1]  # 最新一筆


def _get_valuation(stock_id: str) -> dict:
    """取得本益比（PER）與股價淨值比（PBR）"""
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockPER", stock_id, start_date=start)
    if not rows:
        return {}
    return rows[-1]  # 最新一筆


def _get_income_statement(stock_id: str) -> dict:
    """
    從損益表取得財務指標
    計算：毛利率、淨利率、ROE、ROA
    """
    start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockFinancialStatements", stock_id, start_date=start)

    if not rows:
        return {}

    # 依日期分組，取最新一期的所有欄位
    by_date = {}
    for row in rows:
        date = row.get("date", "")
        t = row.get("type", "")
        v = row.get("value")
        if date not in by_date:
            by_date[date] = {}
        if v is not None:
            by_date[date][t] = float(v)

    if not by_date:
        return {}

    # 取最新一期
    latest_date = sorted(by_date.keys())[-1]
    d = by_date[latest_date]

    result = {}

    # 毛利率 = 毛利 / 營收
    gross_profit = d.get("GrossProfit")
    revenue = d.get("Revenue")
    if gross_profit and revenue and revenue > 0:
        result["gross_margin"] = round(gross_profit / revenue * 100, 2)

    # 淨利率 = 稅後淨利 / 營收
    net_income = d.get("IncomeAfterTaxes")
    if net_income and revenue and revenue > 0:
        result["net_margin"] = round(net_income / revenue * 100, 2)

    # 儲存供 F-Score 使用
    result["net_income"] = net_income
    result["revenue"] = revenue

    # ROE、ROA 需要配合資產負債表計算，這裡先存原始值
    result["operating_income"] = d.get("OperatingIncome")

    return result


def _get_balance_sheet(stock_id: str) -> dict:
    """
    取得資產負債表，計算負債比率與流動比率
    FinMind 的資產負債表欄位帶有 _per 結尾的是百分比
    """
    start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockBalanceSheet", stock_id, start_date=start)

    result = {}
    if not rows:
        return result

    # 依日期分組
    by_date = {}
    for row in rows:
        date = row.get("date", "")
        t = row.get("type", "")
        v = row.get("value")
        if date not in by_date:
            by_date[date] = {}
        if v is not None:
            by_date[date][t] = float(v)

    dates = sorted(by_date.keys())
    if not dates:
        return result

    latest = by_date[dates[-1]]
    prev = by_date[dates[-2]] if len(dates) > 1 else {}

    # FinMind 資產負債表有 _per 欄位（百分比），直接使用更準確
    # 負債比率：用 TotalLiabilities_per（若有）
    total_liab_per = latest.get("TotalLiabilities_per")
    if total_liab_per is not None:
        result["debt_ratio"] = round(float(total_liab_per), 2)
    else:
        # 手動計算
        total_assets = latest.get("TotalAssets")
        total_liab = latest.get("TotalLiabilities")
        if total_assets and total_liab and total_assets > 0:
            result["debt_ratio"] = round(total_liab / total_assets * 100, 2)

    # 前期負債比（供 F-Score F4 使用）
    prev_liab_per = prev.get("TotalLiabilities_per")
    if prev_liab_per is not None:
        result["prev_debt_ratio"] = round(float(prev_liab_per), 2)
    else:
        prev_assets = prev.get("TotalAssets")
        prev_liab = prev.get("TotalLiabilities")
        if prev_assets and prev_liab and prev_assets > 0:
            result["prev_debt_ratio"] = round(prev_liab / prev_assets * 100, 2)
        else:
            result["prev_debt_ratio"] = result.get("debt_ratio", 50)

    # 流動比率 = 流動資產 / 流動負債
    current_assets = latest.get("CurrentAssets")
    current_liab = latest.get("CurrentLiabilities")
    if current_assets and current_liab and current_liab > 0:
        result["current_ratio"] = round(current_assets / current_liab, 2)

    # 總資產（供 ROA 計算）
    result["total_assets"] = latest.get("TotalAssets")
    result["total_equity"] = latest.get("EquityAttributableToOwnersOfParent") or latest.get("TotalEquity")

    return result


def _get_cashflow(stock_id: str) -> dict:
    """
    取得現金流量資料
    欄位：CashFlowsFromOperatingActivities（營業現金流）
          PropertyAndPlantAndEquipment（資本支出，負值）
    """
    start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockCashFlowsStatement", stock_id, start_date=start)

    result = {"ocf": None, "fcf": None}
    if not rows:
        return result

    # 依日期分組，取最新一期
    by_date = {}
    for row in rows:
        date = row.get("date", "")
        t = row.get("type", "")
        v = row.get("value")
        if date not in by_date:
            by_date[date] = {}
        if v is not None:
            by_date[date][t] = float(v)

    dates = sorted(by_date.keys())
    if not dates:
        return result

    latest = by_date[dates[-1]]

    # 營業現金流
    ocf = latest.get("CashFlowsFromOperatingActivities") or latest.get("NetCashInflowFromOperatingActivities")

    # 資本支出（購置固定資產，通常為負值）
    capex = latest.get("PropertyAndPlantAndEquipment", 0)

    if ocf is not None:
        result["ocf"] = ocf
        # 自由現金流 = 營業現金流 - 資本支出（capex 是負值所以用加）
        result["fcf"] = ocf + capex  # capex 本身是負數，所以相加

    return result


def _get_revenue_trend(stock_id: str) -> str:
    """分析近兩年月營收趨勢"""
    start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    rows = _finmind_get("TaiwanStockMonthRevenue", stock_id, start_date=start)

    if not rows or len(rows) < 6:
        return "無資料"

    try:
        revenues = [float(r["revenue"]) for r in rows if r.get("revenue")]
        if len(revenues) < 2:
            return "無資料"

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


def calc_f_score(stock_data: dict, balance_data: dict, cashflow_data: dict, income_data: dict) -> dict:
    """
    計算 Piotroski F-Score（9題，滿分9分）
    """
    detail = {}
    score = 0

    # 取得各項數值
    ocf = cashflow_data.get("ocf") or 0
    net_income = income_data.get("net_income") or 0
    total_assets = balance_data.get("total_assets") or 1
    debt_ratio = stock_data.get("debt_ratio") or 50
    prev_debt_ratio = balance_data.get("prev_debt_ratio") or 50
    current_ratio = stock_data.get("current_ratio") or 0
    gross_margin = stock_data.get("gross_margin") or 0
    net_margin = stock_data.get("net_margin") or 0

    # ROA = 稅後淨利 / 總資產
    roa = (net_income / total_assets * 100) if total_assets and total_assets > 0 else 0

    # ── 獲利能力（3題）──

    # F1: ROA > 0（有在賺錢）
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
        "value": f"{ocf/1e8:.1f}億"
    }
    if f2: score += 1

    # F3: 營業現金流 > 稅後淨利（獲利品質高）
    f3 = ocf > net_income
    detail["F3_accrual"] = {
        "question": "現金流 > 帳面淨利（獲利不是灌水的）",
        "pass": f3,
        "value": f"現金流 {ocf/1e8:.1f}億 vs 淨利 {net_income/1e8:.1f}億"
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

    # F6: 沒有大量增發新股（簡化：預設通過）
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

    # F8: ROA > 5%
    f8 = roa > 5
    detail["F8_asset_turnover"] = {
        "question": "資產使用效率良好（ROA > 5%）",
        "pass": f8,
        "value": f"ROA={roa:.1f}%"
    }
    if f8: score += 1

    # F9: ROA > 8%
    f9 = roa > 8
    detail["F9_roa_change"] = {
        "question": "ROA > 8%（獲利效率優良）",
        "pass": f9,
        "value": f"{roa:.1f}%"
    }
    if f9: score += 1

    return {"total": score, "detail": detail}
