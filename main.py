# main.py（根目錄，Railway 的啟動入口）
# 這個檔案放在專案根目錄，Railway 會從這裡啟動

from app.main import app  # noqa: F401（引入 FastAPI app 實例）

# 直接執行時使用（本機測試用）
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
