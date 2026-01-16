import time
import pandas as pd
import numpy as np
import xgboost as xgb
import csv
import os
import requests
import yfinance as yf
import argparse
import warnings
import logging
import json
import glob
from datetime import datetime, timezone
from py_clob_client.client import ClobClient
from bedrock_parser import MarketParser
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

# --- INITIALIZE SYSTEM ---
def ensure_model_running(model_name="qwen2.5:14b", host="http://localhost:11434"):
    try:
        requests.get(f"{host}/api/ps")
        requests.post(f"{host}/api/generate", json={"model": model_name, "prompt": "", "keep_alive": "5m"})
        return True
    except: return False

ensure_model_running("qwen2.5:14b")

# --- SILENCE WARNINGS ---
warnings.filterwarnings('ignore')

# --- ARGUMENTS ---
parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC", choices=["BTC", "ETH", "SOL"])
args = parser.parse_args()

# --- LOGGING SETUP ---
LOG_DIR = os.path.join("src", "Polymarket", "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(LOG_DIR, f"trader_{args.asset}_{timestamp_str}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()]
)

# --- CONFIG ---
CURRENT_ASSET = args.asset
ASSET_MAP = {
    "BTC": {"ticker": "BTC-USD", "keywords": ["Bitcoin", "BTC"]},
    "ETH": {"ticker": "ETH-USD", "keywords": ["Ethereum", "ETH"]},
    "SOL": {"ticker": "SOL-USD", "keywords": ["Solana", "SOL"]}
}
CONFIG = ASSET_MAP[CURRENT_ASSET]

ASSET_TAGS_MAP = {
    "BTC": ["21", "235", "620"],
    "ETH": ["21", "157"],
    "SOL": ["21", "455"]
}
TARGET_TAGS = ASSET_TAGS_MAP[CURRENT_ASSET]

DATA_DIR = os.path.join("src", "Polymarket")
MODEL_PREFIX = os.path.join(DATA_DIR, f"model_{CURRENT_ASSET}_")
LOG_FILE = f"trades_{CURRENT_ASSET}.csv"
PENDING_DIR = os.path.join(DATA_DIR, "available_markets")

if not os.path.exists(PENDING_DIR): os.makedirs(PENDING_DIR)

NUM_MODELS = 5
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
FAKE_BALANCE = 5000.00
MAX_SPREAD_CENTS = 0.08
MIN_EDGE = 0.10 
MIN_BET = 5.00
MIN_LIQUIDITY = 5000.00
MIN_ODDS = 0.01  
MAX_ODDS = 0.90  

try: nltk.download('vader_lexicon', quiet=True)
except: pass

# --- HELPERS ---

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_live_market_data():
    try:
        tickers = [CONFIG['ticker'], "BTC-USD", "^IXIC"]
        tickers = list(set(tickers))
        raw_data = yf.download(tickers, period="5d", interval="1h", progress=False)['Close']
        df = raw_data.copy()
        
        target_col = CONFIG['ticker']
        df = df.dropna(subset=[target_col])

        if '^IXIC' in df.columns:
            df.loc[:, '^IXIC'] = df['^IXIC'].ffill()
        
        if len(df) < 50: return None
        
        latest = {}
        price_series = df[target_col]
        latest['price'] = float(price_series.iloc[-1])
        latest['rsi'] = float(calculate_rsi(price_series).iloc[-1])
        
        sma50 = price_series.rolling(50).mean().iloc[-1]
        latest['trend'] = (latest['price'] - sma50) / sma50
        latest['vol'] = float(price_series.pct_change(fill_method=None).rolling(24).std().iloc[-1])
        
        if "BTC-USD" in df.columns:
            btc_series = df['BTC-USD'].dropna()
            if len(btc_series) > 24:
                latest['btc_mom'] = float(btc_series.pct_change(24, fill_method=None).iloc[-1])
            else: latest['btc_mom'] = 0.0
        else: latest['btc_mom'] = 0.0
            
        if '^IXIC' in df.columns:
            latest['qqq_mom'] = float(df['^IXIC'].pct_change(24, fill_method=None).iloc[-1])
        else: latest['qqq_mom'] = 0.0
        
        return latest
    except Exception: return None

def calculate_kelly_bet(balance, prob, price):
    if prob <= price: return 0.0
    b = (1.0 - price) / price
    f = (b * prob - (1 - prob)) / b
    f_safe = f * 0.25 
    if f_safe <= 0: return 0.0
    return min(balance * f_safe, balance * 0.05)

