import time
import pandas as pd
import xgboost as xgb
import yfinance as yf
import requests
import argparse
from datetime import datetime

parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

# --- CONFIG ---
ASSET_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
SYMBOL = ASSET_MAP[args.asset]
MODEL_PREFIX = f"futures_ensemble_{args.asset}_"
NUM_MODELS = 5

# SETTINGS
ENTRY_CONFIDENCE = 0.70
STOP_LOSS_PCT = 0.02
TAKE_PROFIT_PCT = 0.04
PAPER_BALANCE = 10000.00

current_position = None 

def get_binance_price_history(symbol):
    """Fetches last 100 hours from Binance for indicators"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": "1h", "limit": 100}
    try:
        resp = requests.get(url, params=params).json()
        df = pd.DataFrame(resp, columns=["time", "open", "high", "low", "close", "vol", "x", "y", "z", "a", "b", "c"])
        df['close'] = df['close'].astype(float)
        return df['close']
    except Exception as e:
        print(f"Binance Error: {e}")
        return None

def get_live_data():
    try:
        # 1. Get Crypto Data (Binance)
        price_series = get_binance_price_history(SYMBOL)
        if price_series is None: return None
        
        latest_price = float(price_series.iloc[-1])
        
        # 2. Get Macro Data (Yahoo)
        nasdaq = yf.download("^IXIC", period="5d", interval="1h", progress=False)['Close']
        
        # --- CALCULATE INDICATORS ---
        # RSI
        delta = price_series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])
        
        # Trend (SMA 50)
        sma50 = price_series.rolling(50).mean().iloc[-1]
        trend = (latest_price - sma50) / sma50
        
        # Volatility & Mom
        # Fix FutureWarning by adding fill_method=None
        vol = float(price_series.pct_change(fill_method=None).rolling(24).std().iloc[-1])
        mom = float(price_series.pct_change(24, fill_method=None).iloc[-1])
        
        # Macro
        qqq = float(nasdaq.pct_change(24, fill_method=None).iloc[-1])
        
        return {
            "price": latest_price,
            "features": pd.DataFrame([{
                'rsi': rsi, 'trend_signal': trend, 'volatility': vol, 
                'momentum_24h': mom, 'qqq_mom': qqq
            }])
        }
    except Exception as e:
        print(f"Data Error: {e}")
        return None

def main():
    global PAPER_BALANCE, current_position
    
    print(f"🚀 BINANCE FUTURES BOT: {args.asset}")
    
    models = []
    for i in range(NUM_MODELS):
        try:
            m = xgb.XGBClassifier()
            m.load_model(f"{MODEL_PREFIX}{i}.json")
            models.append(m)
        except: pass
    
    if not models:
        print("❌ No models found. Run futures_training.py first.")
        return
    print(f"✅ Loaded {len(models)} models.")

    while True:
        data = get_live_data()
        if not data: time.sleep(10); continue
        
        price = data['price']
        
        if current_position:
            entry = current_position['entry']
            sl = current_position['sl']
            tp = current_position['tp']
            
            pnl_pct = (price - entry) / entry
            unrealized_pnl = current_position['size'] * pnl_pct
            
            print(f"   ⚠️ OPEN LONG | Entry: {entry:.2f} | Curr: {price:.2f} | PnL: ${unrealized_pnl:.2f}")
            
            if price <= sl:
                print(f"❌ STOP LOSS HIT at {price:.2f}")
                PAPER_BALANCE += (current_position['size'] + unrealized_pnl)
                current_position = None
                print(f"   📉 New Balance: ${PAPER_BALANCE:,.2f}")
            elif price >= tp:
                print(f"✅ TAKE PROFIT HIT at {price:.2f}")
                PAPER_BALANCE += (current_position['size'] + unrealized_pnl)
                current_position = None
                print(f"   📈 New Balance: ${PAPER_BALANCE:,.2f}")
                
        else:
            votes = [m.predict_proba(data['features'])[0][1] for m in models]
            avg_prob = sum(votes) / len(votes)
            
            print(f"   🔍 SCANNING | Price: {price:.2f} | Conf: {avg_prob:.1%}")
            
            if avg_prob > ENTRY_CONFIDENCE:
                print(f"🚀 ENTRY SIGNAL! Buying {args.asset}...")
                pos_size = PAPER_BALANCE * 0.10
                PAPER_BALANCE -= pos_size
                
                current_position = {
                    'entry': price,
                    'sl': price * (1 - STOP_LOSS_PCT),
                    'tp': price * (1 + TAKE_PROFIT_PCT),
                    'size': pos_size
                }
                print(f"   ➡️ LONG OPENED. Target: {current_position['tp']:.2f}")

        time.sleep(60)

if __name__ == "__main__":
    main()