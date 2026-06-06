import sqlite3
import time
import threading
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "database", "signals.db")

def ensure_columns():
    """Add missing columns if they don't exist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(signals)")
    columns = [col[1] for col in cursor.fetchall()]
    if "exit_time" not in columns:
        cursor.execute("ALTER TABLE signals ADD COLUMN exit_time INTEGER")
        print("Added exit_time column")
    if "pips" not in columns:
        cursor.execute("ALTER TABLE signals ADD COLUMN pips REAL")
        print("Added pips column")
    conn.commit()
    conn.close()

def get_active_signals():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, pair, direction, entry, stop_loss, tp1, tp2, timestamp
        FROM signals WHERE status = 'active'
    ''')
    rows = cursor.fetchall()
    conn.close()
    signals = []
    for row in rows:
        signals.append({
            'id': row[0], 'pair': row[1], 'direction': row[2],
            'entry': row[3], 'stop': row[4], 'tp1': row[5], 'tp2': row[6], 'timestamp': row[7]
        })
    return signals

def get_latest_candle(pair, timeframe="15min"):
    """Return latest candle's high, low, close"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT high, low, close FROM candles
        WHERE pair = ? AND timeframe = ?
        ORDER BY timestamp DESC LIMIT 1
    ''', (pair, timeframe))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"high": row[0], "low": row[1], "close": row[2]}
    return None

def calculate_pips(pair, price_diff):
    mult = {
        "EUR/USD": 10000, "GBP/USD": 10000, "USD/JPY": 100, "USD/CHF": 10000,
        "AUD/USD": 10000, "USD/CAD": 10000, "GBP/JPY": 100, "XAU/USD": 10
    }.get(pair, 10000)
    return price_diff * mult

def update_signal_status(signal_id, status, pips, exit_time):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE signals SET status = ?, pips = ?, exit_time = ? WHERE id = ?
    ''', (status, pips, exit_time, signal_id))
    conn.commit()
    conn.close()

def check_active_signals():
    signals = get_active_signals()
    if not signals:
        return
    for s in signals:
        candle = get_latest_candle(s['pair'])
        if not candle:
            continue
        high = candle['high']
        low = candle['low']
        # For BUY
        if s['direction'] == 'BUY':
            # TP2 (full win)
            if high >= s['tp2']:
                pips = calculate_pips(s['pair'], s['tp2'] - s['entry'])
                update_signal_status(s['id'], 'full_win', pips, int(datetime.now().timestamp()))
                print(f"✅ {s['pair']} signal {s['id']} hit TP2: +{pips:.1f} pips")
            # TP1 (partial win)
            elif high >= s['tp1']:
                pips = calculate_pips(s['pair'], s['tp1'] - s['entry'])
                update_signal_status(s['id'], 'partial_win', pips, int(datetime.now().timestamp()))
                print(f"✅ {s['pair']} signal {s['id']} hit TP1: +{pips:.1f} pips")
            # Stop loss
            elif low <= s['stop']:
                pips = calculate_pips(s['pair'], s['stop'] - s['entry'])
                update_signal_status(s['id'], 'loss', pips, int(datetime.now().timestamp()))
                print(f"❌ {s['pair']} signal {s['id']} hit SL: {pips:.1f} pips")
        # For SELL
        else:
            # TP2 (full win)
            if low <= s['tp2']:
                pips = calculate_pips(s['pair'], s['entry'] - s['tp2'])
                update_signal_status(s['id'], 'full_win', pips, int(datetime.now().timestamp()))
                print(f"✅ {s['pair']} signal {s['id']} hit TP2: +{pips:.1f} pips")
            # TP1 (partial win)
            elif low <= s['tp1']:
                pips = calculate_pips(s['pair'], s['entry'] - s['tp1'])
                update_signal_status(s['id'], 'partial_win', pips, int(datetime.now().timestamp()))
                print(f"✅ {s['pair']} signal {s['id']} hit TP1: +{pips:.1f} pips")
            # Stop loss
            elif high >= s['stop']:
                pips = calculate_pips(s['pair'], s['entry'] - s['stop'])
                update_signal_status(s['id'], 'loss', pips, int(datetime.now().timestamp()))
                print(f"❌ {s['pair']} signal {s['id']} hit SL: {pips:.1f} pips")

def performance_worker():
    while True:
        check_active_signals()
        time.sleep(300)  # every 5 minutes

def start_performance_tracker():
    ensure_columns()
    thread = threading.Thread(target=performance_worker, daemon=True)
    thread.start()
    print("Performance tracker started (high/low check).")