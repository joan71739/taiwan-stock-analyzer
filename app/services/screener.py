# app/services/screener.py
# Phase 2：基本面篩選器
# 功能：從 FinMind 抓取上市/上櫃股票清單，批次計算財務指標，篩出符合條件的公司
#
# 設計原則：
# - 不一次爬全部（太慢且容易被限速），改用「分批 + 快取」
# - 每日排程跑一批，累積幾天後就有完整資料
# - 篩選結果存進 DB，前端直接查 DB 顯示，不需等爬蟲跑完

import requests
import logging
import time
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.database import (
    SessionLocal, StockBasicInfo, StockMetrics, ScreenerResult, IndustryBenchmark
)
from app.services.stock_fetcher import get_stock_data

logger = logging.getLogger(__name__)

FINMIND_API = "https://api.finmindtrade.com/api/v4/data"

# ── 篩選門檻預設值（可透過 API 參數覆蓋）──
DEFAULT_FILTER = {
    "min_roe": 12.0,          # ROE 最低門檻（%）
    "max_debt_ratio": 60.0,   # 負債比最高門檻（%）
    "min_f_score": 6,         # F-Score 最低門檻
    "require_positive_fcf": True,  # 是否要求自由現金流為正
    "max_pe": None,           # PE 上限（None = 不限）
    "max_pb": 3.0,            # PB 上限
}

# 金融業負債比天生偏高，特殊處理
FINANCE_INDUSTRIES = {"金融業", "保險業", "銀行業"}


def fetch_all_stock_ids(market: str = "all") -> list:
    """
    從 FinMind 取得全台股代碼清單
    market: 'TWSE'（上市）、'TPEx'（上櫃）、'all'（全部）
    回傳: [{"stock_id": "2330", "company_name": "台積電", "industry_category": "半導體業", "market": "TWSE"}, ...]
    """
    try:
        resp = requests.get(
            FINMIND_API,
            params={"dataset": "TaiwanStockInfo"},
            timeout=30
        )
        data = resp.json()
        if data.get("status") != 200:
            logger.error(f"取得股票清單失敗: {data.get('msg')}")
            return []

        stocks = data.get("data", [])
        logger.info(f"FinMind 共回傳 {len(stocks)} 筆股票資料")

        # 只保留有意義的股票（4碼或5碼，排除 ETF、權證等）
        filtered = []
        for s in stocks:
            sid = str(s.get("stock_id", ""))
            # 一般股票：4位數字；部分上櫃5碼開頭是數字
            if sid.isdigit() and 4 <= len(sid) <= 5 and not sid.startswith("00"):
                filtered.append({
                    "stock_id": sid,
                    "company_name": s.get("stock_name", ""),
                    "industry": s.get("industry_category", "其他"),
                    "market": s.get("type", "TWSE")
                })

        logger.info(f"過濾後剩 {len(filtered)} 支一般股票")
        return filtered

    except Exception as e:
        logger.error(f"取得股票清單失敗: {e}")
        return []


