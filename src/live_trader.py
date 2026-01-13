import time
import pandas as pd
import numpy as np
import xgboost as xgb
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.constants import POLYGON
import yfinance as yf

# Import your modules
from bedrock_parser import MarketParser

# --- USER CONFIG ---
PRIVATE_KEY = "YOUR_PRIVATE_KEY_HERE" 
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
MODEL_FILE = "polymarket_btc_v2.json"

def get_live_btc_data():
    """Fetches current price and volatility"""
    df = yf.download("BTC-USD", period="5d", interval="1h", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    current_price = df['Close'].iloc[-1]
    
    # Calculate volatility exactly like we did in training
    df['Returns'] = df['Close'].pct_change()
    current_vol = df['Returns'].rolling(window=24).std().iloc[-1]
    
    return current_price, current_vol

def main():
    print("🚀 Starting AI Trader System...")
    
    # 1. Load the Trained Model
    model = xgb.XGBClassifier()
    try:
        model.load_model(MODEL_FILE)
        print(f"✅ Loaded {MODEL_FILE}")
    except:
        print(f"❌ Could not load {MODEL_FILE}. Did you run robust_model.py?")
        return

    # 2. Init Clients
    llm_parser = MarketParser() # AWS Bedrock
    client = ClobClient(HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID, signature_type=0)
    client.set_api_creds(client.create_or_derive_api_creds())

    # 3. Trading Loop
    while True:
        try:
            print("\n--- 📡 Scanning Market ---")
            
            # Get live alpha
            btc_price, btc_vol = get_live_btc_data()
            print(f"BTC Price: ${btc_price:.2f} | Vol: {btc_vol:.4f}")

            # Get open markets via CLOB client or Gamma API
            # Using Gamma for easier searching
            import requests
            resp = requests.get("https://gamma-api.polymarket.com/markets?active=true&closed=false&tag_id=1&limit=20").json()
            
            for m in resp:
                # Filter for "Bitcoin" string to save LLM costs
                if "Bitcoin" not in m['question']: continue

                # A. Parse Question via LLM
                # We use the SAME parser as training to ensure feature consistency
                parsed = llm_parser.parse_question(m['question'])
                
                if not parsed or parsed['asset'] != 'BTC':
                    continue

                # B. Build Features (Must match training columns exactly!)
                target = parsed['target_price']
                
                # Feature 1: Log Distance
                log_distance = np.log(target / btc_price)
                
                # Feature 2: Days Left
                end_dt = pd.to_datetime(m['endDate']).replace(tzinfo=None)
                days_left = (end_dt - pd.Timestamp.now()).days
                if days_left < 1: days_left = 1
                
                # Feature 3: Volatility
                # (btc_vol calculated above)

                # Prepare row for XGBoost
                # Columns: ['log_distance', 'days_left', 'start_vol']
                features = pd.DataFrame([{
                    'log_distance': log_distance,
                    'days_left': days_left,
                    'start_vol': btc_vol
                }])

                # C. Predict
                prob = model.predict_proba(features)[0][1]
                print(f"Market: {m['question'][:40]}... | AI Confidence: {prob:.2%}")

                # D. Execution Logic
                # Fetch Orderbook
                token_id = m['clobTokenIds'][0] # usually 'Yes'
                ob = client.get_order_book(token_id)
                
                if ob.asks:
                    market_price = float(ob.asks[0].price)
                    edge = prob - market_price
                    
                    print(f"   > Market Price: {market_price:.2f} | Edge: {edge:.2f}")

                    if edge > 0.15: # High confidence threshold (15%)
                        print(f"   💰 PLACING BUY ORDER for {token_id}")
                        # Uncomment to enable real trading:
                        # client.create_and_post_order(OrderArgs(price=market_price, size=5.0, side="BUY", token_id=token_id))
        
        except Exception as e:
            print(f"Loop Error: {e}")
            
        print("Sleeping 60s...")
        time.sleep(60)

if __name__ == "__main__":
    main()