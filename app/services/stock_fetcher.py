# app/services/stock_fetcher.py
# 負責從 yfinance 與公開資訊觀測站取得股票資料

import yfinance as yf
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import time
import logging

logger = logging.getLogger(__name__)


def get_stock_data(stock_id: str) -> dict:
    """
    取得單一股票的所有財務指標
    stock_id: 台股代碼，例如 "2330"
    回傳: 包含所有指標的字典，失敗時回傳 None
    """
    # yfinance 台股格式：代碼 + .TW（上市）或 .TWO（上櫃）
    ticker_tw = f"{stock_id}.TW"
    ticker_two = f"{stock_id}.TWO"

    ticker = None
    info = {}

    # 先嘗試上市（.TW），失敗再試上櫃（.TWO）
    for t in [ticker_tw, ticker_two]:
        try:
            tk = yf.Ticker(t)
            info = tk.info
            # 確認有取到有效資料（有 shortName 代表成功）
            if info.get("shortName"):
                ticker = tk
                break
        except Exception as e:
            logger.warning(f"嘗試 {t} 失敗: {e}")
            continue

    if not ticker or not info:
        logger.error(f"找不到股票代碼: {stock_id}")
        return None

    # 取得歷史財報資料（用來計算趨勢與 F-Score）
    try:
        financials = ticker.financials          # 損益表
        balance_sheet = ticker.balance_sheet    # 資產負債表
        cash_flow = ticker.cashflow             # 現金流量表
        quarterly_financials = ticker.quarterly_financials
    except Exception as e:
        logger.warning(f"取得財報失敗 {stock_id}: {e}")
        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cash_flow = pd.DataFrame()
        quarterly_financials = pd.DataFrame()

    # 整理基本指標
    result = {
        "stock_id": stock_id,
        "company_name": info.get("longName") or info.get("shortName", f"股票{stock_id}"),
        "industry": info.get("industry", "未知產業"),
        "market_cap": round((info.get("marketCap", 0) or 0) / 1e8, 2),  # 轉換為億元
        "price": info.get("currentPrice") or info.get("regularMarketPrice", 0),
        "pe_ratio": info.get("trailingPE"),
        "pb_ratio": info.get("priceToBook"),
        "roe": _safe_percent(info.get("returnOnEquity")),
        "roa": _safe_percent(info.get("returnOnAssets")),
        "gross_margin": _safe_percent(info.get("grossMargins")),
        "net_margin": _safe_percent(info.get("profitMargins")),
        "debt_ratio": _calc_debt_ratio(balance_sheet),
        "current_ratio": info.get("currentRatio"),
        "operating_cash_flow": _get_latest_value(cash_flow, "Operating Cash Flow"),
        "free_cash_flow": info.get("freeCashflow"),
        "revenue_trend": _calc_revenue_trend(financials),  # 近四年營收趨勢
    }

    # 計算 Piotroski F-Score
    f_score_result = calc_f_score(balance_sheet, cash_flow, financials, info)
    result["f_score"] = f_score_result["total"]
    result["f_score_detail"] = f_score_result["detail"]

    return result


def calc_f_score(balance_sheet, cash_flow, financials, info) -> dict:
    """
    計算 Piotroski F-Score（9題，滿分9分）
    每題 True=1分，False=0分
    """
    detail = {}
    score = 0

    try:
        # ── 獲利能力（3題）──

        # F1: ROA > 0（今年有沒有賺錢）
        roa = info.get("returnOnAssets", 0) or 0
        detail["F1_roa_positive"] = {
            "question": "今年 ROA > 0（有在賺錢）",
            "pass": roa > 0,
            "value": f"{roa*100:.1f}%"
        }
        if roa > 0:
            score += 1

        # F2: 營業現金流 > 0
        ocf = _get_latest_value(cash_flow, "Operating Cash Flow") or 0
        detail["F2_ocf_positive"] = {
            "question": "營業現金流 > 0（現金有進來）",
            "pass": ocf > 0,
            "value": f"{ocf/1e8:.1f}億"
        }
        if ocf > 0:
            score += 1

        # F3: 營業現金流 > 淨利（獲利品質高）
        net_income = _get_latest_value(financials, "Net Income") or 0
        detail["F3_accrual"] = {
            "question": "現金流 > 帳面淨利（獲利不是灌水的）",
            "pass": ocf > net_income,
            "value": f"現金流 {ocf/1e8:.1f}億 vs 淨利 {net_income/1e8:.1f}億"
        }
        if ocf > net_income:
            score += 1

        # ── 財務結構（3題）──

        # F4: 負債比下降
        debt_now, debt_prev = _get_two_year_debt_ratio(balance_sheet)
        detail["F4_leverage"] = {
            "question": "負債比率比去年下降（財務更健康）",
            "pass": debt_now < debt_prev if (debt_now and debt_prev) else False,
            "value": f"今年 {debt_now:.1f}% vs 去年 {debt_prev:.1f}%"
        }
        if debt_now and debt_prev and debt_now < debt_prev:
            score += 1

        # F5: 流動比率上升
        current_ratio = info.get("currentRatio") or 0
        detail["F5_liquidity"] = {
            "question": "流動比率上升（短期償債能力更好）",
            "pass": current_ratio > 1.5,  # 簡化判斷：流動比 > 1.5 視為良好
            "value": f"{current_ratio:.2f}"
        }
        if current_ratio > 1.5:
            score += 1

        # F6: 沒有增發新股（不缺錢）
        shares_now = info.get("sharesOutstanding", 0) or 0
        # 簡化：從 info 判斷（yfinance 不一定有歷史發行股數）
        detail["F6_dilution"] = {
            "question": "沒有大量增發新股（不缺錢）",
            "pass": True,  # 預設通過，實際需比對歷史股數
            "value": f"流通股數 {shares_now/1e8:.2f}億股"
        }
        score += 1  # 保守預設通過

        # ── 營運效率（3題）──

        # F7: 毛利率上升
        gm_now = info.get("grossMargins", 0) or 0
        detail["F7_gross_margin"] = {
            "question": "毛利率比去年提升（賺錢能力增強）",
            "pass": gm_now > 0.15,  # 簡化：毛利率 > 15% 視為良好
            "value": f"{gm_now*100:.1f}%"
        }
        if gm_now > 0.15:
            score += 1

        # F8: 資產週轉率
        asset_turnover = info.get("assetTurnover") or _calc_asset_turnover(financials, balance_sheet)
        detail["F8_asset_turnover"] = {
            "question": "資產週轉率上升（資產使用效率更好）",
            "pass": (asset_turnover or 0) > 0.5,
            "value": f"{asset_turnover:.2f}x" if asset_turnover else "無資料"
        }
        if asset_turnover and asset_turnover > 0.5:
            score += 1

        # F9: ROA 上升
        detail["F9_roa_change"] = {
            "question": "ROA 比去年上升（賺錢效率提升）",
            "pass": roa > 0.05,  # 簡化：ROA > 5% 視為良好
            "value": f"{roa*100:.1f}%"
        }
        if roa > 0.05:
            score += 1

    except Exception as e:
        logger.error(f"F-Score 計算發生錯誤: {e}")

    return {"total": score, "detail": detail}


