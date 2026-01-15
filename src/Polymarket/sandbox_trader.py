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

# AWS credentials should be set via environment variables or AWS credentials file
# Set these in your environment or use: export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
# Or use AWS credentials file at ~/.aws/credentials
if not os.environ.get("AWS_ACCESS_KEY_ID"):
    raise ValueError("AWS_ACCESS_KEY_ID environment variable not set. Please set it before running.")
if not os.environ.get("AWS_SECRET_ACCESS_KEY"):
    raise ValueError("AWS_SECRET_ACCESS_KEY environment variable not set. Please set it before running.")
if not os.environ.get("AWS_DEFAULT_REGION"):
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


# Run Ollama Qwen 2.5:14b model for local LLM
def ensure_model_running(model_name="qwen2.5:14b", host="http://localhost:11434"):
    try:
        # 1. Check currently loaded models
        response = requests.get(f"{host}/api/ps")
        response.raise_for_status()
        
        running_models = [m['name'] for m in response.json().get('models', [])]
        
        # Ollama sometimes returns names like 'qwen2.5:14b-instruct', so we check if our string is in there
        if any(model_name in running for running in running_models):
            print(f"✅ Model '{model_name}' is already running.")
            return True
        
        # 2. If not running, trigger a load
        print(f"⏳ Model '{model_name}' not loaded. Initializing...")
        
        # We send an empty prompt with keep_alive to force it into VRAM
        # keep_alive: -1 keeps it running indefinitely, or use "5m" for 5 minutes
        requests.post(f"{host}/api/generate", json={
            "model": model_name, 
            "prompt": "", 
            "keep_alive": "5m" 
        })
        
        print(f"🚀 Model '{model_name}' has been started.")
        return True

    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to Ollama. Is the Ollama app/service running?")
        return False
    except Exception as e:
        print(f"❌ An error occurred: {e}")
        return False

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
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

# --- CONFIG ---
CURRENT_ASSET = args.asset
ASSET_MAP = {
    "BTC": {"ticker": "BTC-USD", "keywords": ["Bitcoin", "BTC"]},
    "ETH": {"ticker": "ETH-USD", "keywords": ["Ethereum", "ETH"]},
    "SOL": {"ticker": "SOL-USD", "keywords": ["Solana", "SOL"]}
}
CONFIG = ASSET_MAP[CURRENT_ASSET]

# Specific Tag IDs for deep scanning
# 21 = Crypto (General)
# 235 = Bitcoin, 620 = Bitcoin (Alt tag)
# 157 = Ethereum
# 455 = Solana
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

if not os.path.exists(PENDING_DIR):
    os.makedirs(PENDING_DIR)

NUM_MODELS = 5
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
FAKE_BALANCE = 5000.00
MAX_SPREAD_CENTS = 0.08
MIN_EDGE = 0.10 
MIN_BET = 5.00
MIN_LIQUIDITY = 5000.00  # Only look at markets with > $5,000 liquidity

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

def save_pending_opportunity(market, parsed_info):
    """Saves market to disk when we don't have money"""
    # Use conditionId as filename to ensure uniqueness
    filename = os.path.join(PENDING_DIR, f"{market['conditionId']}.json")
    data = {
        "market": market,
        "parsed": parsed_info,
        "saved_at": datetime.now().isoformat()
    }
    with open(filename, 'w') as f:
        json.dump(data, f)
    logging.info(f"      💾 Saved opportunity to disk (Low Balance).")

# --- UPDATED EVALUATE SIDE (Includes Reference Price Logic) ---
def evaluate_side(side_name, ai_prob, market_price, ref_price, balance, question_text):
    # Detect Dead Book: If Ask is > 0.98 but Reference Price is < 0.90, it's illiquid junk.
    if market_price > 0.98 and ref_price < 0.90:
        return f"SKIP (Dead Book: Ask {market_price:.2f} vs Ref {ref_price:.3f})"

    edge = ai_prob - market_price
    if edge <= 0: return f"SKIP (Neg Edge {edge:.1%})"
    if edge < MIN_EDGE: return f"SKIP (Edge {edge:.1%} < {MIN_EDGE:.0%})"
    bet = calculate_kelly_bet(balance, ai_prob, market_price)
    # Return numerical bet even if it's 0, handled by caller
    return "BUY", bet, edge

