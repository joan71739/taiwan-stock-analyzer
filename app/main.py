# app/main.py
# FastAPI 主程式

from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import os

from app.models.database import get_db, init_db, StockMetrics, StockNews, WatchList, IndustryBenchmark
from app.services.stock_fetcher import get_stock_data
from app.services.ai_analyzer import generate_stock_comment
from app.services.news_fetcher import fetch_google_news, fetch_mops_announcements

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="台股價值投資分析系統", version="1.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def startup_event():
    init_db()
    logger.info("🚀 台股分析系統啟動完成")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/stock/{stock_id}")
async def get_stock_analysis(stock_id: str, db: Session = Depends(get_db)):
    """取得個股完整健檢報告（含產業基準值）"""
    logger.info(f"開始分析股票: {stock_id}")

    # 先查今日快取
    today = datetime.now().date()
    cached = db.query(StockMetrics).filter(
        StockMetrics.stock_id == stock_id,
        StockMetrics.date >= datetime.combine(today, datetime.min.time())
    ).first()

    if cached:
        logger.info(f"使用快取資料: {stock_id}")
        result = _format_metrics_response(cached)
        # 快取也要附上產業基準值
        result["benchmark"] = _get_benchmark(db, cached.stock_id)
        return result

    # 即時爬取
    stock_data = get_stock_data(stock_id)
    if not stock_data:
        raise HTTPException(status_code=404, detail=f"找不到股票代碼 {stock_id}，請確認代碼是否正確")

    # AI 評語
    ai_comment = generate_stock_comment(stock_data)
    stock_data["ai_comment"] = ai_comment

    # 存入資料庫
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

    # 取得產業基準值
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
        "benchmark": benchmark,  # 產業基準值
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
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ── 輔助函式 ──

def _get_benchmark_by_industry(db: Session, industry: str) -> dict:
    """從 DB 取得產業基準值，找不到則用「其他」"""
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
    """從快取的 stock_id 查產業基準值（需要先查產業別）"""
    # 簡化：直接回傳空，快取的資料下次查詢時會重新帶入
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
