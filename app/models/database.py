# app/models/database.py
# 資料庫連線設定與資料表定義

import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# 從環境變數取得資料庫 URL（Railway 會自動注入）
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dev.db")

# Railway 的 PostgreSQL URL 有時以 postgres:// 開頭，需換成 postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class StockBasicInfo(Base):
    """公司基本資料表"""
    __tablename__ = "stock_basic_info"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), unique=True, index=True)
    company_name = Column(String(100))
    industry = Column(String(50))
    market = Column(String(20))
    updated_at = Column(DateTime, default=datetime.utcnow)


class StockMetrics(Base):
    """股票財務指標快照表（每日更新）"""
    __tablename__ = "stock_metrics"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    date = Column(DateTime, default=datetime.utcnow)
    price = Column(Float)
    pe_ratio = Column(Float)
    pb_ratio = Column(Float)
    market_cap = Column(Float)
    roe = Column(Float)
    roa = Column(Float)
    gross_margin = Column(Float)
    net_margin = Column(Float)
    debt_ratio = Column(Float)
    current_ratio = Column(Float)
    operating_cash_flow = Column(Float)
    free_cash_flow = Column(Float)
    f_score = Column(Integer)
    f_score_detail = Column(JSON)
    ai_comment = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow)


class StockNews(Base):
    """公司新聞表"""
    __tablename__ = "stock_news"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    title = Column(String(500))
    url = Column(String(1000))
    source = Column(String(100))
    published_at = Column(DateTime)
    is_important = Column(Boolean, default=False)
    ai_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class WatchList(Base):
    """關注清單"""
    __tablename__ = "watch_list"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    buy_reason = Column(Text)


class IndustryBenchmark(Base):
    """
    產業基準值資料表
    儲存各產業的財務指標正常範圍，供比較判斷用
    之後想調整門檻，直接修改 DB 即可，不需要改程式碼
    """
    __tablename__ = "industry_benchmark"

    id = Column(Integer, primary_key=True, index=True)
    industry = Column(String(100), unique=True, index=True)  # 產業名稱

    # 本益比正常範圍
    pe_low = Column(Float)   # PE 低於此值 = 便宜
    pe_high = Column(Float)  # PE 高於此值 = 偏貴

    # 股價淨值比正常範圍
    pb_low = Column(Float)
    pb_high = Column(Float)

    # ROE 門檻
    roe_good = Column(Float)   # ROE 高於此值 = 良好
    roe_min = Column(Float)    # ROE 低於此值 = 偏低

    # 負債比警戒線
    debt_safe = Column(Float)    # 負債比低於此值 = 安全
    debt_danger = Column(Float)  # 負債比高於此值 = 危險

    # 產業說明（白話文）
    note = Column(Text)

    updated_at = Column(DateTime, default=datetime.utcnow)


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
    _seed_industry_benchmarks()


