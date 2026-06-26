# app/services/scheduler.py
# APScheduler 定時任務設定
# 功能：每日自動執行股票篩選，確保資料保持最新
#
# 設計：分批處理，避免一次爬全部導致 API 被封
# - 每天台股收盤後（16:30）執行一批（30支）
# - 同時同步一次股票基本資料清單（每週一次即可）
# - Railway 重啟不影響，offset 記在 DB，繼續接著跑

import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# 全域 offset 記錄（簡單起見放記憶體，重啟後從 0 重新跑一輪）
_current_offset = 0
_scheduler = None


def _daily_screener_job():
    """
    每日排程任務：爬一批股票並更新篩選結果
    每次處理 50 支，全台股約 1700 支，34 天跑完一輪
    """
    global _current_offset

    # 避免循環引用，在函式內 import
    from app.models.database import SessionLocal
    from app.services.screener import run_screener_batch, sync_stock_basic_info

    logger.info(f"📅 每日篩選任務開始，offset={_current_offset}")

    db = SessionLocal()
    try:
        # 每週一同步股票清單（確保新上市股票也進來）
        if datetime.now().weekday() == 0:
            logger.info("週一：同步股票基本資料清單")
            sync_stock_basic_info(db)
    finally:
        db.close()

    result = run_screener_batch(batch_size=50, offset=_current_offset)

    if result.get("done") or _current_offset + result["processed"] >= 2000:
        # 跑完一輪，重置 offset
        logger.info(f"🎉 全台股篩選完成一輪，重置 offset（本輪通過：{result['passed']}支）")
        _current_offset = 0
    else:
        _current_offset += result["processed"]
        logger.info(f"本批完成：處理 {result['processed']} 支，通過 {result['passed']} 支，下次從 offset={_current_offset} 繼續")


def _weekly_full_sync_job():
    """
    每週日執行完整同步（重置 offset 讓本週從頭跑）
    """
    global _current_offset
    _current_offset = 0
    logger.info("🔄 週日重置：下週從第一支股票重新開始篩選")


def start_scheduler():
    """
    啟動排程器
    Railway 部署時由 FastAPI startup event 呼叫
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.warning("排程器已在執行中，跳過重複啟動")
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Taipei")

    # 每個交易日 17:00 執行（收盤後抓最新資料）
    _scheduler.add_job(
        _daily_screener_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour=17,
            minute=0,
            timezone="Asia/Taipei"
        ),
        id="daily_screener",
        name="每日股票篩選",
        replace_existing=True,
        misfire_grace_time=3600  # 允許最多延遲 1 小時執行
    )

    # 每週日 02:00 重置 offset（讓下週從頭掃一遍）
    _scheduler.add_job(
        _weekly_full_sync_job,
        CronTrigger(day_of_week="sun", hour=2, minute=0, timezone="Asia/Taipei"),
        id="weekly_reset",
        name="週日重置篩選進度",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("✅ APScheduler 已啟動：每個交易日 17:00 自動篩選股票")


def stop_scheduler():
    """停止排程器（FastAPI shutdown 時呼叫）"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("排程器已停止")


def trigger_screener_now(batch_size: int = 30) -> dict:
    """
    手動觸發一批篩選（供 API 端點呼叫，讓使用者不必等排程）
    """
    global _current_offset
    from app.services.screener import run_screener_batch

    result = run_screener_batch(batch_size=batch_size, offset=_current_offset)

    if result.get("done"):
        _current_offset = 0
    else:
        _current_offset += result["processed"]

    return {**result, "current_offset": _current_offset}
