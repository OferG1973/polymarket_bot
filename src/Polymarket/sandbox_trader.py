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
from datetime import datetime
from py_clob_client.client import ClobClient
from bedrock_parser import MarketParser
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

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
            logging.info(f"ℹ️  The RSI (Relative Strength Index) is calculated by comparing the Average Gains vs. the Average Losses over a specific lookback period\n (in your bot's case, 14 hours). The RSI is used to measure the speed and magnitude of price\n changes, helping to identify overbought or oversold conditions.\nIf Buyers pull 5 times harder than Sellers, RSI is high (>70).\nIf Sellers pull 5 times harder than Buyers, RSI is low (<30).\nIf they pull equally, RSI is 50.\nAn RSI of 83.33 means buying pressure is massive compared to selling pressure. The asset is \"Overbought\" and typically due for a correction.\nHence market will shortly start to go down")
            logging.info(f"ℹ️  Looking for 10% Edge on YES or NO")

            data = get_live_market_data()
            if not data: 
                logging.warning("⚠️ Waiting for Yahoo Finance data...")
                time.sleep(10); continue
            
            logging.info(f"Price: ${data['price']:,.2f} | RSI: {data['rsi']:.1f}")

            # Fetch active markets
            search_q = CONFIG['keywords'][0]
            url = f"https://gamma-api.polymarket.com/markets?active=true&closed=false&q={search_q}&limit=50"
            resp = requests.get(url).json()
            
            if not isinstance(resp, list):
                logging.error(f"⚠️ API Error: Expected list, got {type(resp)}")
                resp = []

            logging.info(f"      API returned {len(resp)} potential markets.")
            
            scanned_count = 0
            for m in resp:
                q_text = m.get('question', '')
                
                # --- FILTER 1: KEYWORD ---
                # Fixed: Lowercase both for safety
                if not any(k.lower() in q_text.lower() for k in CONFIG['keywords']):
                    continue
                
                # --- FILTER 2: PARSER ---
                parsed = llm_parser.parse_question(q_text)
                if not parsed or parsed['asset'] != CURRENT_ASSET:
                    # logging.info(f"      [SKIP] Parser: {q_text[:30]}...") # Uncomment for deep debug
                    continue
                
                scanned_count += 1
                logging.info(f"   🔎 ANALYZING: {q_text}")

                target = parsed['target_price']
                direction = parsed.get('direction', 1)
                
                if target == "CURRENT_PRICE": target = data['price']
                
                # Calc Moneyness
                if direction == 1: moneyness = np.log(data['price'] / target)
                elif direction == -1: moneyness = np.log(target / data['price'])
                else: moneyness = -abs(np.log(data['price'] / target))
                
                # Calc Time
                try:
                    end_dt = pd.to_datetime(m['endDate']).replace(tzinfo=None)
                    hours = (end_dt - datetime.now()).total_seconds() / 3600
                    days_left = max(0.1, hours / 24.0)
                except: continue

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
                    logging.info(f"      ⚠️ No Token IDs found.")
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
                            logging.info(f"      ✅ BUY YES: AI {prob_yes:.2f} vs {ask:.2f} | Edge {edge:.1%} | Bet ${bet:.2f}")
                            FAKE_BALANCE -= bet
                            with open(LOG_FILE, 'a', newline='') as f:
                                csv.writer(f).writerow([datetime.now(), m['question'], "YES", f"{prob_yes:.3f}", f"{ask:.3f}", f"{edge:.3f}", f"{bet:.2f}", f"{moneyness:.3f}", f"{data['rsi']:.1f}"])
                        else:
                            logging.info(f"      • YES: AI {prob_yes:.2f} vs {ask:.2f} -> {res}")
                    else:
                        logging.info("      • YES: No Sellers (Empty Book)")
                except: pass

                # --- EVALUATE NO ---
                token_no = m['clobTokenIds'][1]
                try:
                    ob = client.get_order_book(token_no)
                    if ob.asks:
                        ask = float(ob.asks[0].price)
                        res = evaluate_side("NO", prob_no, ask, FAKE_BALANCE, q_text)
                        
                        if isinstance(res, tuple) and res[0] == "BUY":
                            _, bet, edge = res
                            logging.info(f"      ✅ BUY NO: AI {prob_no:.2f} vs {ask:.2f} | Edge {edge:.1%} | Bet ${bet:.2f}")
                            FAKE_BALANCE -= bet
                            with open(LOG_FILE, 'a', newline='') as f:
                                csv.writer(f).writerow([datetime.now(), m['question'], "NO", f"{prob_no:.3f}", f"{ask:.3f}", f"{edge:.3f}", f"{bet:.2f}", f"{moneyness:.3f}", f"{data['rsi']:.1f}"])
                        else:
                            logging.info(f"      • NO:  AI {prob_no:.2f} vs {ask:.2f} -> {res}")
                    else:
                        logging.info("      • NO:  No Sellers (Empty Book)")
                except: pass
            
            if scanned_count == 0:
                logging.warning("   ⚠️ No valid price markets found in this batch (Parser rejected all).")

        except Exception as e:
            logging.error(f"❌ Loop Error: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    main()