def init_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(["Timestamp", "Question", "Side", "AI_Prob", "Price", "Edge", "Bet", "Moneyness", "RSI"])

def parse_group_title(title):
    try:
        title = title.lower().replace(",","").replace("$","").strip()
        if "-" in title:
            parts = title.split("-")
            low = float(parts[0].strip())
            high = float(parts[1].strip())
            return (low + high) / 2, 0 
        if "<" in title:
            val = float(title.replace("<","").strip())
            return val, -1 
        if ">" in title:
            val = float(title.replace(">","").strip())
            return val, 1 
    except: pass
    return None, None

def evaluate_side(side_name, ai_prob, market_price, ref_price, balance):
    # 1. Dead Book Check
    if market_price > 0.98 and ref_price < 0.90:
        return f"SKIP (Dead Book: Ask {market_price:.2f} vs Ref {ref_price:.3f} - No real liquidity)"
    
    # 2. Extreme Odds Filter
    if market_price < MIN_ODDS:
        return f"SKIP (Odds < {MIN_ODDS:.0%}: {market_price:.1%} - Too unlikely / Dead / Liquidity Dust)"
    if market_price > MAX_ODDS:
        return f"SKIP (Odds > {MAX_ODDS:.0%}: {market_price:.1%} - Too expensive / Upside is too small)"

    # 3. Edge Calculation
    edge = ai_prob - market_price
    if edge <= 0: return f"SKIP (Neg Edge {edge:.1%})"
    if edge < MIN_EDGE: return f"SKIP (Low Edge {edge:.1%})"
    
    # 4. Bet Sizing
    bet = calculate_kelly_bet(balance, ai_prob, market_price)
    if bet < MIN_BET: return f"SKIP (Bet ${bet:.2f} < Min)"
    
    return "BUY", bet, edge

# --- ANALYSIS ENGINE ---
def analyze_single_market_logic(m, parsed, data, models, client, global_balance):
    """
    Returns: (Action, Bet, Side, DetailsDict)
    """
    # Log to both file and console
    log_msg = f"🔍 Analyzing market: {m['question']}"
    logging.info("\n" + "=" * len(log_msg) + "\n" + log_msg + "\n" + "=" * len(log_msg) + "\n") 
    
    try:
        liquidity_val = float(m.get('liquidity', 0))
        logging.info(f"Market Liquidity: ${liquidity_val:,.0f}")
    except: pass

    # 1. Features
    target = parsed['target_price']
    direction = parsed.get('direction', 1)
    if target == "CURRENT_PRICE": target = data['price']
    
    if direction == 1: moneyness = np.log(data['price'] / target)
    elif direction == -1: moneyness = np.log(target / data['price'])
    else: moneyness = -abs(np.log(data['price'] / target))
    
    try:
        end_dt = pd.to_datetime(m.get('endDate')).replace(tzinfo=None)
        hours = (end_dt - datetime.now()).total_seconds() / 3600
        days_left = max(0.1, hours / 24.0)
    except: 
        result = {"valid": False, "reason": "Date Error"}
        return result

    features = pd.DataFrame([{
        'moneyness': moneyness, 'days_left': days_left, 'vol': data['vol'],
        'rsi': data['rsi'], 'trend': data['trend'],
        'btc_mom': data['btc_mom'], 'qqq_mom': data['qqq_mom']
    }])

    # 2. AI Prediction
    votes = [mod.predict_proba(features)[0][1] for mod in models]
    prob_yes = sum(votes) / len(votes)
    prob_no = 1.0 - prob_yes
    
    result = {
        "valid": True, 
        "outcome_label": m.get('groupItemTitle', 'Unknown'),
        "prob_yes": prob_yes, "prob_no": prob_no,
        "ask_yes": 0, "ask_no": 0,
        "edge_yes": 0, "edge_no": 0,
        "action": "SKIP", "reason": "",
        "token_yes": None, "token_no": None
    }

    # 3. Order Book Fetch
    try:
        tokens = m.get('clobTokenIds')
        if isinstance(tokens, str): tokens = json.loads(tokens)
        if not tokens or len(tokens) < 2:
            result["reason"] = "No Tokens"
            return result
        
        result["token_yes"] = tokens[0]
        result["token_no"] = tokens[1]

        # Get Prices
        try:
            ob_yes = client.get_order_book(tokens[0])
            result["ask_yes"] = float(ob_yes.asks[0].price) if ob_yes.asks else 0.0
        except: pass
        
        try:
            ob_no = client.get_order_book(tokens[1])
            result["ask_no"] = float(ob_no.asks[0].price) if ob_no.asks else 0.0
        except: pass

        # Get Reference for Dead Book check
        try:
            raw_ops = m.get('outcomePrices')
            if isinstance(raw_ops, str): ops = json.loads(raw_ops)
            else: ops = raw_ops
            ref_yes = float(ops[0])
            ref_no = float(ops[1])
        except: ref_yes, ref_no = 0.0, 0.0

        # Calc Edges (For table display)
        if result["ask_yes"] > 0: result["edge_yes"] = prob_yes - result["ask_yes"]
        if result["ask_no"] > 0: result["edge_no"] = prob_no - result["ask_no"]

        # Decisions
        res_yes = evaluate_side("YES", prob_yes, result["ask_yes"], ref_yes, global_balance)
        res_no = evaluate_side("NO", prob_no, result["ask_no"], ref_no, global_balance)

        if isinstance(res_yes, tuple) and res_yes[0] == "BUY":
            result["action"] = "BUY YES"
        elif isinstance(res_no, tuple) and res_no[0] == "BUY":
            result["action"] = "BUY NO"
        else:
            # KEEP FULL DETAIL FOR LOGGING, SHORTENER HANDLES TABLE
            result["reason"] = f"YES: {res_yes} | NO: {res_no}"

    except Exception as e:
        result["reason"] = f"Error: {e}"

    return result

