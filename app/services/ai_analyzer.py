# app/services/ai_analyzer.py
# 使用 Claude API 產生 AI 評語與新聞摘要

import anthropic
import os
import logging

logger = logging.getLogger(__name__)

# 初始化 Anthropic 客戶端（從環境變數取得 API Key）
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def generate_stock_comment(stock_data: dict) -> str:
    """
    根據股票財務資料，請 Claude 產生白話文健檢評語
    stock_data: get_stock_data() 回傳的字典
    回傳: 白話文評語字串
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "（需設定 ANTHROPIC_API_KEY 才能產生 AI 評語）"

    # 整理 F-Score 細節成文字
    f_detail_text = ""
    if stock_data.get("f_score_detail"):
        for key, val in stock_data["f_score_detail"].items():
            icon = "✅" if val["pass"] else "❌"
            f_detail_text += f"{icon} {val['question']}（{val['value']}）\n"

    prompt = f"""你是一位專業的台股價值投資分析師，請用繁體中文、白話文，幫一般投資人分析以下公司的財務狀況。

公司名稱：{stock_data.get('company_name')}（{stock_data.get('stock_id')}）
產業：{stock_data.get('industry')}
目前股價：{stock_data.get('price')} 元
市值：{stock_data.get('market_cap')} 億

==== 估值指標 ====
本益比（PE）：{stock_data.get('pe_ratio')}
股價淨值比（PB）：{stock_data.get('pb_ratio')}

==== 獲利能力 ====
ROE（股東權益報酬率）：{stock_data.get('roe')}%
ROA（資產報酬率）：{stock_data.get('roa')}%
毛利率：{stock_data.get('gross_margin')}%
淨利率：{stock_data.get('net_margin')}%

==== 財務健康 ====
負債比率：{stock_data.get('debt_ratio')}%
流動比率：{stock_data.get('current_ratio')}
自由現金流：{stock_data.get('free_cash_flow')}
營收趨勢：{stock_data.get('revenue_trend')}

==== Piotroski F-Score：{stock_data.get('f_score')}/9 ====
{f_detail_text}

請依照以下結構回答，每段控制在 2-3 句：

1. **整體印象**（這間公司體質好不好？用一句話說）
2. **估值分析**（現在貴不貴？適合買嗎？）
3. **主要優點**（最值得肯定的 1-2 點）
4. **主要風險**（最需要注意的 1-2 點）
5. **結論建議**（對長期價值投資人，現在適合觀察、買進、還是等待？）

語氣要像朋友聊天，不要太學術，不要給具體買賣價格，結尾加上「以上僅供參考，投資有風險」。"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        logger.error(f"AI 評語產生失敗: {e}")
        return f"AI 評語暫時無法取得（錯誤：{str(e)[:100]}）"


def generate_news_summary(news_title: str, news_content: str, company_name: str) -> str:
    """
    請 Claude 判斷新聞重要性並產生摘要
    回傳: 摘要文字
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "（需設定 ANTHROPIC_API_KEY）"

    prompt = f"""以下是關於「{company_name}」的新聞，請用 2-3 句繁體中文說明這則新聞對公司基本面的影響：

標題：{news_title}
內容：{news_content[:500]}

請說明：這則新聞是正面、負面還是中性？會影響公司的哪個面向？"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        logger.error(f"新聞摘要產生失敗: {e}")
        return "摘要無法取得"


def classify_news_importance(title: str) -> bool:
    """
    判斷新聞是否為重要新聞（影響基本面）
    重要新聞關鍵字：財報、併購、合約、訴訟、裁員、倒閉、換CEO等
    """
    important_keywords = [
        "財報", "EPS", "獲利", "虧損", "合約", "併購", "收購",
        "訴訟", "裁員", "關廠", "停業", "執行長", "總經理", "董事長",
        "重大", "重訊", "增資", "減資", "下市", "警示"
    ]
    return any(kw in title for kw in important_keywords)
