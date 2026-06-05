import sqlite3
import requests
import time
from datetime import datetime
import os

# ==============================================
# YOUR KEYS
# ==============================================
TELEGRAM_BOT_TOKEN = "8958090720:AAEyV-pdf-M5Y0HQW9d4Bpd8u-x8kq8xTgw"
TELEGRAM_CHAT_ID = "1942139816"
TWELVE_DATA_API_KEY = "d5b253bdf088484a914d917a37c3af1c"
FINNHUB_API_KEY = "d8h105hr01qhjpmq4ncgd8h105hr01qhjpmq4nd0"

# ==============================================
# DATABASE SETUP
# ==============================================
DB_PATH = os.path.join(os.path.dirname(__file__), "database", "signals.db")

PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "GBP/JPY", "XAU/USD"
]

# We'll only fetch 1hour and 15min for now (most critical)
# Weekly and Daily can be added later with separate scheduler
TIMEFRAMES = ["1hour", "15min"]

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
    conn.commit()
    conn.close()
    print(f"[{datetime.now()}] Database ready")

def fetch_candle_data(pair, timeframe):
    tf_map = {
        "1hour": "1h",
        "15min": "15min"
    }
    
    url = f"https://api.twelvedata.com/time_series"
    params = {
        "symbol": pair,
        "interval": tf_map[timeframe],
        "outputsize": 500,
        "apikey": TWELVE_DATA_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if "values" not in data:
            print(f"  Error {pair} {timeframe}: {data.get('message', 'Unknown')}")
            return []
        
        candles = []
        for item in data["values"]:
            # Handle different datetime formats
            datetime_str = item["datetime"]
            if " " in datetime_str:
                # Format: "2026-06-05 01:30:00"
                dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
            else:
                # Format: "2026-06-05" (daily/weekly)
                dt = datetime.strptime(datetime_str, "%Y-%m-%d")
            
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
        print(f"  Exception {pair} {timeframe}: {e}")
        return []

def store_candles(pair, timeframe, candles):
    if not candles:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for c in candles:
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO candles 
                (pair, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (pair, timeframe, c["timestamp"], c["open"], c["high"], c["low"], c["close"], c["volume"]))
        except Exception as e:
            print(f"Store error: {e}")
    conn.commit()
    conn.close()
    print(f"  Stored {len(candles)} candles for {pair} {timeframe}")

def update_all_data():
    print(f"\n{'='*60}")
    print(f"Update started at {datetime.now()}")
    
    for pair in PAIRS:
        for tf in TIMEFRAMES:
            print(f"Fetching {pair} - {tf}...")
            candles = fetch_candle_data(pair, tf)
            if candles:
                store_candles(pair, tf, candles)
            # Wait 12 seconds between requests to stay within 8 per minute (60/8 = 7.5 sec)
            time.sleep(12)
    
    print(f"Update completed at {datetime.now()}")

if __name__ == "__main__":
    init_database()
    update_all_data()
    print("\n✅ Data pipeline test complete.")