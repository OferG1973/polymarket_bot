import time
import pandas as pd
import xgboost as xgb
import yfinance as yf
import requests
import argparse
import numpy as np
import os
import logging
from datetime import datetime
from futures_pipeline import get_target_pct_and_lookahead_hours


parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

# --- LOGGING SETUP ---
LOG_DIR = os.path.join("/Volumes/SanDisk_Extreme_SSD", "workingFolder", "binance_futures", "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# One main log file for the trader session, plus CSV for trade history
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(LOG_DIR, f"trader_{args.asset}_{timestamp_str}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s', # Simple format for trading logs
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

# --- PATH CONFIGURATION ---
DATA_DIR = os.path.join("src", "Binance_Futures")
MODEL_PREFIX = os.path.join(DATA_DIR, f"futures_ensemble_{args.asset}_")
TRADE_CSV = os.path.join(DATA_DIR, f"trades_{args.asset}.csv")

# --- CONFIG ---
TICKER_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
TICKER = TICKER_MAP[args.asset]
NUM_MODELS = 5

# --- LEVERAGED STRATEGY (5x) ---
LEVERAGE = 5
ENTRY_CONFIDENCE = 0.60  

TAKE_PROFIT_PRICE_PCT, LOOKAHEAD_HOURS = get_target_pct_and_lookahead_hours()

# 0.4% Price Move * 5x = 2.0% Loss
STOP_LOSS_PRICE_PCT = TAKE_PROFIT_PRICE_PCT/2 #0.004   

print(f"\nLOOKAHEAD_HOURS: {LOOKAHEAD_HOURS}")
print(f"TAKE_PROFIT_PRICE_PCT: {TAKE_PROFIT_PRICE_PCT}")
print(f"STOP_LOSS_PRICE_PCT: {STOP_LOSS_PRICE_PCT}\n")

PAPER_BALANCE = 10000.00 
current_position = None 

def get_binance_history(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": symbol, "interval": "1h", "limit": 100}
        resp = requests.get(url, params=params).json()
        df = pd.DataFrame(resp, columns=["t", "o", "h", "l", "c", "v", "x", "y", "z", "a", "b", "d"])
        df['c'] = df['c'].astype(float)
        return df['c']
    except: return None

def get_realtime_price(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/price"
        resp = requests.get(url, params={"symbol": symbol}).json()
        return float(resp['price'])
    except: return None

def get_live_data():
    try:
        live_price = get_realtime_price(TICKER)
        if live_price is None: return None

        price_series = get_binance_history(TICKER)
        if price_series is None: return None
        
        nasdaq_raw = yf.download("QQQ", period="5d", interval="1h", progress=False)
        if isinstance(nasdaq_raw.columns, pd.MultiIndex): nasdaq = nasdaq_raw['Close'].iloc[:, 0]
        else: nasdaq = nasdaq_raw['Close']
        
        delta = price_series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])
        
        sma50 = price_series.rolling(50).mean().iloc[-1]
        trend = (live_price - sma50) / sma50 
        
        vol = float(price_series.pct_change(fill_method=None).rolling(24).std().iloc[-1])
        mom = float(price_series.pct_change(24, fill_method=None).iloc[-1])
        qqq = float(nasdaq.pct_change(24, fill_method=None).iloc[-1])
        
        return {
            "price": live_price,
            "features": pd.DataFrame([{
                'rsi': rsi, 'trend_signal': trend, 'volatility': vol, 
                'momentum_24h': mom, 'qqq_mom': qqq
            }])
        }
    except Exception as e: return None

def init_csv():
    if not os.path.exists(TRADE_CSV):
        with open(TRADE_CSV, 'w') as f:
            f.write("Time,Action,Price,Size,PnL,Balance,Confidence\n")

def main():
    global PAPER_BALANCE, current_position
    logging.info(f"🚀 FUTURES BOT STARTED: {args.asset} (5x)")
    init_csv()
    
    models = []
    # Log the location where the code is running from
    current_dir = os.getcwd()
    logging.info(f"Running from directory: {current_dir}")
    for i in range(NUM_MODELS):
        logging.info(f"Loading model: {MODEL_PREFIX}{i}.json")
        try:
            m = xgb.XGBClassifier()
            m.load_model(f"{MODEL_PREFIX}{i}.json")
            models.append(m)
        except Exception as e:
            logging.exception(f"❌ Failed to load model: {MODEL_PREFIX}{i}.json | Error: {e}")
            pass
    if not models: 
        logging.error(f"❌ No models found! Train first. Searched in: {MODEL_PREFIX}*.json")
        return

    while True:
        data = get_live_data()
        if not data: time.sleep(10); continue
        price = data['price']
        
        # --- 1. MANAGE POSITION ---
        if current_position:
            pos_type = current_position['type']
            entry = current_position['entry']
            sl = current_position['sl']
            tp = current_position['tp']
            size_cash = current_position['size_cash']
            
            if pos_type == 'LONG': pnl_pct = (price - entry) / entry
            else: pnl_pct = (entry - price) / entry
                
            roe = pnl_pct * LEVERAGE
            unrealized_pnl = size_cash * roe
            
            logging.info(f"⚠️ OPEN {pos_type} | Entry: {entry:.2f} | Cur: {price:.2f} | PnL: ${unrealized_pnl:.2f}")
            
            close = False
            reason = ""
            
            if pos_type == 'LONG':
                if price <= sl: close, reason = True, "STOP LOSS"
                elif price >= tp: close, reason = True, "TAKE PROFIT"
            else:
                if price >= sl: close, reason = True, "STOP LOSS"
                elif price <= tp: close, reason = True, "TAKE PROFIT"
            
            if close:
                PAPER_BALANCE += (size_cash + unrealized_pnl)
                current_position = None
                logging.info(f"✅ TRADE CLOSED {pos_type} ({reason}) at {price:.2f}. Bal: ${PAPER_BALANCE:.2f}")
                with open(TRADE_CSV, 'a') as f:
                    f.write(f"{datetime.now()},CLOSE,{price},{size_cash},{unrealized_pnl:.2f},{PAPER_BALANCE:.2f},0\n")

        # --- 2. CHECK ENTRY ---
        else:
            all_votes = [m.predict_proba(data['features'])[0] for m in models]
            avg = np.mean(all_votes, axis=0) # [Neutral, Long, Short]
            prob_long, prob_short = avg[1], avg[2]
            
            ts = datetime.now().strftime("%H:%M:%S")
            target = f"{ENTRY_CONFIDENCE:.1%}"
            
            # --- NEW EXPLANATORY LOG ---
            move_pct = TAKE_PROFIT_PRICE_PCT * 100
            increased_target = price * (1 + move_pct / 100)
            decreased_target = price * (1 - move_pct / 100)
                        
            move_pct = TAKE_PROFIT_PRICE_PCT * 100
            logging.info(f"      🔍 SCAN | {price:.2f} | Long: {prob_long:.1%} (>{target}) | Short: {prob_short:.1%} (>{target}) | {ts}\n            ℹ️  Based on {LEVERAGE}x leverage, the bot is waiting for >{target} probability that {args.asset} price will move by by {move_pct:.2f}% (increase (Long) to {increased_target:.2f} or decrease (Short) to {decreased_target:.2f}) within the next {LOOKAHEAD_HOURS} hours")
            
            if prob_long > ENTRY_CONFIDENCE:
                logging.info(f"🚀 LONG ENTRY SIGNAL!")
                margin = PAPER_BALANCE * 0.10
                PAPER_BALANCE -= margin
                current_position = {
                    'type': 'LONG', 'entry': price, 'size_cash': margin,
                    'sl': price * (1 - STOP_LOSS_PRICE_PCT),
                    'tp': price * (1 + TAKE_PROFIT_PRICE_PCT)
                }
                with open(TRADE_CSV, 'a') as f:
                    f.write(f"{datetime.now()},LONG,{price},{margin},0,{PAPER_BALANCE:.2f},{prob_long:.2f}\n")
                
            elif prob_short > ENTRY_CONFIDENCE:
                logging.info(f"🚀 SHORT ENTRY SIGNAL!")
                margin = PAPER_BALANCE * 0.10
                PAPER_BALANCE -= margin
                current_position = {
                    'type': 'SHORT', 'entry': price, 'size_cash': margin,
                    'sl': price * (1 + STOP_LOSS_PRICE_PCT),
                    'tp': price * (1 - TAKE_PROFIT_PRICE_PCT)
                }
                with open(TRADE_CSV, 'a') as f:
                    f.write(f"{datetime.now()},SHORT,{price},{margin},0,{PAPER_BALANCE:.2f},{prob_short:.2f}\n")

        time.sleep(60)

if __name__ == "__main__":
    main()