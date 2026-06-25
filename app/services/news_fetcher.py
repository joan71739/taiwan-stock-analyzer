# app/services/news_fetcher.py
# 爬取 Google News RSS 取得台股相關新聞

import feedparser
import requests
from datetime import datetime, timedelta
import logging
from .ai_analyzer import classify_news_importance, generate_news_summary

logger = logging.getLogger(__name__)


def fetch_google_news(stock_id: str, company_name: str, days: int = 365 * 5) -> list:
    """
    從 Google News RSS 搜尋指定公司的新聞
    stock_id: 股票代碼（例如 2330）
    company_name: 公司名稱（例如 台積電）
    days: 搜尋幾天內的新聞（預設五年）
    回傳: 新聞列表 [{"title", "url", "published_at", "source", "is_important"}]
    """
    # Google News RSS 搜尋 URL（繁體中文台灣）
    query = f"{company_name} OR {stock_id}"
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    news_list = []
    cutoff_date = datetime.now() - timedelta(days=days)

    try:
        feed = feedparser.parse(rss_url)
        logger.info(f"取得 {company_name}({stock_id}) 新聞 {len(feed.entries)} 則")

        for entry in feed.entries:
            # 解析發布時間
            try:
                published_at = datetime(*entry.published_parsed[:6])
            except Exception:
                published_at = datetime.now()

            # 過濾太舊的新聞
            if published_at < cutoff_date:
                continue

            title = entry.get("title", "")
            url = entry.get("link", "")
            source = entry.get("source", {}).get("title", "Google News")

            is_important = classify_news_importance(title)

            news_list.append({
                "stock_id": stock_id,
                "title": title,
                "url": url,
                "source": source,
                "published_at": published_at,
                "is_important": is_important,
                "ai_summary": None  # 重要新聞的摘要稍後再產生（避免 API 爆量）
            })

        # 只對前 5 則重要新聞產生 AI 摘要（省 API 費用）
        important_news = [n for n in news_list if n["is_important"]][:5]
        for news in important_news:
            news["ai_summary"] = generate_news_summary(
                news_title=news["title"],
                news_content="",
                company_name=company_name
            )

    except Exception as e:
        logger.error(f"爬取 {company_name} 新聞失敗: {e}")

    return news_list


def fetch_mops_announcements(stock_id: str) -> list:
    """
    從公開資訊觀測站取得重大訊息
    MOPS = Market Observation Post System（公開資訊觀測站）
    """
    url = "https://mops.twse.com.tw/mops/web/ajax_t05sr01"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0"
    }
    data = {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "co_id": stock_id,
        "year": str(datetime.now().year - 1911),  # 民國年
        "month": ""
    }

    news_list = []
    try:
        resp = requests.post(url, headers=headers, data=data, timeout=15)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        # 解析重大訊息表格
        table = soup.find("table", {"class": "hasBorder"})
        if not table:
            return []

        rows = table.find_all("tr")[1:]  # 跳過標題列
        for row in rows[:20]:  # 只取最近 20 筆
            cols = row.find_all("td")
            if len(cols) < 4:
                continue
            date_str = cols[0].get_text(strip=True)
            title = cols[2].get_text(strip=True)
            link_tag = cols[2].find("a")
            url = "https://mops.twse.com.tw" + link_tag["href"] if link_tag else ""

            try:
                published_at = datetime.strptime(date_str, "%Y/%m/%d")
            except Exception:
                published_at = datetime.now()

            news_list.append({
                "stock_id": stock_id,
                "title": f"【重訊】{title}",
                "url": url,
                "source": "公開資訊觀測站",
                "published_at": published_at,
                "is_important": True,
                "ai_summary": None
            })
    except Exception as e:
        logger.warning(f"取得 MOPS 重大訊息失敗 {stock_id}: {e}")

    return news_list