# --- VISUALIZATION HELPER ---
def shorten_skip_reason(text):
    """
    Parses complex strings like 'YES: SKIP (Dead Book...) | NO: SKIP (Neg Edge...)'
    into 'SKIP (Yes-Dead Book | No-Neg Edge)'
    """
    if not text: return ""
    if "BUY" in text: return text
    
    try:
        parts = text.split(" | NO:")
        yes_full = parts[0].replace("YES: ", "")
        no_full = parts[1] if len(parts) > 1 else ""
        
        def extract_code(s):
            if "Dead Book" in s: return "Dead Book"
            if "Odds <" in s: return "Odds < 1%"
            if "Odds >" in s: return "Odds > 90%"
            if "Neg Edge" in s: return "Neg Edge"
            if "Low Edge" in s: return "Low Edge"
            if "Bet" in s: return "Small Bet"
            if "No Ask" in s: return "No Ask"
            if "No Orderbook" in s: return "No OB"
            return "Other"

        y_code = extract_code(yes_full)
        n_code = extract_code(no_full)
        
        return f"SKIP (Yes-{y_code}|No-{n_code})"
    except:
        return "SKIP"

def print_event_table(event_title, end_date, btc_price, asset_vol, rows):
    logging.info("\n" + "=" * 130)
    logging.info(f"📅 EVENT: {event_title}")
    logging.info(f"   End: {end_date} | BTC: ${btc_price:,.2f} | Asset Volatility: {asset_vol:.4f}")
    logging.info("-" * 130)
    
    # Headers
    logging.info(f"{'Outcome':<20} | {'AI Prob (Y/N)':<15} | {'Cost (Y/N)':<15} | {'Edge (Y/N)':<18} | {'Action':<50}")
    logging.info("-" * 130)
    
    for r in rows:
        outcome = r['outcome_label'][:20]
        ai_prob = f"{r['prob_yes']:.0%} / {r['prob_no']:.0%}"
        
        cost_y = f"{r['ask_yes']:.2f}" if r['ask_yes'] > 0 else "-"
        cost_n = f"{r['ask_no']:.2f}" if r['ask_no'] > 0 else "-"
        cost_str = f"{cost_y} / {cost_n}"
        
        edge_y = f"{r['edge_yes']:.1%}" if r['edge_yes'] != 0 else "-"
        edge_n = f"{r['edge_no']:.1%}" if r['edge_no'] != 0 else "-"
        edge_str = f"{edge_y} / {edge_n}"
        
        action = r['action']
        if action == "SKIP":
            # Apply Shortener for Table View ONLY
            action = shorten_skip_reason(r['reason'])
        
        if "BUY" in action:
             action = f"🔥 {action}"
        
        logging.info(f"{outcome:<20} | {ai_prob:<15} | {cost_str:<15} | {edge_str:<18} | {action:<50}")
    
    logging.info("=" * 130 + "\n")