# --- CORE ANALYSIS FUNCTION ---
# This is extracted so we can use it for both Live and Saved markets
def analyze_single_market(m, parsed, data, models, client, global_balance):
    """
    Returns: (Action, Bet, Side, DetailsDict)
    Action: "EXECUTE", "SAVE", "SKIP"
    """
    # Log to both file and console
    log_msg = f"🔍 Analyzing market: {m['question']}"
    logging.info("\n" + "=" * len(log_msg) + "\n" + log_msg + "\n" + "=" * len(log_msg) + "\n") 
    
    try:
        liquidity_val = float(m.get('liquidity', 0))
        market_liquidity_str = f"Market Liquidity: ${liquidity_val:,.0f}"
    except Exception:
        market_liquidity_str = f"Market Liquidity: {m.get('liquidity', 0)}"

    try:
        end_date = m.get('endDate')
        end_dt = pd.to_datetime(end_date).replace(tzinfo=None)
        hours = (end_dt - datetime.now()).total_seconds() / 3600
        days_left = max(0.1, hours / 24.0)
        market_end_date_str = f"Market End Date: {days_left:.1f} days left\n\n"
    except Exception:
        market_end_date_str = f"Market End Date: {m.get('endDate')}\n\n"

    logging.info(market_liquidity_str)
    logging.info(market_end_date_str)

    # 1. Build Features
    target = parsed['target_price']
    direction = parsed.get('direction', 1)
    
    if target == "CURRENT_PRICE": target = data['price']
    
    if direction == 1: moneyness = np.log(data['price'] / target)
    elif direction == -1: moneyness = np.log(target / data['price'])
    else: moneyness = -abs(np.log(data['price'] / target))
    
    try:
        end_date = m.get('endDate')
        end_dt = pd.to_datetime(end_date).replace(tzinfo=None)
        hours = (end_dt - datetime.now()).total_seconds() / 3600
        days_left = max(0.1, hours / 24.0)
    except: 
        return "SKIP", 0, None, "Date Error"

    features = pd.DataFrame([{
        'moneyness': moneyness,
        'days_left': days_left,
        'vol': data['vol'],
        'rsi': data['rsi'],
        'trend': data['trend'],
        'btc_mom': data['btc_mom'],
        'qqq_mom': data['qqq_mom']
    }])

    # 2. AI Vote
    votes = [mod.predict_proba(features)[0][1] for mod in models]
    prob_yes = sum(votes) / len(votes)
    prob_no = 1.0 - prob_yes

    # 3. Check Order Book
    try:
        # Handle cases where tokens might be stored differently
        tokens = m.get('clobTokenIds')
        if isinstance(tokens, str): tokens = json.loads(tokens)
        
        if not tokens or len(tokens) < 2:
            return "SKIP", 0, None, "No Tokens"
            
        token_yes = tokens[0]
        token_no = tokens[1]
    except: return "SKIP", 0, None, "Token Parse Error"

    # --- GET REFERENCE PRICES FOR DEAD BOOK CHECK ---
    try:
        raw_ops = m.get('outcomePrices')
        if isinstance(raw_ops, str): ops = json.loads(raw_ops)
        else: ops = raw_ops
        ref_yes = float(ops[0])
        ref_no = float(ops[1])
    except:
        ref_yes = 0.0
        ref_no = 0.0

    # Track reasons for rejection if we don't buy
    yes_status = "No Ask Found"
    no_status = "No Ask Found"

    # --- EVALUATE YES ---
    try:
        ob_yes = client.get_order_book(token_yes)
        if ob_yes.asks:
            ask_yes = float(ob_yes.asks[0].price)
            res = evaluate_side("YES", prob_yes, ask_yes, ref_yes, global_balance, m['question'])
            
            # If Buy
            if isinstance(res, tuple) and res[0] == "BUY":
                action, bet, edge = res
                details = {"side": "YES", "prob": prob_yes, "price": ask_yes, "edge": edge, "bet": bet, "rsi": data['rsi'], "moneyness": moneyness}
                
                if bet > MIN_BET:
                    return "EXECUTE", bet, "YES", details
                else:
                    if global_balance < MIN_BET:
                        return "SAVE", 0, "YES", details
                    return "SKIP", 0, "YES", "Bet too small (Kelly)"
            
            # If Skip, save specific reason
            yes_status = f"AI:{prob_yes:.2f}/Mkt:{ask_yes:.2f} (Ref:{ref_yes:.3f}) -> {res}"
            
    except Exception as e:
        if "No orderbook" in str(e): yes_status = "No Orderbook"
        else: logging.error(f"Error YES OB: {e}")

    # --- EVALUATE NO ---
    try:
        ob_no = client.get_order_book(token_no)
        if ob_no.asks:
            ask_no = float(ob_no.asks[0].price)
            res = evaluate_side("NO", prob_no, ask_no, ref_no, global_balance, m['question'])
            
            # If Buy
            if isinstance(res, tuple) and res[0] == "BUY":
                action, bet, edge = res
                details = {"side": "NO", "prob": prob_no, "price": ask_no, "edge": edge, "bet": bet, "rsi": data['rsi'], "moneyness": moneyness}
                
                if bet > MIN_BET:
                    return "EXECUTE", bet, "NO", details
                else:
                    if global_balance < MIN_BET:
                        return "SAVE", 0, "NO", details
                    return "SKIP", 0, "NO", "Bet too small (Kelly)"
            
            # If Skip, save specific reason
            no_status = f"AI:{prob_no:.2f}/Mkt:{ask_no:.2f} (Ref:{ref_no:.3f}) -> {res}"

    except Exception as e:
        if "No orderbook" in str(e): no_status = "No Orderbook"
        else: logging.error(f"Error NO OB: {e}")

    # If we reached here, neither side was a buy. Return detailed reasons.
    detailed_reason = f"No Edge. YES[{yes_status}] | NO[{no_status}]"
    return "SKIP", 0, None, detailed_reason

