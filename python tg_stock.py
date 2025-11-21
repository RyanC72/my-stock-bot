import twstock
import yfinance as yf
import datetime
import time
from telegram.ext import ApplicationBuilder, CommandHandler
from telegram.constants import ParseMode

# ==================== CONFIG 設定區 ========================
TG_BOT_TOKEN = '8326220496:AAFVvl8wFSjaPva8EkvWhXgBQxorCrX1UJs' 
TG_CHAT_ID = '1218958685'

# 1. 台股設定
TARGET_STOCK = '0050' 
HISTORICAL_HIGH_0050 = 64.85  # 已更新為您指定的高點
BUY_ALERT_DROP_PERCENT = 0.06 

# 2. 美股定時報價清單 (可自行增加)
US_TARGET_LIST = ['SPY', 'QQQ', 'VOO']
# ============================================================

# --- 建立台股名稱對照表 ---
TW_STOCK_MAP = {}
for code in twstock.codes:
    info = twstock.codes[code]
    TW_STOCK_MAP[info.name] = code

def search_tw_code_by_name(name):
    """輸入中文名稱，回傳台股代號"""
    if name in TW_STOCK_MAP:
        return TW_STOCK_MAP[name]
    for stock_name, code in TW_STOCK_MAP.items():
        if name in stock_name:
            return code
    return None

def get_tw_stock_message(stock_code):
    """抓取台股 (顯示高低與成交量)"""
    try:
        if not stock_code.isdigit():
            found_code = search_tw_code_by_name(stock_code)
            if found_code:
                stock_code = found_code
            else:
                return None

        if datetime.datetime.today().weekday() > 4:
             pass 

        stock = twstock.realtime.get(stock_code)
        if not stock.get('success'): return None

        name = stock['info']['name']
        realtime = stock['realtime']
        
        latest = realtime['latest_trade_price']
        if latest == '-' and realtime['best_bid_price']:
             price = float(realtime['best_bid_price'][0])
        elif latest != '-':
             price = float(latest)
        else:
             return f"⚠️ {name} ({stock_code}) 目前無成交資訊。"

        open_price = float(realtime['open'])
        diff = price - open_price
        diff_percent = (diff / open_price) * 100 if open_price != 0 else 0
        
        emoji = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➖")
        sign = "+" if diff > 0 else ""

        high_price = float(realtime['high'])
        low_price = float(realtime['low'])
        volume = int(realtime['accumulate_trade_volume'])

        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        msg = (
            f"<b>🇹🇼 【{name} ({stock_code})】</b>\n"
            f"時間: {current_time}\n"
            f"--------------------\n"
            f"💰 <b>現價: {price}</b>\n"
            f"📈 漲跌: {emoji} {sign}{diff:.2f} ({sign}{diff_percent:.2f}%)\n"
            f"--------------------\n"
            f"🔥 最高: {high_price} | ❄️ 最低: {low_price}\n"
            f"📊 量: {volume} 張"
        )
        return msg
    except Exception as e:
        print(f"台股抓取錯誤: {e}")
        return None

