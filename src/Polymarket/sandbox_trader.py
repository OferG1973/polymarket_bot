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
from datetime import datetime
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

DATA_DIR = os.path.join("src", "Polymarket")
MODEL_PREFIX = os.path.join(DATA_DIR, f"model_{CURRENT_ASSET}_")
LOG_FILE = f"trades_{CURRENT_ASSET}.csv"
NUM_MODELS = 5

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
FAKE_BALANCE = 5000.00
MAX_SPREAD_CENTS = 0.08
MIN_EDGE = 0.10 
MIN_BET = 5.00

try: nltk.download('vader_lexicon', quiet=True)
except: pass

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

def evaluate_side(side_name, ai_prob, market_price, balance, question_text):
    edge = ai_prob - market_price
    if edge <= 0: return f"SKIP (Neg Edge {edge:.1%})"
    if edge < MIN_EDGE: return f"SKIP (Edge {edge:.1%} < {MIN_EDGE:.0%})"
    bet = calculate_kelly_bet(balance, ai_prob, market_price)
    if bet < MIN_BET: return f"SKIP (Bet ${bet:.2f} < ${MIN_BET})"
    return "BUY", bet, edge

def main():
    global FAKE_BALANCE
    logging.info(f"🚀 STARTING TRADER FOR: {CURRENT_ASSET}")
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
            logging.info(f"\n--- SCANNING {CURRENT_ASSET} [${FAKE_BALANCE:,.2f}] ---")
            data = get_live_market_data()
            if not data: 
                logging.warning("⚠️ Waiting for Yahoo Finance data...")
                time.sleep(10); continue
            
            logging.info(f"Price: ${data['price']:,.2f} | RSI: {data['rsi']:.1f}")
            logging.info(f"      ℹ️  Targeting: AI Probability > Market Price + 10% (Edge)")

            # Fetch active markets
            search_q = CONFIG['keywords'][0]
            url = f"https://gamma-api.polymarket.com/markets?active=true&closed=false&q={search_q}&limit=50&tag_id=235"
            resp = requests.get(url).json()
            
            if not isinstance(resp, list):
                logging.error(f"⚠️ API Error: Expected list, got {type(resp)}")
                resp = []

            logging.info(f"      API returned {len(resp)} potential markets.")
            
            scanned_count = 0
            for m in resp:
                q_text = m.get('question', '')
                raw_outcomes = m.get('outcomes')
                
                # Check if market endDate is more than 24 hours from now
                end_date_str = m.get('endDate')
                if end_date_str:
                    try:
                        # Parse endDate string to datetime
                        end_dt = datetime.fromisoformat(end_date_str.replace('Z','+00:00')) if 'Z' in end_date_str else datetime.fromisoformat(end_date_str)
                        now = datetime.utcnow()
                        # If using timezone-aware, convert now to UTC and ignore tz if end_dt is naive
                        if end_dt.tzinfo is not None and end_dt.utcoffset() is not None:
                            now = datetime.now(end_dt.tzinfo)
                        delta = (end_dt - now).total_seconds()
                        if delta > 24 * 3600:
                            logging.info(f"      ⏳ [SKIP] Market ends in more than 24 hours: {end_date_str}")
                            continue
                    except Exception as e:
                        logging.info(f"      ⚠️ [WARN] Could not parse endDate: {end_date_str} ({e})")


                # --- VERBOSE RAW LOG ---
                # Log outcome formatting to debug weird JSON strings
                logging.info(f"   🔹 RAW: {q_text[:70]}... | Outcomes: {str(raw_outcomes)[:50]}")

                # --- FILTER 1: KEYWORD ---
                if not any(k.lower() in q_text.lower() for k in CONFIG['keywords']):
                    logging.info(f"      ❌ [SKIP] Keyword mismatch")
                    continue
                
                # --- FILTER 2: VALIDATE OUTCOMES ---
                try:
                    if isinstance(raw_outcomes, str):
                        outcomes = json.loads(raw_outcomes)
                    else:
                        outcomes = raw_outcomes
                    
                    if not outcomes:
                        logging.info(f"      ❌ [SKIP] Outcomes empty")
                        continue

                    # Normalize to lowercase set
                    out_set = set(str(o).strip().lower() for o in outcomes)
                    
                    # Allowed Outcome Pairs
                    valid_pairs = [
                        {'yes', 'no'},
                        {'up', 'down'},
                        {'true', 'false'}
                    ]
                    
                    if not any(out_set == pair for pair in valid_pairs):
                        logging.info(f"      ❌ [SKIP] Invalid Outcomes: {out_set}")
                        continue
                        
                except Exception as e:
                    logging.info(f"      ❌ [SKIP] Outcome parse error: {e}")
                    continue

                # --- FILTER 3: PARSER ---
                parsed = llm_parser.parse_question(q_text)
                
                if not parsed:
                    logging.info(f"      ❌ [SKIP] Parser Failed (No Target/Asset found)")
                    continue
                
                if parsed.get('asset') != CURRENT_ASSET:
                    logging.info(f"      ❌ [SKIP] Wrong Asset: {parsed.get('asset')}")
                    continue
                
                # --- FILTER 4: TARGET TYPE CHECK ---
                if parsed['target_price'] == "CURRENT_PRICE":
                    pass 
                elif not isinstance(parsed['target_price'], (int, float)):
                    logging.info(f"      ❌ [SKIP] Invalid Target Price: {parsed['target_price']}")
                    continue

                # --- SUCCESSFUL VALIDATION ---
                scanned_count += 1
                logging.info(f"      ✅ ANALYZING MATH...")

                target = parsed['target_price']
                direction = parsed.get('direction', 1)
                
                if target == "CURRENT_PRICE": target = data['price']
                
                # Calc Moneyness
                if direction == 1: moneyness = np.log(data['price'] / target)
                elif direction == -1: moneyness = np.log(target / data['price'])
                else: moneyness = -abs(np.log(data['price'] / target))
                
                try:
                    end_dt = pd.to_datetime(m['endDate']).replace(tzinfo=None)
                    hours = (end_dt - datetime.now()).total_seconds() / 3600
                    days_left = max(0.1, hours / 24.0)
                except: 
                    logging.info(f"      ❌ [SKIP] Date Error")
                    continue

                features = pd.DataFrame([{
                    'moneyness': moneyness,
                    'days_left': days_left,
                    'vol': data['vol'],
                    'rsi': data['rsi'],
                    'trend': data['trend'],
                    'btc_mom': data['btc_mom'],
                    'qqq_mom': data['qqq_mom']
                }])

                # AI Vote
                votes = [mod.predict_proba(features)[0][1] for mod in models]
                prob_yes = sum(votes) / len(votes)
                prob_no = 1.0 - prob_yes

                if not m.get('clobTokenIds') or len(m['clobTokenIds']) < 2: 
                    logging.info(f"      ⚠️ [SKIP] No Orderbook Tokens.")
                    continue
                
                # --- EVALUATE YES ---
                token_yes = m['clobTokenIds'][0]
                try:
                    ob = client.get_order_book(token_yes)
                    if ob.asks:
                        ask = float(ob.asks[0].price)
                        res = evaluate_side("YES", prob_yes, ask, FAKE_BALANCE, q_text)
                        
                        if isinstance(res, tuple) and res[0] == "BUY":
                            _, bet, edge = res
                            logging.info(f"      🔥 BUY YES: AI {prob_yes:.2f} vs {ask:.2f} | Edge {edge:.1%} | Bet ${bet:.2f}")
                            FAKE_BALANCE -= bet
                            with open(LOG_FILE, 'a', newline='') as f:
                                csv.writer(f).writerow([datetime.now(), m['question'], "YES", f"{prob_yes:.3f}", f"{ask:.3f}", f"{edge:.3f}", f"{bet:.2f}", f"{moneyness:.3f}", f"{data['rsi']:.1f}"])
                        else:
                            logging.info(f"      • YES: AI {prob_yes:.2f} vs Mkt {ask:.2f} -> {res}")
                    else:
                        logging.info("      • YES: No Sellers (Empty Book)")
                except Exception as e:
                    if "No orderbook exists" in str(e):
                        logging.info("      • YES: Orderbook not initialized")
                    else:
                        logging.error(f"      ❌ YES Error: {e}")

                # --- EVALUATE NO ---
                token_no = m['clobTokenIds'][1]
                try:
                    ob = client.get_order_book(token_no)
                    if ob.asks:
                        ask = float(ob.asks[0].price)
                        res = evaluate_side("NO", prob_no, ask, FAKE_BALANCE, q_text)
                        
                        if isinstance(res, tuple) and res[0] == "BUY":
                            _, bet, edge = res
                            logging.info(f"      🔥 BUY NO: AI {prob_no:.2f} vs {ask:.2f} | Edge {edge:.1%} | Bet ${bet:.2f}")
                            FAKE_BALANCE -= bet
                            with open(LOG_FILE, 'a', newline='') as f:
                                csv.writer(f).writerow([datetime.now(), m['question'], "NO", f"{prob_no:.3f}", f"{ask:.3f}", f"{edge:.3f}", f"{bet:.2f}", f"{moneyness:.3f}", f"{data['rsi']:.1f}"])
                        else:
                            logging.info(f"      • NO:  AI {prob_no:.2f} vs Mkt {ask:.2f} -> {res}")
                    else:
                        logging.info("      • NO:  No Sellers (Empty Book)")
                except Exception as e:
                    if "No orderbook exists" in str(e):
                        logging.info("      • NO:  Orderbook not initialized")
                    else:
                        logging.error(f"      ❌ NO Error: {e}")
            
            if scanned_count == 0:
                logging.warning("   ⚠️ No valid price markets found in this batch.")

        except Exception as e:
            logging.error(f"❌ Loop Error: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    main()