def process_pending_markets(client, models, live_data):
    """
    Checks the 'available_markets' folder. Re-analyzes files.
    If traded, delete file. If expired/bad, delete file.
    """
    global FAKE_BALANCE
    files = glob.glob(os.path.join(PENDING_DIR, "*.json"))
    
    if not files: return
    
    logging.info(f"📂 Checking {len(files)} saved pending markets...")
    
    for filepath in files:
        if FAKE_BALANCE < MIN_BET:
            break # Still broke, stop checking
            
        try:
            with open(filepath, 'r') as f:
                saved_data = json.load(f)
            
            m = saved_data['market']
            parsed = saved_data['parsed']
            
            # Re-Run Analysis
            action, bet, side, details = analyze_single_market(m, parsed, live_data, models, client, FAKE_BALANCE)
            
            if action == "EXECUTE":
                logging.info(f"   🔥 [SAVED] EXECUTING {side}: {m['question'][:40]}...")
                FAKE_BALANCE -= bet
                with open(LOG_FILE, 'a', newline='') as f:
                    csv.writer(f).writerow([datetime.now(), m['question'], side, 
                                            f"{details['prob']:.3f}", f"{details['price']:.3f}", 
                                            f"{details['edge']:.3f}", f"{bet:.2f}", 
                                            f"{details['moneyness']:.3f}", f"{details['rsi']:.1f}"])
                # Trade done, delete file
                os.remove(filepath)
            
            elif action == "SKIP":
                os.remove(filepath)
                
        except Exception as e:
            logging.error(f"Error processing saved file {filepath}: {e}")
            try: os.remove(filepath)
            except: pass