def _seed_industry_benchmarks():
    """
    寫入產業基準值預設資料
    只在資料表是空的時候執行（避免重複寫入）
    """
    db = SessionLocal()
    try:
        # 如果已經有資料，跳過
        if db.query(IndustryBenchmark).count() > 0:
            return

        benchmarks = [
            IndustryBenchmark(
                industry="半導體業",
                pe_low=15, pe_high=30,
                pb_low=2, pb_high=6,
                roe_good=20, roe_min=10,
                debt_safe=40, debt_danger=60,
                note="台灣最重要的產業，台積電、聯發科等。本益比普遍較高因為成長性強，負債比相對低較健康。"
            ),
            IndustryBenchmark(
                industry="電子零組件業",
                pe_low=10, pe_high=20,
                pb_low=1, pb_high=3,
                roe_good=15, roe_min=8,
                debt_safe=45, debt_danger=65,
                note="鴻海、日月光等。競爭激烈、毛利率偏低，PE 通常不高。"
            ),
            IndustryBenchmark(
                industry="其他電子業",
                pe_low=12, pe_high=25,
                pb_low=1, pb_high=3,
                roe_good=15, roe_min=8,
                debt_safe=45, debt_danger=65,
                note="電子相關產業，標準與一般電子業相近。"
            ),
            IndustryBenchmark(
                industry="光電業",
                pe_low=10, pe_high=20,
                pb_low=1, pb_high=2,
                roe_good=12, roe_min=6,
                debt_safe=50, debt_danger=70,
                note="面板、LED 等，景氣循環明顯，PE 和毛利率普遍偏低。"
            ),
            IndustryBenchmark(
                industry="生技醫療業",
                pe_low=30, pe_high=80,
                pb_low=3, pb_high=10,
                roe_good=15, roe_min=5,
                debt_safe=40, debt_danger=60,
                note="新藥研發期間可能長期虧損，PE 偏高甚至無意義。重點看研發管線與現金是否足夠。"
            ),
            IndustryBenchmark(
                industry="化學生技醫療",
                pe_low=20, pe_high=50,
                pb_low=2, pb_high=6,
                roe_good=12, roe_min=5,
                debt_safe=45, debt_danger=65,
                note="包含化學與生技，標準介於兩者之間。"
            ),
            IndustryBenchmark(
                industry="金融業",
                pe_low=8, pe_high=15,
                pb_low=0.8, pb_high=2,
                roe_good=12, roe_min=8,
                debt_safe=92, debt_danger=96,
                note="銀行、保險、券商。因為吸收存款，負債比天生很高（90%以上是正常的），不能用一般標準判斷。"
            ),
            IndustryBenchmark(
                industry="保險業",
                pe_low=8, pe_high=15,
                pb_low=0.8, pb_high=2,
                roe_good=10, roe_min=6,
                debt_safe=92, debt_danger=96,
                note="保險公司負債比極高是正常現象（保費收入算負債），需用特殊標準評估。"
            ),
            IndustryBenchmark(
                industry="塑膠工業",
                pe_low=8, pe_high=18,
                pb_low=0.8, pb_high=2,
                roe_good=12, roe_min=6,
                debt_safe=50, debt_danger=65,
                note="台塑集團等傳統產業。景氣循環性強，原料價格影響大。"
            ),
            IndustryBenchmark(
                industry="化學工業",
                pe_low=8, pe_high=18,
                pb_low=0.8, pb_high=2,
                roe_good=12, roe_min=6,
                debt_safe=50, debt_danger=65,
                note="傳統化工產業，景氣循環明顯。"
            ),
            IndustryBenchmark(
                industry="鋼鐵工業",
                pe_low=6, pe_high=15,
                pb_low=0.5, pb_high=1.5,
                roe_good=10, roe_min=5,
                debt_safe=55, debt_danger=70,
                note="中鋼等。強烈景氣循環，虧損年份 PE 無意義，看 PB 更重要。"
            ),
            IndustryBenchmark(
                industry="水泥工業",
                pe_low=8, pe_high=18,
                pb_low=0.8, pb_high=2,
                roe_good=10, roe_min=5,
                debt_safe=50, debt_danger=65,
                note="台泥、亞泥等。穩定但成長性低，適合看股息殖利率。"
            ),
            IndustryBenchmark(
                industry="建材營造",
                pe_low=8, pe_high=20,
                pb_low=0.8, pb_high=2,
                roe_good=12, roe_min=6,
                debt_safe=55, debt_danger=70,
                note="房地產相關，受政策與景氣影響大。"
            ),
            IndustryBenchmark(
                industry="食品工業",
                pe_low=15, pe_high=30,
                pb_low=1.5, pb_high=4,
                roe_good=15, roe_min=8,
                debt_safe=50, debt_danger=65,
                note="統一、味全等民生必需品。景氣穩定，PE 相對高，品牌價值重要。"
            ),
            IndustryBenchmark(
                industry="紡織纖維",
                pe_low=8, pe_high=18,
                pb_low=0.8, pb_high=2,
                roe_good=10, roe_min=5,
                debt_safe=50, debt_danger=65,
                note="傳統產業，成長性低，注重股息。"
            ),
            IndustryBenchmark(
                industry="電機機械",
                pe_low=10, pe_high=22,
                pb_low=1, pb_high=3,
                roe_good=12, roe_min=7,
                debt_safe=50, debt_danger=65,
                note="工具機、馬達等。景氣循環性強。"
            ),
            IndustryBenchmark(
                industry="汽車工業",
                pe_low=8, pe_high=18,
                pb_low=0.8, pb_high=2,
                roe_good=10, roe_min=5,
                debt_safe=55, debt_danger=70,
                note="裕隆、和泰等。台灣汽車業規模小，PE 通常偏低。"
            ),
            IndustryBenchmark(
                industry="油電燃氣業",
                pe_low=8, pe_high=18,
                pb_low=0.8, pb_high=2,
                roe_good=8, roe_min=4,
                debt_safe=60, debt_danger=75,
                note="中油、台電相關。公用事業，穩定但成長性低，負債比偏高是正常的。"
            ),
            IndustryBenchmark(
                industry="電信業",
                pe_low=15, pe_high=25,
                pb_low=1.5, pb_high=3,
                roe_good=12, roe_min=8,
                debt_safe=55, debt_danger=70,
                note="中華電、台哥大等。穩定配息，PE 相對合理，看股息殖利率很重要。"
            ),
            IndustryBenchmark(
                industry="觀光餐旅",
                pe_low=15, pe_high=35,
                pb_low=1, pb_high=3,
                roe_good=10, roe_min=5,
                debt_safe=55, debt_danger=70,
                note="受景氣與疫情影響大，獲利波動明顯。"
            ),
            IndustryBenchmark(
                industry="數位雲端",
                pe_low=20, pe_high=50,
                pb_low=3, pb_high=10,
                roe_good=15, roe_min=8,
                debt_safe=40, debt_danger=60,
                note="軟體、雲端服務等新興產業，成長性高所以 PE 偏高是合理的。"
            ),
            IndustryBenchmark(
                industry="其他",
                pe_low=12, pe_high=25,
                pb_low=1, pb_high=3,
                roe_good=12, roe_min=6,
                debt_safe=50, debt_danger=65,
                note="其他產業，使用通用標準判斷。"
            ),
        ]

        for b in benchmarks:
            db.add(b)
        db.commit()
        print(f"✅ 產業基準值寫入完成，共 {len(benchmarks)} 個產業")

    except Exception as e:
        print(f"❌ 產業基準值寫入失敗: {e}")
        db.rollback()
    finally:
        db.close()
