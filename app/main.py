# app/main.py
# FastAPI 主程式
# Phase 2 新增：
#   - /screener 篩選器頁面
#   - /api/screener 取得篩選結果 API
#   - /api/screener/trigger 手動觸發篩選
#   - /api/screener/stats 篩選統計資訊
#   - /api/stocks/list 取得全台股清單（供篩選器 dropdown 用）
#   - APScheduler 啟動/停止

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import os

from app.models.database import (
    get_db, init_db,
    StockMetrics, StockNews, WatchList, IndustryBenchmark, StockBasicInfo
)
from app.services.stock_fetcher import get_stock_data
from app.services.ai_analyzer import generate_stock_comment
from app.services.news_fetcher import fetch_google_news, fetch_mops_announcements
# Phase 2 新增
from app.services.screener import (
    get_screener_results, get_screener_stats, sync_stock_basic_info
)
from app.services.scheduler import start_scheduler, stop_scheduler, trigger_screener_now

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="台股價值投資分析系統", version="2.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def startup_event():
    init_db()
    start_scheduler()   # Phase 2：啟動定時篩選任務
    logger.info("🚀 台股分析系統啟動完成（Phase 2 篩選器已啟用）")


@app.on_event("shutdown")
async def shutdown_event():
    stop_scheduler()


# ══════════════════════════════════════════
# 頁面路由
# ══════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """個股健檢頁面（Phase 1）"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/screener", response_class=HTMLResponse)
async def screener_page(request: Request):
    """基本面篩選器頁面（Phase 2）"""
    return templates.TemplateResponse("screener.html", {"request": request})


# ══════════════════════════════════════════
# Phase 1：個股查詢 API（維持不變）
# ══════════════════════════════════════════

@app.get("/api/stock/{stock_id}")
async def get_stock_analysis(stock_id: str, db: Session = Depends(get_db)):
    """取得個股完整健檢報告（含產業基準值）"""
    logger.info(f"開始分析股票: {stock_id}")

    today = datetime.now().date()
    cached = db.query(StockMetrics).filter(
        StockMetrics.stock_id == stock_id,
        StockMetrics.date >= datetime.combine(today, datetime.min.time())
    ).first()

    if cached:
        logger.info(f"使用快取資料: {stock_id}")
        result = _format_metrics_response(cached)
        result["benchmark"] = _get_benchmark(db, cached.stock_id)
        return result

    stock_data = get_stock_data(stock_id)
    if not stock_data:
        raise HTTPException(status_code=404, detail=f"找不到股票代碼 {stock_id}，請確認代碼是否正確")

    ai_comment = generate_stock_comment(stock_data)
    stock_data["ai_comment"] = ai_comment

    metrics = StockMetrics(
        stock_id=stock_id,
        date=datetime.now(),
        price=stock_data.get("price"),
        pe_ratio=stock_data.get("pe_ratio"),
        pb_ratio=stock_data.get("pb_ratio"),
        market_cap=stock_data.get("market_cap"),
        roe=stock_data.get("roe"),
        roa=stock_data.get("roa"),
        gross_margin=stock_data.get("gross_margin"),
        net_margin=stock_data.get("net_margin"),
        debt_ratio=stock_data.get("debt_ratio"),
        current_ratio=stock_data.get("current_ratio"),
        operating_cash_flow=stock_data.get("operating_cash_flow"),
        free_cash_flow=stock_data.get("free_cash_flow"),
        f_score=stock_data.get("f_score"),
        f_score_detail=stock_data.get("f_score_detail"),
        ai_comment=ai_comment
    )
    db.add(metrics)
    db.commit()

    industry = stock_data.get("industry", "其他")
    benchmark = _get_benchmark_by_industry(db, industry)

    return {
        "stock_id": stock_id,
        "company_name": stock_data.get("company_name"),
        "industry": industry,
        "market_cap": stock_data.get("market_cap"),
        "price": stock_data.get("price"),
        "pe_ratio": stock_data.get("pe_ratio"),
        "pb_ratio": stock_data.get("pb_ratio"),
        "roe": stock_data.get("roe"),
        "roa": stock_data.get("roa"),
        "gross_margin": stock_data.get("gross_margin"),
        "net_margin": stock_data.get("net_margin"),
        "debt_ratio": stock_data.get("debt_ratio"),
        "current_ratio": stock_data.get("current_ratio"),
        "free_cash_flow": stock_data.get("free_cash_flow"),
        "revenue_trend": stock_data.get("revenue_trend"),
        "f_score": stock_data.get("f_score"),
        "f_score_detail": stock_data.get("f_score_detail"),
        "ai_comment": ai_comment,
        "benchmark": benchmark,
        "updated_at": datetime.now().isoformat()
    }


@app.get("/api/stock/{stock_id}/news")
async def get_stock_news(stock_id: str, db: Session = Depends(get_db)):
    """取得個股近期新聞"""
    today = datetime.now().date()
    cached_news = db.query(StockNews).filter(
        StockNews.stock_id == stock_id,
        StockNews.created_at >= datetime.combine(today, datetime.min.time())
    ).order_by(StockNews.published_at.desc()).limit(30).all()

    if cached_news:
        return {"news": [_format_news(n) for n in cached_news]}

    stock_info = get_stock_data(stock_id)
    company_name = stock_info.get("company_name", stock_id) if stock_info else stock_id

    news_list = fetch_google_news(stock_id, company_name, days=365)
    mops_news = fetch_mops_announcements(stock_id)
    all_news = mops_news + news_list

    for news in all_news[:50]:
        news_obj = StockNews(
            stock_id=news["stock_id"],
            title=news["title"],
            url=news["url"],
            source=news["source"],
            published_at=news["published_at"],
            is_important=news["is_important"],
            ai_summary=news.get("ai_summary")
        )
        db.add(news_obj)
    db.commit()

    return {"news": all_news[:30]}