def main():
    global FAKE_BALANCE
    logging.info(f"🚀 STARTING MULTI-TAG TRADER FOR: {CURRENT_ASSET}")
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
            logging.info(f"\n--- STARTING CYCLE [Bal: ${FAKE_BALANCE:,.2f}] ---")
            
            # 1. Get Live Data Once per Cycle
            data = get_live_market_data()
            if not data: 
                logging.warning("⚠️ Waiting for Yahoo Finance data...")
                time.sleep(10); continue
            
            logging.info(f"BTC Price: ${data['price']:,.2f} | RSI: {data['rsi']:.1f}")

            # 2. Check Pending Markets First (If we have money)
            if FAKE_BALANCE > MIN_BET:
                process_pending_markets(client, models, data)

            total_markets_found = 0

            # 3. Iterate Tags
            for tag_id in TARGET_TAGS:
                offset = 0
                logging.info(f"👉 Scanning Tag {tag_id}...")
                
                while True: # Pagination Loop
                    # Fetch
                    search_q = CONFIG['keywords'][0]
                    url = f"https://gamma-api.polymarket.com/markets"
                    params = {
                        "active": "true", "closed": "false",
                        "tag_id": tag_id,
                        "q": search_q,
                        "order": "liquidity", # <--- Sort by Liquidity to find good markets first
                        "ascending": "false",
                        "limit": 50, "offset": offset
                    }
                    
                    resp = requests.get(url, params=params).json()
                    
                    if not isinstance(resp, list) or len(resp) == 0:
                        break # End of this tag
                    
                    total_markets_found += len(resp)
                    
                    for m in resp:
                        q_text = m.get('question', '')
                        
                        # Filter 0: Liquidity
                        try:
                            liq = float(m.get('liquidity', 0))
                            if liq < MIN_LIQUIDITY:
                                logging.info(f"   [SKIP] Low Liquidity: ${liq:,.0f} for market: {q_text}")
                                continue
                        except Exception as e: 
                            continue

                        # Filter 1: Keyword
                        if not any(k.lower() in q_text.lower() for k in CONFIG['keywords']):
                            continue
                        
                        # Filter 2: Validate Outcomes
                        try:
                            raw_outcomes = m.get('outcomes')
                            if isinstance(raw_outcomes, str): outcomes = json.loads(raw_outcomes)
                            else: outcomes = raw_outcomes
                            if not outcomes: continue
                            out_set = set(str(o).strip().lower() for o in outcomes)
                            valid_pairs = [{'yes', 'no'}, {'up', 'down'}, {'true', 'false'}]
                            if not any(out_set == pair for pair in valid_pairs):
                                logging.info(f"   [SKIP] Bad Outcomes: {outcomes} for market: {q_text}")
                                continue
                        except: continue

                        # Filter 3: Parser
                        parsed = llm_parser.parse_question(q_text)
                        if not parsed or parsed['asset'] != CURRENT_ASSET:
                            continue
                        
                        if not isinstance(parsed['target_price'], (int, float)) and parsed['target_price'] != "CURRENT_PRICE":
                            continue

                        # Analyze
                        action, bet, side, details = analyze_single_market(m, parsed, data, models, client, FAKE_BALANCE)
                        
                        if action == "EXECUTE":
                            logging.info(f"   🔥 BUY {side}: {q_text[:40]}... (Edge {details['edge']:.1%})")
                            FAKE_BALANCE -= bet
                            with open(LOG_FILE, 'a', newline='') as f:
                                csv.writer(f).writerow([datetime.now(), m['question'], side, 
                                                        f"{details['prob']:.3f}", f"{details['price']:.3f}", 
                                                        f"{details['edge']:.3f}", f"{bet:.2f}", 
                                                        f"{details['moneyness']:.3f}", f"{details['rsi']:.1f}"])
                        
                        elif action == "SAVE":
                            save_pending_opportunity(m, parsed)
                        
                        elif action == "SKIP":
                            if "Orderbook" not in str(details) and "Token" not in str(details):
                                logging.info(f"   [SKIP] {q_text[:40]}... Reason: {details}")

                    # Pagination increment
                    offset += 50
                    time.sleep(0.2) # Small delay between pages
            
            # 4. End of Cycle Logic
            if total_markets_found == 0:
                logging.info("💤 No markets found in any tag. Sleeping 60s.")
                time.sleep(60)
            else:
                logging.info("🔄 Cycle complete. Restarting immediately...")
                time.sleep(1)

        except Exception as e:
            logging.error(f"❌ Critical Loop Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()