# app/models/database.py
# 資料庫連線設定與資料表定義

import os
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    DateTime, Boolean, Text, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# 從環境變數取得資料庫 URL（Railway 會自動注入）
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dev.db")

# Railway 的 PostgreSQL URL 有時以 postgres:// 開頭，需換成 postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 建立資料庫引擎
engine = create_engine(DATABASE_URL)

# 建立 Session 工廠
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 所有 Model 的基底類別
Base = declarative_base()


class StockBasicInfo(Base):
    """公司基本資料表"""
    __tablename__ = "stock_basic_info"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), unique=True, index=True)  # 股票代碼，例如 2330
    company_name = Column(String(100))                       # 公司名稱
    industry = Column(String(50))                            # 產業別
    market = Column(String(20))                              # 上市/上櫃
    updated_at = Column(DateTime, default=datetime.utcnow)


class StockMetrics(Base):
    """股票財務指標快照表（每日更新）"""
    __tablename__ = "stock_metrics"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    date = Column(DateTime, default=datetime.utcnow)

    # 股價與估值
    price = Column(Float)            # 現在股價
    pe_ratio = Column(Float)         # 本益比
    pb_ratio = Column(Float)         # 股價淨值比
    market_cap = Column(Float)       # 市值（億）

    # 獲利能力
    roe = Column(Float)              # 股東權益報酬率 %
    roa = Column(Float)              # 資產報酬率 %
    gross_margin = Column(Float)     # 毛利率 %
    net_margin = Column(Float)       # 淨利率 %

    # 財務結構
    debt_ratio = Column(Float)       # 負債比率 %
    current_ratio = Column(Float)    # 流動比率

    # 現金流
    operating_cash_flow = Column(Float)  # 營業現金流
    free_cash_flow = Column(Float)       # 自由現金流

    # F-Score
    f_score = Column(Integer)        # Piotroski F-Score 總分 (0-9)
    f_score_detail = Column(JSON)    # 九題逐條結果

    # AI 評語
    ai_comment = Column(Text)        # Claude 產生的白話文評語

    updated_at = Column(DateTime, default=datetime.utcnow)


class StockNews(Base):
    """公司新聞表"""
    __tablename__ = "stock_news"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    title = Column(String(500))       # 新聞標題
    url = Column(String(1000))        # 新聞連結
    source = Column(String(100))      # 來源（Yahoo、Google News 等）
    published_at = Column(DateTime)   # 發布時間
    is_important = Column(Boolean, default=False)  # 是否為重要新聞
    ai_summary = Column(Text)         # AI 摘要（重要新聞才有）
    created_at = Column(DateTime, default=datetime.utcnow)


class WatchList(Base):
    """關注清單（使用者自訂）"""
    __tablename__ = "watch_list"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    buy_reason = Column(Text)         # 當初加入的理由，用於持股監控判斷


def get_db():
    """取得資料庫 Session（FastAPI 依賴注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化資料庫，建立所有資料表"""
    Base.metadata.create_all(bind=engine)
    print("✅ 資料庫初始化完成")