# ══════════════════════════════════════════
# Phase 2：篩選器 API
# ══════════════════════════════════════════

@app.get("/api/screener")
async def get_screener(
    passed_only: bool = Query(True, description="只顯示通過篩選的股票"),
    industry: str = Query("全部", description="篩選特定產業"),
    sort_by: str = Query("composite_score", description="排序依據：composite_score/f_score/roe/pe_ratio/pb_ratio"),
    limit: int = Query(100, description="回傳筆數上限"),
    db: Session = Depends(get_db)
):
    """
    取得基本面篩選結果
    資料來自 screener_result 快取表（由每日排程更新）
    """
    results = get_screener_results(db, passed_only=passed_only, industry=industry, sort_by=sort_by, limit=limit)
    stats = get_screener_stats(db)

    # 取得所有產業列表（供前端 dropdown 用）
    industries = db.query(StockBasicInfo.industry).distinct().order_by(StockBasicInfo.industry).all()
    industry_list = ["全部"] + [i[0] for i in industries if i[0]]

    return {
        "results": results,
        "stats": stats,
        "industries": industry_list,
        "filters_applied": {
            "passed_only": passed_only,
            "industry": industry,
            "sort_by": sort_by,
        }
    }


@app.post("/api/screener/trigger")
async def trigger_screener(batch_size: int = Query(30, description="本次處理幾支股票（建議 20-50）")):
    """
    手動觸發一批股票篩選
    第一次使用時請先呼叫這個 API 讓系統開始跑資料
    每次約需 30-60 秒（依 batch_size 而定）
    """
    logger.info(f"手動觸發篩選，batch_size={batch_size}")
    result = trigger_screener_now(batch_size=batch_size)
    return {
        "message": f"篩選完成：處理 {result['processed']} 支，通過 {result['passed']} 支",
        **result
    }


@app.post("/api/screener/sync-stocks")
async def sync_stocks(db: Session = Depends(get_db)):
    """
    同步台股基本資料清單（stock_basic_info 表）
    第一次使用時必須先跑這個，否則篩選器沒有股票清單
    約需 10-30 秒
    """
    count = sync_stock_basic_info(db)
    total = db.query(StockBasicInfo).count()
    return {
        "message": f"同步完成，新增 {count} 筆，資料庫共 {total} 支股票"
    }


@app.get("/api/screener/stats")
async def screener_stats(db: Session = Depends(get_db)):
    """取得篩選器統計資訊"""
    stats = get_screener_stats(db)
    total_stocks = db.query(StockBasicInfo).count()
    return {**stats, "total_stocks_in_db": total_stocks}


# ══════════════════════════════════════════
# 關注清單 API（維持不變）
# ══════════════════════════════════════════

@app.get("/api/watchlist")
async def get_watchlist(db: Session = Depends(get_db)):
    items = db.query(WatchList).order_by(WatchList.added_at.desc()).all()
    return {"watchlist": [{"stock_id": i.stock_id, "added_at": i.added_at, "buy_reason": i.buy_reason} for i in items]}


@app.post("/api/watchlist/{stock_id}")
async def add_to_watchlist(stock_id: str, buy_reason: str = "", db: Session = Depends(get_db)):
    existing = db.query(WatchList).filter(WatchList.stock_id == stock_id).first()
    if existing:
        return {"message": f"{stock_id} 已在關注清單中"}
    item = WatchList(stock_id=stock_id, buy_reason=buy_reason)
    db.add(item)
    db.commit()
    return {"message": f"{stock_id} 已加入關注清單"}


@app.delete("/api/watchlist/{stock_id}")
async def remove_from_watchlist(stock_id: str, db: Session = Depends(get_db)):
    item = db.query(WatchList).filter(WatchList.stock_id == stock_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="不在關注清單中")
    db.delete(item)
    db.commit()
    return {"message": f"{stock_id} 已從關注清單移除"}


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0", "timestamp": datetime.now().isoformat()}


# ══════════════════════════════════════════
# 輔助函式
# ══════════════════════════════════════════

def _get_benchmark_by_industry(db: Session, industry: str) -> dict:
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
        "note": bm.note
    }


def _get_benchmark(db: Session, stock_id: str) -> dict:
    return {}


def _format_metrics_response(metrics: StockMetrics) -> dict:
    return {
        "stock_id": metrics.stock_id,
        "price": metrics.price,
        "pe_ratio": metrics.pe_ratio,
        "pb_ratio": metrics.pb_ratio,
        "market_cap": metrics.market_cap,
        "roe": metrics.roe,
        "roa": metrics.roa,
        "gross_margin": metrics.gross_margin,
        "net_margin": metrics.net_margin,
        "debt_ratio": metrics.debt_ratio,
        "current_ratio": metrics.current_ratio,
        "free_cash_flow": metrics.free_cash_flow,
        "f_score": metrics.f_score,
        "f_score_detail": metrics.f_score_detail,
        "ai_comment": metrics.ai_comment,
        "updated_at": metrics.updated_at.isoformat() if metrics.updated_at else None,
        "from_cache": True
    }


def _format_news(news: StockNews) -> dict:
    return {
        "title": news.title,
        "url": news.url,
        "source": news.source,
        "published_at": news.published_at.isoformat() if news.published_at else None,
        "is_important": news.is_important,
        "ai_summary": news.ai_summary
    }
