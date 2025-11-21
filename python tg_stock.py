import twstock
import yfinance as yf
import datetime
import time
import threading
from flask import Flask # 偽裝成網站的工具
from telegram.ext import ApplicationBuilder, CommandHandler
from telegram.constants import ParseMode

# ==================== CONFIG 設定區 ========================
TG_BOT_TOKEN = '8326220496:AAFVvl8wFSjaPva8EkvWhXgBQxorCrX1UJs' 

# 多人設定
TG_CHAT_ID_LIST = ['1218958685'] 

TARGET_STOCK = '0050' 
HISTORICAL_HIGH_0050 = 64.85 
BUY_ALERT_DROP_PERCENT = 0.06 
US_TARGET_LIST = ['SPY', 'QQQ', 'VOO']
# ============================================================

# --- 1. 建立一個假的網站伺服器 (為了讓 Render Web Service 開心) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_web_server():
    # Render 規定要聽 0.0.0.0，port 預設 10000
    app.run(host='0.0.0.0', port=10000)

# ---------------------------------------------------------

# --- 建立台股名稱對照表 ---
TW_STOCK_MAP = {}
for code in twstock.codes:
    info = twstock.codes[code]
    TW_STOCK_MAP[info.name] = code

def search_tw_code_by_name(name):
    if name in TW_STOCK_MAP:
        return TW_STOCK_MAP[name]
    for stock_name, code in TW_STOCK_MAP.items():
        if name in stock_name:
            return code
    return None

def get_tw_stock_message(stock_code):
    try:
        if not stock_code.isdigit():
            found_code = search_tw_code_by_name(stock_code)
            if found_code:
                stock_code = found_code
            else:
                return None

        if datetime.datetime.today().weekday() > 4: pass 

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
            f"🔥 今日最高: {high_price}\n"
            f"❄️ 今日最低: {low_price}\n"
            f"📊 量: {volume} 張"
        )
        return msg
    except Exception as e:
        print(f"台股抓取錯誤: {e}")
        return None

def get_us_stock_message(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
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
        fifty_two_high = info.get('fiftyTwoWeekHigh', 0)

        msg = (
            f"<b>🇺🇸 【{ticker.upper()} ({name})】</b>\n"
            f"--------------------\n"
            f"💰 <b>USD: {price}</b>\n"
            f"📈 漲跌: {emoji} {sign}{diff:.2f} ({sign}{diff_percent:.2f}%)\n"
            f"--------------------\n"
            f"🔥 今日高: {day_high} | 低: {day_low}\n"
            f"🏔️ 52週高: {fifty_two_high}\n"
            f"📊 量: {volume:,}" 
        )
        return msg
    except Exception as e:
        print(f"美股抓取錯誤: {e}")
        return f"⚠️ 美股 {ticker} 查詢失敗。"

async def stock_command(update, context):
    try:
        if not context.args:
            query = TARGET_STOCK
        else:
            query = context.args[0].strip()
        await update.message.reply_text(f"🔍 查詢「{query}」中...", parse_mode=ParseMode.HTML)
        
        tw_msg = get_tw_stock_message(query)
        if tw_msg:
            await update.message.reply_text(tw_msg, parse_mode=ParseMode.HTML)
        else:
            us_msg = get_us_stock_message(query)
            await update.message.reply_text(us_msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"🚨 錯誤: {e}")

async def daily_report_job(context):
    messages = []
    tw_msg = get_tw_stock_message(TARGET_STOCK)
    if tw_msg: messages.append(tw_msg)
    for us_stock in US_TARGET_LIST:
        us_msg = get_us_stock_message(us_stock)
        if us_msg: messages.append(us_msg)

    for chat_id in TG_CHAT_ID_LIST:
        if chat_id and chat_id.strip() != '':
            try:
                for msg in messages:
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)
            except Exception as e:
                print(f"發送給 {chat_id} 失敗: {e}")

async def check_buy_alert(context):
    now = datetime.datetime.now()
    if now.weekday() > 4: return 
    if not (datetime.time(9, 0) <= now.time() <= datetime.time(13, 35)): return

    alert_messages = []
    try:
        stock = twstock.realtime.get(TARGET_STOCK)
        if stock.get('success'):
            latest = stock['realtime']['latest_trade_price']
            if latest == '-' and stock['realtime']['best_bid_price']:
                current_price = float(stock['realtime']['best_bid_price'][0])
            elif latest != '-':
                current_price = float(latest)
            else:
                current_price = None

            if current_price:
                drop_percent = (HISTORICAL_HIGH_0050 - current_price) / HISTORICAL_HIGH_0050
                if drop_percent >= BUY_ALERT_DROP_PERCENT:
                    alert_messages.append(
                        f"🔔 <b>[🚨 0050 買入提醒]</b>\n"
                        f"已從高點 {HISTORICAL_HIGH_0050} 回檔 <b>{drop_percent*100:.1f}%</b>\n"
                        f"現價: {current_price}"
                    )
    except Exception as e:
        print(f"檢查 0050 出錯: {e}")

    for us_ticker in US_TARGET_LIST:
        try:
            ticker = yf.Ticker(us_ticker)
            info = ticker.info
            price = info.get('currentPrice') or info.get('regularMarketPrice')
            fifty_two_high = info.get('fiftyTwoWeekHigh')

            if price and fifty_two_high:
                drop_percent = (fifty_two_high - price) / fifty_two_high
                if drop_percent >= BUY_ALERT_DROP_PERCENT:
                    alert_messages.append(
                        f"🔔 <b>[🚨 {us_ticker} 買入提醒]</b>\n"
                        f"已從52週高點 {fifty_two_high} 回檔 <b>{drop_percent*100:.1f}%</b>\n"
                        f"現價 (USD): {price}"
                    )
        except Exception as e:
            print(f"檢查 {us_ticker} 出錯: {e}")

    if alert_messages:
        for chat_id in TG_CHAT_ID_LIST:
            if chat_id and chat_id.strip() != '':
                try:
                    for alert in alert_messages:
                        await context.bot.send_message(chat_id=chat_id, text=alert, parse_mode=ParseMode.HTML)
                except Exception as e:
                    print(f"發送警報給 {chat_id} 失敗: {e}")

def main():
    # 啟動偽裝網站 (使用執行緒，才不會卡住機器人)
    threading.Thread(target=run_web_server).start()

    application = ApplicationBuilder().token(TG_BOT_TOKEN).build()
    j = application.job_queue
    
    application.add_handler(CommandHandler("stock", stock_command))
    
    j.run_daily(daily_report_job, time=datetime.time(12, 0, 0), days=(0, 1, 2, 3, 4))
    j.run_daily(daily_report_job, time=datetime.time(13, 30, 0), days=(0, 1, 2, 3, 4))
    j.run_repeating(check_buy_alert, interval=1800, first=10)

    print(f"--- 雲端免費版機器人啟動中 ---")
    application.run_polling()

if __name__ == '__main__':
    main()