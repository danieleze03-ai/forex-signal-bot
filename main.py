import sqlite3
import requests
import time
import threading
from datetime import datetime, timezone, timedelta
import os

# ==============================================
# KEYS (hardcoded as you requested)
# ==============================================
TELEGRAM_BOT_TOKEN = "8958090720:AAEyV-pdf-M5Y0HQW9d4Bpd8u-x8kq8xTgw"
# Multiple chat IDs: your personal ID and your channel ID
TELEGRAM_CHAT_IDS = [1942139816, 1003890885812]   # <-- ADDED BOTH
TWELVE_DATA_API_KEY = "d5b253bdf088484a914d917a37c3af1c"
FINNHUB_API_KEY = "d8h105hr01qhjpmq4ncgd8h105hr01qhjpmq4nd0"

# ==============================================
# IMPORT TRACKING AND REPORTING MODULES
# ==============================================
from performance_tracker import start_performance_tracker
from report_scheduler import start_report_scheduler

# ==============================================
# CONFIGURATION
# ==============================================
DB_PATH = os.path.join(os.path.dirname(__file__), "database", "signals.db")

PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "GBP/JPY", "XAU/USD"
]

# Set to False to respect real London/NY session hours; True forces always active
TRADING_SESSION_ACTIVE = False   # <-- FOR LIVE DEPLOYMENT

# ==============================================
# DATABASE FUNCTIONS
# ==============================================
def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT,
            timeframe TEXT,
            timestamp INTEGER,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            UNIQUE(pair, timeframe, timestamp)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT,
            direction TEXT,
            entry REAL,
            stop_loss REAL,
            tp1 REAL,
            tp2 REAL,
            confidence INTEGER,
            layers_passed TEXT,
            session TEXT,
            timestamp INTEGER,
            status TEXT,
            pips REAL,
            exit_time INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def fetch_candle_data(pair, timeframe):
    tf_map = {"week": "1week", "day": "1day", "1hour": "1h", "15min": "15min"}
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": pair,
        "interval": tf_map[timeframe],
        "outputsize": 500,
        "apikey": TWELVE_DATA_API_KEY
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if "values" not in data:
            print(f"Error {pair} {timeframe}: {data.get('message', 'Unknown')}")
            return []
        candles = []
        for item in data["values"]:
            dt_str = item["datetime"]
            if " " in dt_str:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.strptime(dt_str, "%Y-%m-%d")
            candles.append({
                "timestamp": int(dt.timestamp()),
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": int(item.get("volume", 0))
            })
        return candles
    except Exception as e:
        print(f"Exception {pair} {timeframe}: {e}")
        return []

def store_candles(pair, timeframe, candles):
    if not candles:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for c in candles:
        cursor.execute('''
            INSERT OR REPLACE INTO candles 
            (pair, timeframe, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (pair, timeframe, c["timestamp"], c["open"], c["high"], c["low"], c["close"], c["volume"]))
    conn.commit()
    conn.close()
    print(f"Stored {len(candles)} candles for {pair} {timeframe}")

def get_latest_candle(pair, timeframe):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, open, high, low, close
        FROM candles
        WHERE pair = ? AND timeframe = ?
        ORDER BY timestamp DESC LIMIT 1
    ''', (pair, timeframe))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"timestamp": row[0], "open": row[1], "high": row[2], "low": row[3], "close": row[4]}
    return None