def save_pending_opportunity(market, parsed_info):
    filename = os.path.join(PENDING_DIR, f"{market['conditionId']}.json")
    data = {"market": market, "parsed": parsed_info, "saved_at": datetime.now().isoformat()}
    with open(filename, 'w') as f: json.dump(data, f)
    logging.info(f"      💾 Saved opportunity to disk (Low Balance).")

def process_pending_markets(client, models, live_data):
    global FAKE_BALANCE
    files = glob.glob(os.path.join(PENDING_DIR, "*.json"))
    if not files: return
    
    logging.info(f"📂 Checking {len(files)} saved pending markets...")
    for filepath in files:
        if FAKE_BALANCE < MIN_BET: break 
        try:
            with open(filepath, 'r') as f: saved_data = json.load(f)
            m = saved_data['market']
            parsed = saved_data['parsed']
            
            res = analyze_single_market_logic(m, parsed, live_data, models, client, FAKE_BALANCE)
            
            if "BUY" in res["action"]:
                side = "YES" if "YES" in res["action"] else "NO"
                prob = res["prob_yes"] if side == "YES" else res["prob_no"]
                ask = res["ask_yes"] if side == "YES" else res["ask_no"]
                bet = calculate_kelly_bet(FAKE_BALANCE, prob, ask)
                if bet > MIN_BET:
                    logging.info(f"   🔥 [SAVED] EXECUTING {side}: {m['question'][:40]}...")
                    FAKE_BALANCE -= bet
                    with open(LOG_FILE, 'a', newline='') as f:
                        csv.writer(f).writerow([datetime.now(), m['question'], side, 
                                                f"{prob:.3f}", f"{ask:.3f}", 
                                                f"{res['edge_yes' if side=='YES' else 'edge_no']:.3f}", f"{bet:.2f}", 
                                                0, 0])
                    os.remove(filepath)
            elif res["action"] == "SKIP" and ("Dead Book" in res["reason"] or "Odds" in res["reason"]):
                os.remove(filepath)
        except: 
            try: os.remove(filepath)
            except: pass

