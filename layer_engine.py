import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "database", "signals.db")

# ==============================================
# LAYER 1: Higher Timeframe Bias (Weekly + Daily)
# ==============================================
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

def determine_trend(candle):
    if candle is None:
        return "neutral"
    # Simple trend: compare close to open
    if candle["close"] > candle["open"]:
        return "uptrend"
    elif candle["close"] < candle["open"]:
        return "downtrend"
    else:
        return "neutral"

def layer1_higher_timeframe_bias(pair):
    weekly = get_latest_candle(pair, "week")
    daily = get_latest_candle(pair, "day")
    if weekly is None or daily is None:
        return False, "Insufficient data", "neutral"
    trend_weekly = determine_trend(weekly)
    trend_daily = determine_trend(daily)
    if trend_weekly == trend_daily and trend_weekly != "neutral":
        return True, f"Weekly {trend_weekly}, Daily {trend_daily}", trend_weekly
    else:
        return False, f"Weekly {trend_weekly} vs Daily {trend_daily} (disagreement)", "neutral"

# ==============================================
# LAYER 2: Smart Money Order Blocks (1H)
# ==============================================
def find_order_blocks(pair, direction):
    # Simplified: identify last 10 candles on 1H, find the candle before a large move
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, open, high, low, close 
        FROM candles 
        WHERE pair = ? AND timeframe = '1hour' 
        ORDER BY timestamp DESC LIMIT 20
    ''', (pair,))
    rows = cursor.fetchall()
    conn.close()
    if len(rows) < 10:
        return False, "Not enough 1H data"
    # Convert to list of dicts
    candles = [{"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in rows]
    candles.reverse()  # oldest first
    # Look for an impulsive move (candle range > 1.5x average)
    avg_range = sum((c["high"]-c["low"]) for c in candles[-10:]) / 10
    for i in range(1, len(candles)):
        if abs(candles[i]["close"] - candles[i-1]["close"]) > 1.5 * avg_range:
            # The candle before the impulse is the order block
            ob_candle = candles[i-1]
            if direction == "uptrend" and ob_candle["close"] < ob_candle["open"]:
                # Bullish order block (bearish candle before up move)
                return True, f"Order block found at {ob_candle['high']:.5f}"
            elif direction == "downtrend" and ob_candle["close"] > ob_candle["open"]:
                # Bearish order block (bullish candle before down move)
                return True, f"Order block found at {ob_candle['low']:.5f}"
    return False, "No valid order block"

def layer2_order_blocks(pair, trend_direction):
    if trend_direction == "neutral":
        return False, "No trend direction"
    return find_order_blocks(pair, trend_direction)

# ==============================================
# LAYER 3: Market Structure Confirmation (15M)
# ==============================================
def check_structure_break(pair, direction):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, high, low 
        FROM candles 
        WHERE pair = ? AND timeframe = '15min' 
        ORDER BY timestamp DESC LIMIT 50
    ''', (pair,))
    rows = cursor.fetchall()
    conn.close()
    if len(rows) < 20:
        return False, "Insufficient 15M data"
    # Find swing highs/lows
    highs = [r[1] for r in rows]
    lows = [r[2] for r in rows]
    recent_high = max(highs[:10])
    recent_low = min(lows[:10])
    current_price = rows[0][1]  # use latest high as proxy for current price
    if direction == "uptrend" and current_price > recent_high:
        return True, f"Break of structure to upside above {recent_high:.5f}"
    elif direction == "downtrend" and current_price < recent_low:
        return True, f"Break of structure to downside below {recent_low:.5f}"
    else:
        return False, "No structure break"

def layer3_market_structure(pair, trend_direction):
    if trend_direction == "neutral":
        return False, "Neutral trend"
    return check_structure_break(pair, trend_direction)

# ==============================================
# LAYER 4: Session Timing (handled in main.py, but we'll check)
# ==============================================
def layer4_session_timing():
    # Will be called from main, just return True if within session
    # This is a placeholder; actual check is in main's is_trading_session()
    return True, "Session active"

# ==============================================
# LAYER 5: Economic Calendar Filter (Finnhub)
# ==============================================
import requests

FINNHUB_KEY = "d8h105hr01qhjpmq4ncgd8h105hr01qhjpmq4nd0"

def layer5_economic_calendar(pair):
    # Get currency code from pair
    currency = pair.split('/')[0]  # e.g., EUR from EUR/USD
    if currency == "XAU":
        currency = "USD"  # Gold uses USD news
    url = f"https://finnhub.io/api/v1/calendar/economic?apiKey={FINNHUB_KEY}"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if "economicCalendar" not in data:
            return True, "No news data"
        now = datetime.now()
        for event in data["economicCalendar"]:
            if event.get("impact") == "high" and currency in event.get("currency", ""):
                event_time = datetime.fromtimestamp(event.get("timestamp", now.timestamp()))
                if abs((event_time - now).total_seconds()) < 7200:  # within 2 hours
                    return False, f"High impact news: {event.get('event', 'unknown')}"
        return True, "No high impact news within 2h"
    except:
        return True, "News check unavailable (safe)"

# ==============================================
# LAYER 6: Stop Loss & Risk Engine (will compute later in signal generator)
# ==============================================
def layer6_risk_engine(pair, entry, direction):
    # Placeholder: will compute structural stop loss and R:R
    return True, "Risk OK (placeholder)"

# ==============================================
# LAYER 7: Sentiment (COT, Retail, etc.) - Placeholder
# ==============================================
def layer7_sentiment(pair, direction):
    # For now, assume aligned
    return True, "Sentiment aligned (placeholder)"

# ==============================================
# MASTER ANALYSIS FUNCTION
# ==============================================
def analyze_pair(pair):
    results = {}
    # Layer 1
    passed, msg, trend = layer1_higher_timeframe_bias(pair)
    results["layer1"] = {"passed": passed, "message": msg}
    if not passed:
        return results, False, trend
    
    # Layer 2
    passed, msg = layer2_order_blocks(pair, trend)
    results["layer2"] = {"passed": passed, "message": msg}
    if not passed:
        return results, False, trend
    
    # Layer 3
    passed, msg = layer3_market_structure(pair, trend)
    results["layer3"] = {"passed": passed, "message": msg}
    if not passed:
        return results, False, trend
    
    # Layer 4 (will be checked in main)
    results["layer4"] = {"passed": True, "message": "Session active (assumed)"}
    
    # Layer 5
    passed, msg = layer5_economic_calendar(pair)
    results["layer5"] = {"passed": passed, "message": msg}
    if not passed:
        return results, False, trend
    
    # Layer 6 & 7 will be done in signal_generator after entry is determined
    results["layer6"] = {"passed": True, "message": "To be computed"}
    results["layer7"] = {"passed": True, "message": "To be computed"}
    
    return results, True, trend