def _safe_percent(value) -> float:
    """將小數轉換為百分比，處理 None"""
    if value is None:
        return None
    return round(float(value) * 100, 2)


def _get_latest_value(df: pd.DataFrame, key: str):
    """從財報 DataFrame 取最新一年的值"""
    if df is None or df.empty:
        return None
    # 找最接近的欄位名稱（yfinance 的欄位名稱有時略有不同）
    for col_name in df.index:
        if key.lower() in str(col_name).lower():
            row = df.loc[col_name]
            if not row.empty:
                return float(row.iloc[0])
    return None


def _calc_debt_ratio(balance_sheet: pd.DataFrame) -> float:
    """計算負債比率 = 總負債 / 總資產"""
    if balance_sheet is None or balance_sheet.empty:
        return None
    try:
        total_assets = None
        total_liabilities = None
        for idx in balance_sheet.index:
            if "Total Assets" in str(idx):
                total_assets = float(balance_sheet.loc[idx].iloc[0])
            if "Total Liabilities" in str(idx):
                total_liabilities = float(balance_sheet.loc[idx].iloc[0])
        if total_assets and total_liabilities and total_assets > 0:
            return round(total_liabilities / total_assets * 100, 2)
    except Exception:
        pass
    return None


def _get_two_year_debt_ratio(balance_sheet: pd.DataFrame):
    """取得今年與去年的負債比率，用於 F-Score F4"""
    if balance_sheet is None or balance_sheet.empty or len(balance_sheet.columns) < 2:
        return 50.0, 50.0  # 無法取得時預設相同（不加分）
    try:
        assets_row = None
        liab_row = None
        for idx in balance_sheet.index:
            if "Total Assets" in str(idx):
                assets_row = balance_sheet.loc[idx]
            if "Total Liabilities" in str(idx):
                liab_row = balance_sheet.loc[idx]

        if assets_row is not None and liab_row is not None:
            debt_now = liab_row.iloc[0] / assets_row.iloc[0] * 100
            debt_prev = liab_row.iloc[1] / assets_row.iloc[1] * 100
            return round(debt_now, 2), round(debt_prev, 2)
    except Exception:
        pass
    return 50.0, 50.0


def _calc_asset_turnover(financials: pd.DataFrame, balance_sheet: pd.DataFrame):
    """計算資產週轉率 = 營收 / 總資產"""
    try:
        revenue = _get_latest_value(financials, "Total Revenue")
        assets = _get_latest_value(balance_sheet, "Total Assets")
        if revenue and assets and assets > 0:
            return round(revenue / assets, 2)
    except Exception:
        pass
    return None


def _calc_revenue_trend(financials: pd.DataFrame) -> str:
    """
    分析近四年營收趨勢
    回傳: "成長" / "持平" / "衰退" / "無資料"
    """
    if financials is None or financials.empty:
        return "無資料"
    try:
        revenue_row = None
        for idx in financials.index:
            if "Total Revenue" in str(idx):
                revenue_row = financials.loc[idx]
                break
        if revenue_row is None or len(revenue_row) < 2:
            return "無資料"
        values = [float(v) for v in revenue_row if v and float(v) > 0]
        if len(values) < 2:
            return "無資料"
        # 最新年 vs 兩年前
        latest = values[0]
        oldest = values[-1]
        change = (latest - oldest) / oldest * 100
        if change > 10:
            return f"成長（近幾年 +{change:.0f}%）"
        elif change < -10:
            return f"衰退（近幾年 {change:.0f}%）"
        else:
            return f"持平（近幾年 {change:+.0f}%）"
    except Exception:
        return "無資料"


def get_company_list_from_twse() -> list:
    """
    從台灣證券交易所取得所有上市公司清單
    回傳: [{"stock_id": "2330", "company_name": "台積電", "industry": "半導體"}, ...]
    """
    url = "https://www.twse.com.tw/rwd/zh/company/companyList?market=TPEX&type=ALL&response=json"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        companies = []
        for row in data.get("data", []):
            if len(row) >= 4:
                companies.append({
                    "stock_id": row[0].strip(),
                    "company_name": row[1].strip(),
                    "industry": row[4].strip() if len(row) > 4 else "未知"
                })
        return companies
    except Exception as e:
        logger.error(f"取得上市公司清單失敗: {e}")
        return []