def get_us_stock_message(ticker):
    """抓取美股 (顯示美金報價)"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # 取得價格 (優先使用 currentPrice，若無則用 regularMarketPrice)
        price = info.get('currentPrice') or info.get('regularMarketPrice')
        previous_close = info.get('previousClose')
        
        if not price or not previous_close:
            return f"⚠️ 找不到美股 <b>{ticker}</b> 資料。"

        name = info.get('shortName', ticker)

        diff = price - previous_close
        diff_percent = (diff / previous_close) * 100
        
        emoji = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➖")
        sign = "+" if diff > 0 else ""
        
        day_high = info.get('dayHigh', 0)
        day_low = info.get('dayLow', 0)
        volume = info.get('volume', 0)

        msg = (
            f"<b>🇺🇸 【{ticker.upper()} ({name})】</b>\n"
            f"--------------------\n"
            f"💰 <b>USD: {price}</b>\n"
            f"📈 漲跌: {emoji} {sign}{diff:.2f} ({sign}{diff_percent:.2f}%)\n"
            f"--------------------\n"
            f"🔥 最高: {day_high} | ❄️ 最低: {day_low}\n"
            f"📊 量: {volume:,}" 
        )
        return msg

    except Exception as e:
        print(f"美股抓取錯誤: {e}")
        return f"⚠️ 美股 {ticker} 查詢失敗。"

async def stock_command(update, context):
    """/stock 指令：自動判斷台股或美股"""
    try:
        if not context.args:
            query = TARGET_STOCK
        else:
            query = context.args[0].strip()

        await update.message.reply_text(f"🔍 查詢「{query}」中...", parse_mode=ParseMode.HTML)
        
        # 1. 先查台股
        tw_msg = get_tw_stock_message(query)
        if tw_msg:
            await update.message.reply_text(tw_msg, parse_mode=ParseMode.HTML)
        else:
            # 2. 查不到就查美股
            us_msg = get_us_stock_message(query)
            await update.message.reply_text(us_msg, parse_mode=ParseMode.HTML)
            
    except Exception as e:
        await update.message.reply_text(f"🚨 錯誤: {e}")

# --- 定時排程功能 ---

async def daily_report_job(context):
    """每日定時報價 (包含 0050 與 美股清單)"""
    chat_id = context.job.data
    
    # 1. 傳送 0050 報價
    tw_msg = get_tw_stock_message(TARGET_STOCK)
    if tw_msg:
        await context.bot.send_message(chat_id=chat_id, text=tw_msg, parse_mode=ParseMode.HTML)
    
    # 2. 傳送美股清單 (SPY, QQQ, VOO)
    for us_stock in US_TARGET_LIST:
        us_msg = get_us_stock_message(us_stock)
        if us_msg:
            await context.bot.send_message(chat_id=chat_id, text=us_msg, parse_mode=ParseMode.HTML)

async def check_buy_alert(context):
    """盤中跌幅監控 (只監控 0050)"""
    now = datetime.datetime.now()
    if now.weekday() > 4: return 
    if not (datetime.time(9, 0) <= now.time() <= datetime.time(13, 35)): return

    stock = twstock.realtime.get(TARGET_STOCK)
    if not stock.get('success'): return
    latest = stock['realtime']['latest_trade_price']
    
    if latest == '-' and stock['realtime']['best_bid_price']:
        current_price = float(stock['realtime']['best_bid_price'][0])
    elif latest != '-':
        current_price = float(latest)
    else:
        return

    drop_percent = (HISTORICAL_HIGH_0050 - current_price) / HISTORICAL_HIGH_0050
    if drop_percent >= BUY_ALERT_DROP_PERCENT:
        alert_msg = f"🔔 <b>[🚨 買入機會提醒！]</b>\n0050 已從高點 {HISTORICAL_HIGH_0050} 回檔 <b>{drop_percent*100:.1f}%</b>\n現價: {current_price}"
        await context.bot.send_message(chat_id=context.job.data, text=alert_msg, parse_mode=ParseMode.HTML)

def main():
    application = ApplicationBuilder().token(TG_BOT_TOKEN).build()
    j = application.job_queue
    
    application.add_handler(CommandHandler("stock", stock_command))
    
    # 設定定時任務：每天 12:00 和 13:30 執行 daily_report_job
    j.run_daily(daily_report_job, time=datetime.time(12, 0, 0), days=(0, 1, 2, 3, 4), data=TG_CHAT_ID)
    j.run_daily(daily_report_job, time=datetime.time(13, 30, 0), days=(0, 1, 2, 3, 4), data=TG_CHAT_ID)
    
    # 設定盤中監控
    j.run_repeating(check_buy_alert, interval=1800, first=10, data=TG_CHAT_ID)

    print(f"--- 2025 全方位股市機器人 (0050 + 美股) 啟動中 ---")
    application.run_polling()

if __name__ == '__main__':
    main()