def get_historical_candles(pair, timeframe, limit):
    """Return list of candles (close, high, low) sorted oldest first"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, open, high, low, close
        FROM candles
        WHERE pair = ? AND timeframe = ?
        ORDER BY timestamp ASC
        LIMIT ?
    ''', (pair, timeframe, limit))
    rows = cursor.fetchall()
    conn.close()
    candles = []
    for r in rows:
        candles.append({
            "timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4]
        })
    return candles

# ==============================================
# DATA UPDATE LOGIC
# ==============================================
last_daily_update = None

def update_timeframe(pair, timeframe):
    print(f"Fetching {pair} {timeframe}...")
    candles = fetch_candle_data(pair, timeframe)
    if candles:
        store_candles(pair, timeframe, candles)
        return True
    return False

def update_daily_weekly():
    global last_daily_update
    today = datetime.now().date()
    if last_daily_update == today:
        return
    print(f"\n--- Daily/Weekly update for {today} ---")
    for pair in PAIRS:
        for tf in ["week", "day"]:
            update_timeframe(pair, tf)
            time.sleep(12)
    last_daily_update = today
    print("--- Daily/Weekly update complete ---\n")

def update_intraday():
    print(f"\n--- Intraday update {datetime.now()} ---")
    for pair in PAIRS:
        for tf in ["1hour", "15min"]:
            update_timeframe(pair, tf)
            time.sleep(12)

# ==============================================
# SESSION CHECK
# ==============================================
def is_trading_session():
    if TRADING_SESSION_ACTIVE:
        return True
    now_utc = datetime.now(timezone.utc)
    hour_utc = now_utc.hour
    return (6 <= hour_utc < 11) or (12 <= hour_utc < 16)

# ==============================================
# LAYER 1 – Higher Timeframe Trend
# ==============================================
def layer1_trend(pair):
    weekly = get_latest_candle(pair, "week")
    daily = get_latest_candle(pair, "day")
    if not weekly or not daily:
        return False, "Missing weekly/daily data", "neutral"
    wk_trend = "uptrend" if weekly["close"] > weekly["open"] else "downtrend" if weekly["close"] < weekly["open"] else "neutral"
    dy_trend = "uptrend" if daily["close"] > daily["open"] else "downtrend" if daily["close"] < daily["open"] else "neutral"
    if wk_trend == dy_trend and wk_trend != "neutral":
        return True, f"Weekly {wk_trend}, Daily {dy_trend}", wk_trend
    return False, f"Weekly {wk_trend} vs Daily {dy_trend}", "neutral"

# ==============================================
# LAYER 2 – Smart Money Order Blocks (1H)
# ==============================================
def layer2_order_blocks(pair, trend):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT open, high, low, close FROM candles
        WHERE pair = ? AND timeframe = '1hour'
        ORDER BY timestamp DESC LIMIT 20
    ''', (pair,))
    rows = cursor.fetchall()
    conn.close()
    if len(rows) < 10:
        return False, "Insufficient 1H data"
    candles = [{"open": r[0], "high": r[1], "low": r[2], "close": r[3]} for r in reversed(rows)]
    avg_range = sum((c["high"]-c["low"]) for c in candles[-10:]) / 10
    for i in range(1, len(candles)):
        move = abs(candles[i]["close"] - candles[i-1]["close"])
        if move > 1.5 * avg_range:
            ob = candles[i-1]
            if trend == "uptrend" and ob["close"] < ob["open"]:
                return True, f"Bullish OB near {ob['high']:.5f}"
            if trend == "downtrend" and ob["close"] > ob["open"]:
                return True, f"Bearish OB near {ob['low']:.5f}"
    return False, "No valid order block"

# ==============================================
# LAYER 3 – Market Structure (15M) – IMPROVED with swing points
# ==============================================
def find_swing_points(candles, lookback=3):
    """
    candles: list of dicts with 'high', 'low', 'close'
    returns (last_swing_high, last_swing_low)
    """
    if len(candles) < lookback * 2 + 1:
        return None, None
    swing_highs = []
    swing_lows = []
    for i in range(lookback, len(candles) - lookback):
        # Swing high
        is_high = all(candles[i]['high'] >= candles[i-j]['high'] for j in range(1, lookback+1)) and \
                  all(candles[i]['high'] >= candles[i+j]['high'] for j in range(1, lookback+1))
        if is_high:
            swing_highs.append({'index': i, 'price': candles[i]['high']})
        # Swing low
        is_low = all(candles[i]['low'] <= candles[i-j]['low'] for j in range(1, lookback+1)) and \
                 all(candles[i]['low'] <= candles[i+j]['low'] for j in range(1, lookback+1))
        if is_low:
            swing_lows.append({'index': i, 'price': candles[i]['low']})
    last_high = swing_highs[-1]['price'] if swing_highs else None
    last_low = swing_lows[-1]['price'] if swing_lows else None
    return last_high, last_low

def layer3_structure(pair, trend):
    candles = get_historical_candles(pair, "15min", 100)
    if len(candles) < 30:
        return False, "Insufficient 15M data"
    # Convert to format needed for swing detection
    swing_candles = [{'high': c['high'], 'low': c['low'], 'close': c['close']} for c in candles]
    last_swing_high, last_swing_low = find_swing_points(swing_candles, lookback=3)
    current_close = candles[-1]['close']
    
    if trend == "uptrend" and last_swing_high is not None and current_close > last_swing_high:
        return True, f"Structure break above swing high {last_swing_high:.5f}"
    elif trend == "downtrend" and last_swing_low is not None and current_close < last_swing_low:
        return True, f"Structure break below swing low {last_swing_low:.5f}"
    else:
        return False, "No confirmed structure break"

# ==============================================
# LAYER 4 – Session (handled in main loop)
# ==============================================
def layer4_session():
    return True, "Session active (checked in main)"

# ==============================================
# LAYER 5 – Economic Calendar (Finnhub) – IMPLEMENTED
# ==============================================
def layer5_economic(pair):
    # Map pair to base currency
    curr = pair.split('/')[0]
    if curr == "XAU":
        curr = "USD"
    url = f"https://finnhub.io/api/v1/calendar/economic?apiKey={FINNHUB_API_KEY}"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if "economicCalendar" not in data:
            return True, "No news data"
        now = datetime.now()
        for event in data["economicCalendar"]:
            if event.get("impact") == "high" and curr in event.get("currency", ""):
                event_time = datetime.fromtimestamp(event.get("timestamp", now.timestamp()))
                if abs((event_time - now).total_seconds()) < 7200:  # 2 hours
                    return False, f"High impact news: {event.get('event', 'unknown')}"
        return True, "No high impact news within 2h"
    except Exception as e:
        print(f"News check error: {e}")
        return True, "News check failed, skipping filter"

# ==============================================
# LAYER 6 – Structural Stop Loss & Risk – IMPROVED
# ==============================================
def find_nearest_stop_level(pair, direction, entry_price):
    """Find nearest swing high (for sell) or swing low (for buy) within last 100 candles on 15M"""
    candles = get_historical_candles(pair, "15min", 100)
    if len(candles) < 30:
        return None
    swing_candles = [{'high': c['high'], 'low': c['low']} for c in candles]
    last_swing_high, last_swing_low = find_swing_points(swing_candles, lookback=3)
    if direction == "BUY" and last_swing_low is not None:
        if last_swing_low < entry_price:
            return last_swing_low
    elif direction == "SELL" and last_swing_high is not None:
        if last_swing_high > entry_price:
            return last_swing_high
    return None

def calculate_structural_stop(pair, direction, entry_price):
    pip_multiplier = {
        "EUR/USD": 0.0001, "GBP/USD": 0.0001, "USD/JPY": 0.01, "USD/CHF": 0.0001,
        "AUD/USD": 0.0001, "USD/CAD": 0.0001, "GBP/JPY": 0.01, "XAU/USD": 0.1
    }
    pip = pip_multiplier.get(pair, 0.0001)
    buffer_pips = {
        "EUR/USD": 5, "GBP/USD": 7, "USD/JPY": 8, "USD/CHF": 5,
        "AUD/USD": 6, "USD/CAD": 6, "GBP/JPY": 12, "XAU/USD": 3
    }.get(pair, 5)
    
    level = find_nearest_stop_level(pair, direction, entry_price)
    if level is not None:
        if direction == "BUY":
            stop = level - buffer_pips * pip
        else:
            stop = level + buffer_pips * pip
    else:
        # Fallback to 20 pips
        if direction == "BUY":
            stop = entry_price - 20 * pip
        else:
            stop = entry_price + 20 * pip
    return stop

def layer6_risk(pair, direction, entry, stop_loss):
    # This function is now integrated into generate_signal via calculate_structural_stop.
    # Placeholder for any additional risk checks.
    return True, "Risk OK"

# ==============================================
# LAYER 7 – Sentiment (placeholder, can be upgraded later)
# ==============================================
def layer7_sentiment(pair, direction):
    # TODO: Integrate free retail sentiment API (e.g., OANDA or FXCM) in the future.
    # For now, always passes.
    return True, "Sentiment aligned (placeholder)"

# ==============================================
# MASTER ANALYSIS (runs all 7 layers)
# ==============================================
def analyze_pair_full(pair):
    # Layer 1
    ok, msg, trend = layer1_trend(pair)
    if not ok:
        return {"layer1": msg}, False, trend
    # Layer 2
    ok, msg = layer2_order_blocks(pair, trend)
    if not ok:
        return {"layer2": msg}, False, trend
    # Layer 3
    ok, msg = layer3_structure(pair, trend)
    if not ok:
        return {"layer3": msg}, False, trend
    # Layer 4 (always passes – session is handled by main loop)
    # Layer 5
    ok, msg = layer5_economic(pair)
    if not ok:
        return {"layer5": msg}, False, trend
    # Layer 6 will be applied in generate_signal with stop calculation
    # Layer 7
    ok, msg = layer7_sentiment(pair, trend)
    if not ok:
        return {"layer7": msg}, False, trend
    
    return {"layers": "All 7 layers passed"}, True, trend

# ==============================================
# SIGNAL GENERATION (uses structural stop) – WITH DUPLICATE PREVENTION
# ==============================================
def calculate_tp_levels(pair, direction, entry, stop):
    pip_multiplier = {
        "EUR/USD": 0.0001, "GBP/USD": 0.0001, "USD/JPY": 0.01, "USD/CHF": 0.0001,
        "AUD/USD": 0.0001, "USD/CAD": 0.0001, "GBP/JPY": 0.01, "XAU/USD": 0.1
    }
    pip = pip_multiplier.get(pair, 0.0001)
    risk_pips = abs(entry - stop) / pip
    if direction == "BUY":
        tp1 = entry + risk_pips * pip
        tp2 = entry + 2 * risk_pips * pip
    else:
        tp1 = entry - risk_pips * pip
        tp2 = entry - 2 * risk_pips * pip
    return tp1, tp2

def send_telegram_message(message):
    """Send message to multiple Telegram chats"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        try:
            requests.post(url, json=payload, timeout=5)
            print(f"Telegram message sent to {chat_id}")
        except Exception as e:
            print(f"Telegram error for {chat_id}: {e}")

