import sqlite3
import schedule
import time
import threading
from datetime import datetime, timedelta
import os
import requests

# Import keys from main (or duplicate here – simpler to copy)
TELEGRAM_BOT_TOKEN = "8958090720:AAEyV-pdf-M5Y0HQW9d4Bpd8u-x8kq8xTgw"
TELEGRAM_CHAT_ID = "1942139816"
DB_PATH = os.path.join(os.path.dirname(__file__), "database", "signals.db")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
        print("Report message sent.")
    except Exception as e:
        print(f"Telegram error: {e}")

def get_week_range():
    """Return (start_date, end_date) for current week (Monday to Sunday)"""
    today = datetime.now().date()
    start = today - timedelta(days=today.weekday())  # Monday
    end = start + timedelta(days=6)  # Sunday
    return start, end

def get_month_range():
    """Return (start_date, end_date) for current month"""
    today = datetime.now().date()
    start = today.replace(day=1)
    # next month first day minus one day
    if start.month == 12:
        end = start.replace(year=start.year+1, month=1, day=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month+1, day=1) - timedelta(days=1)
    return start, end

def get_signal_stats(start_date, end_date):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT direction, status, pips, pair, session, timestamp
        FROM signals
        WHERE datetime(timestamp, 'unixepoch') >= ? AND datetime(timestamp, 'unixepoch') <= ?
    ''', (start_date.isoformat(), end_date.isoformat()))
    rows = cursor.fetchall()
    conn.close()
    
    total = len(rows)
    full_wins = sum(1 for r in rows if r[1] == 'full_win')
    partial_wins = sum(1 for r in rows if r[1] == 'partial_win')
    losses = sum(1 for r in rows if r[1] == 'loss')
    win_rate = (full_wins + partial_wins) / total * 100 if total > 0 else 0
    
    # Breakdown by pair
    pair_perf = {}
    for r in rows:
        pair = r[3]
        if pair not in pair_perf:
            pair_perf[pair] = {'wins': 0, 'losses': 0, 'pips': 0}
        if r[1] in ('full_win', 'partial_win'):
            pair_perf[pair]['wins'] += 1
            pair_perf[pair]['pips'] += r[2] if r[2] else 0
        else:
            pair_perf[pair]['losses'] += 1
            pair_perf[pair]['pips'] += r[2] if r[2] else 0
    
    # Session performance
    session_perf = {}
    for r in rows:
        sess = r[4] or 'Unknown'
        if sess not in session_perf:
            session_perf[sess] = {'wins': 0, 'total': 0}
        session_perf[sess]['total'] += 1
        if r[1] in ('full_win', 'partial_win'):
            session_perf[sess]['wins'] += 1
    
    # For simplicity, we will format the report as per example
    return {
        'total': total,
        'full_wins': full_wins,
        'partial_wins': partial_wins,
        'losses': losses,
        'win_rate': win_rate,
        'pair_perf': pair_perf,
        'session_perf': session_perf,
        'rows': rows
    }

def format_weekly_report(start_date, end_date):
    stats = get_signal_stats(start_date, end_date)
    if stats['total'] == 0:
        return f"📊 No signals this week ({start_date} – {end_date})"
    
    # Build report string
    lines = []
    lines.append(f"📊 FOREX BOT — WEEKLY PERFORMANCE REPORT")
    lines.append(f"Week: {start_date.strftime('%d %b')} – {end_date.strftime('%d %b %Y')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(f"📈 RESULTS THIS WEEK:")
    lines.append(f"Total Signals: {stats['total']}")
    lines.append(f"Full Wins (TP2 hit): {stats['full_wins']} ✅")
    lines.append(f"Partial Wins (TP1 hit): {stats['partial_wins']} ✅")
    lines.append(f"Losses (SL hit): {stats['losses']} ❌")
    lines.append(f"Win Rate: {stats['win_rate']:.1f}%")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("💰 BREAKDOWN:")
    for pair, perf in stats['pair_perf'].items():
        wins = perf['wins']
        losses = perf['losses']
        pips = perf['pips']
        result = "✅" if wins > losses else "❌"
        lines.append(f"{pair} {result} — {wins} wins {losses} losses | {pips:+.0f} pips")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    # Find best/worst pair (simple: highest win rate)
    best_pair = max(stats['pair_perf'].items(), key=lambda x: x[1]['wins']/(x[1]['wins']+x[1]['losses']) if (x[1]['wins']+x[1]['losses'])>0 else 0)[0]
    worst_pair = min(stats['pair_perf'].items(), key=lambda x: x[1]['wins']/(x[1]['wins']+x[1]['losses']) if (x[1]['wins']+x[1]['losses'])>0 else 1)[0]
    lines.append(f"📊 BEST PERFORMING PAIR: {best_pair}")
    lines.append(f"📊 WORST PERFORMING PAIR: {worst_pair}")
    # Session performance
    best_session = max(stats['session_perf'].items(), key=lambda x: x[1]['wins']/x[1]['total'] if x[1]['total']>0 else 0)[0]
    lines.append(f"📊 BEST SESSION: {best_session} ({stats['session_perf'][best_session]['wins']}/{stats['session_perf'][best_session]['total']} wins)")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    # For now, we skip layer performance (needs to be stored per signal). We'll add placeholder.
    lines.append("🔍 LAYER PERFORMANCE: (to be implemented)")
    lines.append("")
    # Account performance – we would need starting balance per week. For simplicity, we can compute net pips and assume 1% per trade risk.
    total_pips = sum(perf['pips'] for perf in stats['pair_perf'].values())
    # Rough growth: assume 1% risk per trade, each pip ~ $1 for standard lot? We'll just show net pips.
    lines.append(f"💼 ACCOUNT PERFORMANCE (simulated):")
    lines.append(f"Net Pips: {total_pips:+.0f}")
    lines.append("")
    lines.append("🤖 Forex Signal Bot | Weekly Summary")
    return "\n".join(lines)

def format_monthly_report(start_date, end_date):
    stats = get_signal_stats(start_date, end_date)
    if stats['total'] == 0:
        return f"📊 No signals this month ({start_date.strftime('%b %Y')})"
    
    lines = []
    lines.append(f"📊 FOREX BOT — MONTHLY PERFORMANCE REPORT")
    lines.append(f"Month: {start_date.strftime('%B %Y')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(f"Total Signals: {stats['total']}")
    lines.append(f"Full Wins: {stats['full_wins']} ✅")
    lines.append(f"Partial Wins: {stats['partial_wins']} ✅")
    lines.append(f"Losses: {stats['losses']} ❌")
    lines.append(f"Overall Win Rate: {stats['win_rate']:.1f}%")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    # Best performing pairs
    sorted_pairs = sorted(stats['pair_perf'].items(), key=lambda x: x[1]['wins']/(x[1]['wins']+x[1]['losses']) if (x[1]['wins']+x[1]['losses'])>0 else 0, reverse=True)
    lines.append("🏆 BEST PERFORMING PAIRS:")
    for i, (pair, perf) in enumerate(sorted_pairs[:3]):
        lines.append(f"{i+1}. {pair} — {perf['wins']} wins {perf['losses']} losses")
    lines.append("")
    lines.append("⚠️ WEAKEST PAIRS:")
    for pair, perf in sorted_pairs[-2:]:
        lines.append(f"{pair} — {perf['wins']} wins {perf['losses']} losses")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    # Session performance
    lines.append("🕐 SESSION PERFORMANCE:")
    for sess, perf in stats['session_perf'].items():
        wr = perf['wins']/perf['total']*100 if perf['total']>0 else 0
        lines.append(f"{sess} Win Rate: {wr:.0f}% ({perf['wins']}/{perf['total']})")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    # Layer performance would require storing layer results per signal. Placeholder.
    lines.append("🔍 LAYER PERFORMANCE: (to be implemented)")
    lines.append("")
    # Account performance: net pips
    total_pips = sum(perf['pips'] for perf in stats['pair_perf'].values())
    lines.append("💼 ACCOUNT PERFORMANCE (simulated):")
    lines.append(f"Net Pips: {total_pips:+.0f}")
    lines.append("")
    lines.append("🤖 Forex Signal Bot | Monthly Summary")
    return "\n".join(lines)

def send_weekly_report():
    start, end = get_week_range()
    report = format_weekly_report(start, end)
    send_telegram_message(report)

def send_monthly_report():
    start, end = get_month_range()
    # Check if it's the first Sunday of the month
    today = datetime.now().date()
    if today.day > 7:
        # Not first week, skip
        return
    report = format_monthly_report(start, end)
    send_telegram_message(report)

def schedule_reports():
    # Schedule weekly report every Sunday at 8am UK time
    # UK time can be approximated as UTC+1 in summer. We'll use UTC+1 for simplicity.
    # Better: use timezone-aware scheduling; but we'll schedule at 7am UTC which is 8am UK during summer.
    schedule.every().sunday.at("07:00").do(send_weekly_report)
    # Monthly on first Sunday – we check inside the function because schedule doesn't have "first sunday"
    # Instead, run a daily check at 8am UK, if it's first Sunday, send monthly.
    schedule.every().day.at("07:00").do(send_monthly_report)
    while True:
        schedule.run_pending()
        time.sleep(60)

def start_report_scheduler():
    thread = threading.Thread(target=schedule_reports, daemon=True)
    thread.start()
    print("Report scheduler started.")