def sync_stock_basic_info(db: Session):
    """
    同步股票基本資料到 DB
    先對來源資料去重，再用 upsert 寫入，可安全重複執行
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stocks = fetch_all_stock_ids()
    if not stocks:
        logger.warning("取得股票清單為空，跳過同步")
        return 0

    # ★ 先去重：同一個 stock_id 只保留第一筆
    seen = set()
    unique_stocks = []
    for s in stocks:
        if s["stock_id"] not in seen:
            seen.add(s["stock_id"])
            unique_stocks.append(s)

    logger.info(f"去重後剩 {len(unique_stocks)} 支（原始 {len(stocks)} 筆）")

    BATCH_SIZE = 200
    total = 0

    for i in range(0, len(unique_stocks), BATCH_SIZE):
        batch = unique_stocks[i:i + BATCH_SIZE]

        rows = [{
            "stock_id": s["stock_id"],
            "company_name": s["company_name"],
            "industry": s["industry"],
            "market": s["market"],
            "updated_at": datetime.utcnow()
        } for s in batch]

        stmt = pg_insert(StockBasicInfo).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id"],
            set_={
                "company_name": stmt.excluded.company_name,
                "industry": stmt.excluded.industry,
                "market": stmt.excluded.market,
                "updated_at": stmt.excluded.updated_at,
            }
        )
        db.execute(stmt)
        db.commit()
        total += len(batch)
        logger.info(f"同步進度：{min(i+BATCH_SIZE, len(unique_stocks))}/{len(unique_stocks)}")

    logger.info(f"✅ 股票清單同步完成，共 {total} 筆")
    return total


def run_screener_batch(batch_size: int = 30, offset: int = 0, filters: dict = None) -> dict:
    """
    執行一批篩選（每次處理 batch_size 支股票）
    offset: 從第幾支開始（用於排程分批處理）
    filters: 自訂篩選條件（None = 用預設值）
    回傳: {"processed": N, "passed": M, "next_offset": K}
    """
    f = {**DEFAULT_FILTER, **(filters or {})}
    db = SessionLocal()
    passed = 0
    processed = 0

    try:
        # 從 DB 取得股票清單（依 stock_id 排序，確保每次 offset 一致）
        stocks = db.query(StockBasicInfo).order_by(StockBasicInfo.stock_id).offset(offset).limit(batch_size).all()

        if not stocks:
            logger.info("所有股票都已處理完畢")
            return {"processed": 0, "passed": 0, "next_offset": 0, "done": True}

        logger.info(f"開始篩選第 {offset+1}～{offset+len(stocks)} 支股票")

        for stock in stocks:
            processed += 1
            sid = stock.stock_id
            industry = stock.industry

            try:
                # 先查今日快取
                today = datetime.now().date()
                cached = db.query(StockMetrics).filter(
                    StockMetrics.stock_id == sid,
                    StockMetrics.date >= datetime.combine(today, datetime.min.time())
                ).first()

                if cached:
                    metrics = _metrics_from_cache(cached)
                else:
                    # 即時抓取（每支間隔 0.5 秒避免被限速）
                    metrics = get_stock_data(sid)
                    time.sleep(0.5)

                if not metrics:
                    continue

                # 取得該產業基準值
                bm = _get_benchmark(db, industry)

                # 判斷是否通過篩選
                passed_filter, fail_reasons = _apply_filters(metrics, bm, f)

                # 計算綜合評分（用於排序）
                composite_score = _calc_composite_score(metrics)

                # 寫入篩選結果（upsert：有就更新，沒有就新增）
                existing_result = db.query(ScreenerResult).filter(
                    ScreenerResult.stock_id == sid
                ).first()

                if existing_result:
                    existing_result.passed = passed_filter
                    existing_result.fail_reasons = fail_reasons
                    existing_result.composite_score = composite_score
                    existing_result.pe_ratio = metrics.get("pe_ratio")
                    existing_result.pb_ratio = metrics.get("pb_ratio")
                    existing_result.roe = metrics.get("roe")
                    existing_result.debt_ratio = metrics.get("debt_ratio")
                    existing_result.f_score = metrics.get("f_score")
                    existing_result.free_cash_flow = metrics.get("free_cash_flow")
                    existing_result.price = metrics.get("price")
                    existing_result.revenue_trend = metrics.get("revenue_trend")
                    existing_result.updated_at = datetime.utcnow()
                else:
                    db.add(ScreenerResult(
                        stock_id=sid,
                        company_name=stock.company_name,
                        industry=industry,
                        market=stock.market,
                        passed=passed_filter,
                        fail_reasons=fail_reasons,
                        composite_score=composite_score,
                        pe_ratio=metrics.get("pe_ratio"),
                        pb_ratio=metrics.get("pb_ratio"),
                        roe=metrics.get("roe"),
                        debt_ratio=metrics.get("debt_ratio"),
                        f_score=metrics.get("f_score"),
                        free_cash_flow=metrics.get("free_cash_flow"),
                        price=metrics.get("price"),
                        revenue_trend=metrics.get("revenue_trend"),
                    ))

                if passed_filter:
                    passed += 1
                    logger.info(f"✅ {sid} {stock.company_name} 通過篩選（F={metrics.get('f_score')}, ROE={metrics.get('roe')}）")

            except Exception as e:
                logger.error(f"處理 {sid} 失敗: {e}")
                continue

        db.commit()

    except Exception as e:
        logger.error(f"批次篩選失敗: {e}")
        db.rollback()
    finally:
        db.close()

    return {
        "processed": processed,
        "passed": passed,
        "next_offset": offset + processed,
        "done": len(stocks) < batch_size
    }


def get_screener_results(
    db: Session,
    passed_only: bool = True,
    industry: str = None,
    sort_by: str = "composite_score",
    limit: int = 100
) -> list:
    """
    從 DB 讀取篩選結果
    passed_only: 只回傳通過篩選的股票
    industry: 指定產業（None = 全部）
    sort_by: 排序欄位（composite_score / f_score / roe / pe_ratio）
    """
    query = db.query(ScreenerResult)

    if passed_only:
        query = query.filter(ScreenerResult.passed == True)

    if industry and industry != "全部":
        query = query.filter(ScreenerResult.industry == industry)

    # 排序
    sort_map = {
        "composite_score": ScreenerResult.composite_score.desc(),
        "f_score": ScreenerResult.f_score.desc(),
        "roe": ScreenerResult.roe.desc(),
        "pe_ratio": ScreenerResult.pe_ratio.asc(),   # PE 越低越好
        "pb_ratio": ScreenerResult.pb_ratio.asc(),
    }
    order = sort_map.get(sort_by, ScreenerResult.composite_score.desc())
    query = query.order_by(order)

    results = query.limit(limit).all()
    return [_format_result(r) for r in results]


def get_screener_stats(db: Session) -> dict:
    """取得篩選器統計資訊（上次更新時間、覆蓋率等）"""
    total = db.query(ScreenerResult).count()
    passed = db.query(ScreenerResult).filter(ScreenerResult.passed == True).count()
    latest = db.query(ScreenerResult).order_by(ScreenerResult.updated_at.desc()).first()

    return {
        "total_screened": total,
        "passed_count": passed,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "last_updated": latest.updated_at.isoformat() if latest else None,
    }


# ── 內部輔助函式 ──

def _apply_filters(metrics: dict, benchmark: dict, f: dict) -> tuple:
    """
    套用篩選條件，回傳 (是否通過, 失敗原因列表)
    金融業負債比特殊處理
    """
    fail_reasons = []
    industry = metrics.get("industry", "")

    roe = metrics.get("roe")
    debt = metrics.get("debt_ratio")
    f_score = metrics.get("f_score")
    fcf = metrics.get("free_cash_flow")
    pb = metrics.get("pb_ratio")
    pe = metrics.get("pe_ratio")

    # ROE 門檻
    if roe is None:
        fail_reasons.append("ROE 無資料")
    elif roe < f["min_roe"]:
        fail_reasons.append(f"ROE={roe:.1f}% 低於門檻{f['min_roe']}%")

    # 負債比（金融業跳過此項）
    if industry not in FINANCE_INDUSTRIES:
        if debt is None:
            fail_reasons.append("負債比無資料")
        elif debt > f["max_debt_ratio"]:
            fail_reasons.append(f"負債比={debt:.1f}% 超過{f['max_debt_ratio']}%")

    # F-Score
    if f_score is None:
        fail_reasons.append("F-Score 無資料")
    elif f_score < f["min_f_score"]:
        fail_reasons.append(f"F-Score={f_score} 低於門檻{f['min_f_score']}")

    # 自由現金流（選擇性）
    if f["require_positive_fcf"] and fcf is not None and fcf < 0:
        fail_reasons.append(f"自由現金流為負({fcf/1e8:.1f}億)")

    # PB 上限
    if f["max_pb"] and pb is not None and pb > f["max_pb"]:
        fail_reasons.append(f"PB={pb:.2f} 超過上限{f['max_pb']}")

    # PE 上限（選擇性）
    if f["max_pe"] and pe is not None and pe > f["max_pe"]:
        fail_reasons.append(f"PE={pe:.1f} 超過上限{f['max_pe']}")

    return len(fail_reasons) == 0, "|".join(fail_reasons)


def _calc_composite_score(metrics: dict) -> float:
    """
    計算綜合評分（0-100），用於排序
    加權考量：F-Score（40%）、ROE（30%）、低負債（20%）、低PE（10%）
    """
    score = 0.0

    # F-Score（滿分9）→ 佔 40 分
    f = metrics.get("f_score") or 0
    score += (f / 9) * 40

    # ROE（>25% 滿分）→ 佔 30 分
    roe = metrics.get("roe") or 0
    score += min(roe / 25, 1.0) * 30

    # 負債比（<30% 滿分，>70% 0分）→ 佔 20 分
    debt = metrics.get("debt_ratio") or 50
    score += max(0, (70 - debt) / 40) * 20

    # PE（<15 滿分，>40 0分）→ 佔 10 分
    pe = metrics.get("pe_ratio")
    if pe and pe > 0:
        score += max(0, (40 - pe) / 25) * 10

    return round(score, 2)


def _get_benchmark(db: Session, industry: str) -> dict:
    """取得產業基準值"""
    bm = db.query(IndustryBenchmark).filter(IndustryBenchmark.industry == industry).first()
    if not bm:
        bm = db.query(IndustryBenchmark).filter(IndustryBenchmark.industry == "其他").first()
    if not bm:
        return {}
    return {
        "pe_low": bm.pe_low, "pe_high": bm.pe_high,
        "pb_low": bm.pb_low, "pb_high": bm.pb_high,
        "roe_good": bm.roe_good, "roe_min": bm.roe_min,
        "debt_safe": bm.debt_safe, "debt_danger": bm.debt_danger,
    }


def _metrics_from_cache(cached) -> dict:
    """從 StockMetrics 快取物件轉為 dict"""
    return {
        "stock_id": cached.stock_id,
        "price": cached.price,
        "pe_ratio": cached.pe_ratio,
        "pb_ratio": cached.pb_ratio,
        "roe": cached.roe,
        "roa": cached.roa,
        "debt_ratio": cached.debt_ratio,
        "f_score": cached.f_score,
        "free_cash_flow": cached.free_cash_flow,
    }


def _format_result(r: ScreenerResult) -> dict:
    """將 ScreenerResult ORM 物件轉為 API 回傳用 dict"""
    return {
        "stock_id": r.stock_id,
        "company_name": r.company_name,
        "industry": r.industry,
        "market": r.market,
        "price": r.price,
        "pe_ratio": r.pe_ratio,
        "pb_ratio": r.pb_ratio,
        "roe": r.roe,
        "debt_ratio": r.debt_ratio,
        "f_score": r.f_score,
        "free_cash_flow": r.free_cash_flow,
        "revenue_trend": r.revenue_trend,
        "composite_score": r.composite_score,
        "fail_reasons": r.fail_reasons,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
