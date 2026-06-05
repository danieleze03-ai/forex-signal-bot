import sqlite3
import time
import threading
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "database", "signals.db")

def ensure_exit_time_column():
    """Add exit_time column to signals table if it doesn't exist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Check if column exists
    cursor.execute("PRAGMA table_info(signals)")
    columns = [col[1] for col in cursor.fetchall()]
    if "exit_time" not in columns:
        cursor.execute("ALTER TABLE signals ADD COLUMN exit_time INTEGER")
        print("Added exit_time column to signals table")
    if "pips" not in columns:
        cursor.execute("ALTER TABLE signals ADD COLUMN pips REAL")
        print("Added pips column to signals table")
    conn.commit()
    conn.close()

def get_active_signals():
    """Return list of active signals (status='active')"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, pair, direction, entry, stop_loss, tp1, tp2, timestamp
        FROM signals
        WHERE status = 'active'
    ''')
    rows = cursor.fetchall()
    conn.close()
    signals = []
    for row in rows:
        signals.append({
            'id': row[0],
            'pair': row[1],
            'direction': row[2],
            'entry': row[3],
            'stop': row[4],
            'tp1': row[5],
            'tp2': row[6],
            'timestamp': row[7]
        })
    return signals

def get_current_price(pair):
    """Get latest close price from 15min candles"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT close FROM candles
        WHERE pair = ? AND timeframe = '15min'
        ORDER BY timestamp DESC LIMIT 1
    ''', (pair,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return None

def update_signal_status(signal_id, status, pips, exit_time):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE signals
        SET status = ?, pips = ?, exit_time = ?
        WHERE id = ?
    ''', (status, pips, exit_time, signal_id))
    conn.commit()
    conn.close()

def calculate_pips(pair, price_diff):
    """Convert price difference to pips based on pair"""
    pip_multiplier = {
        "EUR/USD": 10000, "GBP/USD": 10000, "USD/JPY": 100, "USD/CHF": 10000,
        "AUD/USD": 10000, "USD/CAD": 10000, "GBP/JPY": 100, "XAU/USD": 10
    }
    multiplier = pip_multiplier.get(pair, 10000)
    return price_diff * multiplier

def check_active_signals():
    signals = get_active_signals()
    if not signals:
        return
    for s in signals:
        price = get_current_price(s['pair'])
        if price is None:
            continue
        # Determine direction
        if s['direction'] == 'BUY':
            # Check TP2 first (full win)
            if price >= s['tp2']:
                pips = calculate_pips(s['pair'], s['tp2'] - s['entry'])
                update_signal_status(s['id'], 'full_win', pips, int(datetime.now().timestamp()))
                print(f"✅ Signal {s['id']} hit TP2 (full win) +{pips:.1f} pips")
            elif price >= s['tp1']:
                pips = calculate_pips(s['pair'], s['tp1'] - s['entry'])
                update_signal_status(s['id'], 'partial_win', pips, int(datetime.now().timestamp()))
                print(f"✅ Signal {s['id']} hit TP1 (partial win) +{pips:.1f} pips")
            elif price <= s['stop']:
                pips = calculate_pips(s['pair'], s['stop'] - s['entry'])
                update_signal_status(s['id'], 'loss', pips, int(datetime.now().timestamp()))
                print(f"❌ Signal {s['id']} hit stop loss {pips:.1f} pips")
        else:  # SELL
            if price <= s['tp2']:
                pips = calculate_pips(s['pair'], s['entry'] - s['tp2'])
                update_signal_status(s['id'], 'full_win', pips, int(datetime.now().timestamp()))
                print(f"✅ Signal {s['id']} hit TP2 (full win) +{pips:.1f} pips")
            elif price <= s['tp1']:
                pips = calculate_pips(s['pair'], s['entry'] - s['tp1'])
                update_signal_status(s['id'], 'partial_win', pips, int(datetime.now().timestamp()))
                print(f"✅ Signal {s['id']} hit TP1 (partial win) +{pips:.1f} pips")
            elif price >= s['stop']:
                pips = calculate_pips(s['pair'], s['entry'] - s['stop'])
                update_signal_status(s['id'], 'loss', pips, int(datetime.now().timestamp()))
                print(f"❌ Signal {s['id']} hit stop loss {pips:.1f} pips")

def performance_worker():
    """Run every 5 minutes to check active signals"""
    while True:
        check_active_signals()
        time.sleep(300)  # 5 minutes

def start_performance_tracker():
    # First, ensure the database has required columns
    ensure_exit_time_column()
    thread = threading.Thread(target=performance_worker, daemon=True)
    thread.start()
    print("Performance tracker started.")