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
CRYPTOPANIC_API_KEY = "YOUR_KEY"

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

def main():
    global FAKE_BALANCE
    print(f"🚀 STARTING BIDIRECTIONAL TRADER FOR: {CURRENT_ASSET}")
    init_log()
    
    models = []
    for i in range(NUM_MODELS):
        try:
            m = xgb.XGBClassifier()
            m.load_model(f"{MODEL_PREFIX}{i}.json")
            models.append(m)
        except: pass
    
    if not models:
        print(f"❌ No models found.")
        return

    llm_parser = MarketParser()
    client = ClobClient(HOST, chain_id=CHAIN_ID)

    while True:
        try:
            print(f"\n--- SCANNING {CURRENT_ASSET} [${FAKE_BALANCE:,.2f}] ---")
            data = get_live_market_data()
            if not data: time.sleep(10); continue
            
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"Price: ${data['price']:,.2f} | RSI: {data['rsi']:.1f} | Timestamp: {ts}")
            print(f"      ℹ️  Looking for 10% Edge on YES or NO (AI calculates its own probability based on 2 years of history and see if the winning probability is at least 10% better than what the market thinks (e.g. yes price is 60cent and Ai probability is 75%))")

            search_q = CONFIG['keywords'][0]
            resp = requests.get(f"https://gamma-api.polymarket.com/markets?active=true&closed=false&q={search_q}&limit=30").json()
            
            for m in resp:
                q_text = m['question']
                if not any(k in q_text for k in CONFIG['keywords']): continue
                
                parsed = llm_parser.parse_question(q_text)
                if not parsed or parsed['asset'] != CURRENT_ASSET: continue
                
                target = parsed['target_price']
                direction = parsed.get('direction', 1)
                
                if target == "CURRENT_PRICE": target = data['price']
                
                if direction == 1: moneyness = np.log(data['price'] / target)
                elif direction == -1: moneyness = np.log(target / data['price'])
                else: moneyness = -abs(np.log(data['price'] / target))
                
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

                # AI Prediction is probability of YES (1)
                votes = [mod.predict_proba(features)[0][1] for mod in models]
                prob_yes = sum(votes) / len(votes)
                prob_no = 1.0 - prob_yes

                if not m.get('clobTokenIds') or len(m['clobTokenIds']) < 2: continue
                
                # --- CHECK YES SIDE ---
                token_yes = m['clobTokenIds'][0]
                try:
                    ob_yes = client.get_order_book(token_yes)
                    if ob_yes.asks:
                        ask_yes = float(ob_yes.asks[0].price)
                        edge_yes = prob_yes - ask_yes
                        
                        if edge_yes > 0.10:
                            bet = calculate_kelly_bet(FAKE_BALANCE, prob_yes, ask_yes)
                            if bet > 5:
                                print(f"   🔥 BUY YES: {q_text[:40]}... (AI: {prob_yes:.2f} vs {ask_yes:.2f})")
                                FAKE_BALANCE -= bet
                                with open(LOG_FILE, 'a', newline='') as f:
                                    csv.writer(f).writerow([
                                        datetime.now(), m['question'], "YES", f"{prob_yes:.3f}", f"{ask_yes:.3f}", 
                                        f"{edge_yes:.3f}", f"{bet:.2f}", f"{moneyness:.3f}", f"{data['rsi']:.1f}"
                                    ])
                except: pass

                # --- CHECK NO SIDE ---
                token_no = m['clobTokenIds'][1]
                try:
                    ob_no = client.get_order_book(token_no)
                    if ob_no.asks:
                        ask_no = float(ob_no.asks[0].price)
                        edge_no = prob_no - ask_no
                        
                        if edge_no > 0.10:
                            bet = calculate_kelly_bet(FAKE_BALANCE, prob_no, ask_no)
                            if bet > 5:
                                print(f"   🔥 BUY NO: {q_text[:40]}... (AI: {prob_no:.2f} vs {ask_no:.2f})")
                                FAKE_BALANCE -= bet
                                with open(LOG_FILE, 'a', newline='') as f:
                                    csv.writer(f).writerow([
                                        datetime.now(), m['question'], "NO", f"{prob_no:.3f}", f"{ask_no:.3f}", 
                                        f"{edge_no:.3f}", f"{bet:.2f}", f"{moneyness:.3f}", f"{data['rsi']:.1f}"
                                    ])
                except: pass
        
        except Exception as e:
            print(f"Loop Error: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    main()