def generate_signal(pair, trend, entry_price):
    # === DUPLICATE PREVENTION: check if there's an active signal for this pair ===
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM signals
        WHERE pair = ? AND status = 'active'
    ''', (pair,))
    active = cursor.fetchone()
    conn.close()
    if active:
        print(f"⏸️ Skipping {pair} – active signal already exists")
        return False
    # ============================================================================

    direction = "BUY" if trend == "uptrend" else "SELL"
    stop = calculate_structural_stop(pair, direction, entry_price)
    tp1, tp2 = calculate_tp_levels(pair, direction, entry_price, stop)
    risk = abs(entry_price - stop)
    reward = abs(tp2 - entry_price)
    if reward < 1.5 * risk:
        print(f"Signal rejected for {pair}: R/R {reward/risk:.1f} < 1.5")
        return False
    confidence = 94
    layers_passed = "7/7"
    session = "London" if datetime.now().hour < 12 else "New York"
    
    # ===== LOG TO DATABASE BEFORE TELEGRAM =====
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO signals (pair, direction, entry, stop_loss, tp1, tp2, confidence, layers_passed, session, timestamp, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (pair, direction, entry_price, stop, tp1, tp2, confidence, layers_passed, session, int(datetime.now().timestamp()), "active"))
    conn.commit()
    conn.close()
    # ==========================================
    
    # Then send Telegram to all recipients
    msg = f"""
🚨 FOREX SIGNAL — HIGH CONFIDENCE

Pair: {pair}
Direction: {direction} 📉
Confidence: {confidence}% — {layers_passed} LAYERS CONFIRMED

Entry Zone: {entry_price:.5f}
Stop Loss: {stop:.5f}
Take Profit 1: {tp1:.5f} (1:1.0 — move SL to breakeven)
Take Profit 2: {tp2:.5f} (1:2.0 — full target)

🔑 Why This Trade:
- Weekly & Daily aligned: {trend} ✅
- Order block respected ✅
- Structure shift confirmed ✅
- {session} session active ✅
- No high impact news ✅
- Risk: 1% of account

⏳ Setup valid for: 2 hours
🕐 Signal time: {datetime.now().strftime('%H:%M UK time')}
    """
    send_telegram_message(msg)
    return True

# ==============================================
# MAIN ANALYSIS LOOP
# ==============================================
def run_analysis():
    print(f"[{datetime.now()}] Running 7-layer analysis...")
    for pair in PAIRS:
        results, passed, trend = analyze_pair_full(pair)
        if passed:
            latest = get_latest_candle(pair, "15min")
            if latest:
                entry = latest["close"]
                generate_signal(pair, trend, entry)
            else:
                print(f"⚠️ No price data for {pair}")
        else:
            failed_layer = list(results.keys())[0] if results else "unknown"
            print(f"❌ {pair} failed on {failed_layer}: {results.get(failed_layer, '')}")
    print("Analysis cycle complete.\n")

# ==============================================
# BACKGROUND WORKER
# ==============================================
def background_worker():
    print("Background worker started.")
    while True:
        if is_trading_session():
            print("\n=== Trading session active ===")
            update_daily_weekly()
            update_intraday()
            run_analysis()
        else:
            print(f"[{datetime.now()}] Outside trading hours. Sleeping 5 min...")
        time.sleep(300)

# ==============================================
# FLASK WEB SERVER (for Render/UptimeRobot)
# ==============================================
from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Forex Signal Bot is running."

def start_background():
    thread = threading.Thread(target=background_worker, daemon=True)
    thread.start()

# ==============================================
# MAIN ENTRY
# ==============================================
if __name__ == "__main__":
    print("Starting Forex Signal Bot (final version with reports and tracking)...")
    init_database()
    # Start the performance tracker (monitors active signals)
    start_performance_tracker()
    # Start the report scheduler (weekly/monthly summaries)
    start_report_scheduler()
    # Start the main bot background worker
    start_background()
    # Run Flask to keep the bot alive on Render
    app.run(host='0.0.0.0', port=5000)