def main():
    global FAKE_BALANCE
    logging.info(f"🚀 STARTING MULTI-TAG TRADER FOR: {CURRENT_ASSET}")
    logging.info(f"   Filters: Min Edge {MIN_EDGE:.0%}, Odds Range {MIN_ODDS:.0%}-{MAX_ODDS:.0%}")
    init_log()
    
    models = []
    for i in range(NUM_MODELS):
        try:
            m = xgb.XGBClassifier()
            m.load_model(f"{MODEL_PREFIX}{i}.json")
            models.append(m)
        except: pass
    
    if not models:
        logging.error(f"❌ No models found in {DATA_DIR}.")
        return

    llm_parser = MarketParser()
    client = ClobClient(HOST, chain_id=CHAIN_ID)

    while True:
        try:
            logging.info(f"\n--- SCANNING [Bal: ${FAKE_BALANCE:,.2f}] ---")
            data = get_live_market_data()
            if not data: 
                logging.warning("⚠️ Waiting for Yahoo Finance data...")
                time.sleep(10); continue
            
            logging.info(f"BTC Price: ${data['price']:,.2f} | RSI: {data['rsi']:.1f}")

            if FAKE_BALANCE > MIN_BET: process_pending_markets(client, models, data)

            total_events_scanned = 0

            for tag_id in TARGET_TAGS:
                offset = 0
                while True:
                    search_q = CONFIG['keywords'][0]
                    url = f"https://gamma-api.polymarket.com/events"
                    params = {
                        "active": "true", "closed": "false",
                        "tag_id": tag_id, "q": search_q,
                        "order": "volume", "ascending": "false",
                        "limit": 10, "offset": offset 
                    }
                    
                    resp = requests.get(url, params=params).json()
                    if not isinstance(resp, list) or len(resp) == 0: break 
                    
                    for event in resp:
                        total_events_scanned += 1
                        event_rows = []
                        valid_event_markets = False
                        
                        if not any(k.lower() in event['title'].lower() for k in CONFIG['keywords']):
                            continue
                        
                        logging.info(f"\n\n================================================================================================\n\n")
                        logging.info(f"\n\n🔎 EVENT: {event.get('title', 'Unknown')}\n\n")
                        markets = event.get('markets', [])
                        
                        for m in markets:
                            q_text = m.get('question', '')
                            
                            try:
                                liq = float(m.get('liquidity', 0))
                                if liq < MIN_LIQUIDITY: 
                                    logging.info(f"   ❌ SKIP MARKET: Low Liquidity (${liq:,.0f}) - {q_text}")
                                    continue
                            except: continue

                            if not any(k.lower() in q_text.lower() for k in CONFIG['keywords']):
                                logging.info(f"   ❌ SKIP MARKET: Keyword Mismatch - {q_text}")
                                continue
                            
                            try:
                                raw_outcomes = m.get('outcomes')
                                if isinstance(raw_outcomes, str): outcomes = json.loads(raw_outcomes)
                                else: outcomes = raw_outcomes
                                if not outcomes: continue
                                out_set = set(str(o).strip().lower() for o in outcomes)
                                valid_pairs = [{'yes', 'no'}, {'up', 'down'}, {'true', 'false'}]
                                if not any(out_set == pair for pair in valid_pairs): 
                                    logging.info(f"   ❌ SKIP MARKET: Invalid Outcomes {outcomes} - {q_text}")
                                    continue
                            except: continue

                            parsed = llm_parser.parse_question(q_text)
                            if not parsed or not isinstance(parsed.get('target_price'), (int, float)):
                                group_title = m.get('groupItemTitle', '')
                                if group_title:
                                    t_price, direction = parse_group_title(group_title)
                                    if t_price is not None:
                                        parsed = {"asset": CURRENT_ASSET, "target_price": t_price, "direction": direction}

                            if not parsed or parsed.get('asset') != CURRENT_ASSET: 
                                logging.info(f"   ❌ SKIP MARKET: Parser Rejected - {q_text}")
                                continue
                            
                            if not isinstance(parsed['target_price'], (int, float)) and parsed['target_price'] != "CURRENT_PRICE": 
                                logging.info(f"   ❌ SKIP MARKET: Invalid Target - {q_text}")
                                continue

                            # Analyze
                            row_result = analyze_single_market_logic(m, parsed, data, models, client, FAKE_BALANCE)
                            
                            if row_result["valid"]:
                                event_rows.append(row_result)
                                valid_event_markets = True
                                
                                # IMMEDIATE LOGGING
                                if "BUY" in row_result["action"]:
                                     logging.info(f"      ✅ DECISION: {row_result['action']}")
                                else:
                                     logging.info(f"      🛑 DECISION: {row_result['reason']}")
                                     if "Dead Book" in row_result["reason"]:
                                        logging.info(f"\n                  In a Dead Book, the Market Makers (professionals who provide liquidity) have left.\n                  The only orders remaining are 'Stub Quotes'—default orders set at the maximum price by bots or users who forgot about them.\n                  This is a sign of a market that is not being actively traded.\n                  We will not trade in this market.")
                                
                                # EXECUTION
                                if "BUY" in row_result["action"]:
                                    side = "YES" if "YES" in row_result["action"] else "NO"
                                    prob = row_result["prob_yes"] if side == "YES" else row_result["prob_no"]
                                    ask = row_result["ask_yes"] if side == "YES" else row_result["ask_no"]
                                    bet = calculate_kelly_bet(FAKE_BALANCE, prob, ask)
                                    
                                    if bet > MIN_BET:
                                        FAKE_BALANCE -= bet
                                        print(f"💰 EXECUTING TRADE: {side} on {row_result['outcome_label']} (${bet:.2f})")
                                        with open(LOG_FILE, 'a', newline='') as f:
                                            csv.writer(f).writerow([datetime.now(), m['question'], side, 
                                                                    f"{prob:.3f}", f"{ask:.3f}", 
                                                                    f"{row_result['edge_yes']:.3f}", f"{bet:.2f}", 
                                                                    0, 0])
                                    elif FAKE_BALANCE < MIN_BET:
                                        save_pending_opportunity(m, parsed)
                            else:
                                logging.info(f"   ❌ SKIP MARKET: Logic Invalid ({row_result['reason']}) - {q_text}")

                        # PRINT TABLE
                        if valid_event_markets:
                            print_event_table(event['title'], event.get('endDate', 'N/A')[:10], data['price'], data['vol'], event_rows)
                        else:
                            logging.info("   ℹ️ No valid price markets found in this event.")

                    offset += 10
                    time.sleep(0.5)
            
            if total_events_scanned == 0:
                logging.info("💤 No active events found. Sleeping 60s.")
                time.sleep(60)
            else:
                logging.info("🔄 Cycle complete. Restarting immediately...")
                time.sleep(1)

        except Exception as e:
            logging.error(f"Error: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    main()