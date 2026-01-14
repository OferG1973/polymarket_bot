import requests
import pandas as pd
import yfinance as yf
import time
import numpy as np
import os
import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from bedrock_parser import MarketParser
DATA_DIR = os.path.join("src", "Polymarket")

# --- ARGUMENT PARSING ---
parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC", choices=["BTC", "ETH", "SOL"])
args = parser.parse_args()

# --- CONFIGURATION ---
ASSET_MAP = {
    "BTC": {"ticker": "BTC-USD", "keywords": ["bitcoin", "btc"], "polymarket_tag": ""},
    "ETH": {"ticker": "ETH-USD", "keywords": ["ethereum", "eth"], "polymarket_tag": ""},
    "SOL": {"ticker": "SOL-USD", "keywords": ["solana", "sol"], "polymarket_tag": ""}
}

# Dynamically resolve tag
def get_polymarket_tag_for_asset(asset_name):
    slug = asset_name.lower()
    url = f"https://gamma-api.polymarket.com/tags/slug/{slug}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return str(response.json().get("id"))
    except: return None

# Initialize Tags
for asset, asset_config in ASSET_MAP.items():
    tag = get_polymarket_tag_for_asset(asset_config["keywords"][0])
    if tag: ASSET_MAP[asset]["polymarket_tag"] = tag

CURRENT_ASSET = args.asset
CONFIG = ASSET_MAP[CURRENT_ASSET]
OUTPUT_FILE = f"data_{CURRENT_ASSET}.csv"
MIN_SAMPLES_NEEDED = 100

print(f"🚀 INITIALIZING PIPELINE FOR: {CURRENT_ASSET}")
print(f"   Ticker: {CONFIG['ticker']}")
print(f"   Output: {OUTPUT_FILE}")

# --- HELPER: RSI ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- STEP 1: FETCH DATA ---
def fetch_market_data():
    print("📉 Fetching fresh financial history (730 days)...")
    tickers = [CONFIG['ticker'], "BTC-USD", "^IXIC"]
    tickers = list(set(tickers))
    
    data = yf.download(tickers, period="730d", interval="1h", progress=False)['Close']
    
    # Timezone Standardization
    if data.index.tz is None: data.index = data.index.tz_localize('UTC')
    else: data.index = data.index.tz_convert('UTC')
    
    print(f"   ⏱️ Data Start: {data.index[0]}")
    print(f"   ⏱️ Data End:   {data.index[-1]}")

    df = pd.DataFrame(index=data.index)
    target_col = CONFIG['ticker']
    df['Price'] = data[target_col]
    df['Ret'] = df['Price'].pct_change(fill_method=None)
    df['Vol_24h'] = df['Ret'].rolling(window=24).std()
    df['RSI'] = calculate_rsi(df['Price'], period=14)
    df['SMA50'] = df['Price'].rolling(window=50).mean()
    df['Trend'] = (df['Price'] - df['SMA50']) / df['SMA50']

    if "BTC-USD" in data.columns: df['BTC_Mom'] = data['BTC-USD'].pct_change(24, fill_method=None)
    else: df['BTC_Mom'] = 0 
    df['QQQ_Mom'] = data['^IXIC'].pct_change(24, fill_method=None).ffill()

    df.dropna(inplace=True)
    print(f"✅ Financial Data Ready: {len(df)} rows.")
    return df

# --- STEP 2: TIME LOOKUP ---
def get_point_in_time_features(df, timestamp):
    if timestamp.tzinfo is None: timestamp = timestamp.tz_localize('UTC')
    
    if timestamp < df.index[0]: return "TOO_OLD"
    
    if timestamp > df.index[-1]: 
        diff = timestamp - df.index[-1]
        # Allow 48h lag for recent markets
        if diff < timedelta(hours=48):
            row = df.iloc[-1]
            return {
                "price": float(row['Price']),
                "vol": float(row['Vol_24h']),
                "rsi": float(row['RSI']),
                "trend": float(row['Trend']),
                "btc_mom": float(row['BTC_Mom']),
                "qqq_mom": float(row['QQQ_Mom'])
            }
        return "TOO_NEW"
    
    idx = df.index.get_indexer([timestamp], method='pad')[0]
    if idx == -1: return "NO_MATCH"
    row = df.iloc[idx]
    
    return {
        "price": float(row['Price']),
        "vol": float(row['Vol_24h']),
        "rsi": float(row['RSI']),
        "trend": float(row['Trend']),
        "btc_mom": float(row['BTC_Mom']),
        "qqq_mom": float(row['QQQ_Mom'])
    }

# --- STEP 3: PRICE-BASED RESOLUTION (CRITICAL FIX) ---
def resolve_market_outcome(m):
    """
    Determines winner based on FINAL PRICES ($1.00 vs $0.00).
    Expected Input:
      m['outcomePrices'] -> "[\"0\", \"1\"]"
      m['outcomes'] -> "[\"Up\", \"Down\"]"
    """
    try:
        # INSERT_YOUR_CODE
        import os
        import json
        from datetime import datetime

        market_dumps_dir = "market_dumps"
        if not os.path.exists(market_dumps_dir):
            os.makedirs(market_dumps_dir)

        # Use a timestamp and market identifier in the filename if available
        market_id = m.get("id") or m.get("marketId") or "unknown_market"
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        filename = f"{market_id}_{timestamp}.json"
        filepath = os.path.join(market_dumps_dir, filename)
        try:
            with open(filepath, "w") as f:
                json.dump(m, f, indent=2)
        except Exception as dump_e:
            pass  # Optionally log or handle

        # 1. Extract and Parse Strings
        raw_outcomes = m.get('outcomes')
        raw_prices = m.get('outcomePrices')

        # If they are strings (which they usually are in this API), decode them
        if isinstance(raw_outcomes, str): 
            try: outcomes = json.loads(raw_outcomes)
            except: return None
        else: outcomes = raw_outcomes

        if isinstance(raw_prices, str):
            try: prices = json.loads(raw_prices)
            except: return None
        else: prices = raw_prices
        
        # 2. Basic Validation
        if not outcomes or not prices or len(outcomes) != len(prices):
            return None

        # 3. Find the Winner (Price approx 1.0)
        # Note: Polymarket prices are strings "0" or "1", convert to float
        prices_float = [float(p) for p in prices]
        
        winner_index = -1
        for i, p in enumerate(prices_float):
            if p > 0.95: # Allow slight floating point variance
                winner_index = i
                break
        
        if winner_index == -1:
            return None # No clear winner found (market might be disputed or invalid)

        # 4. Map Winner Text to Binary Label
        winner_text = str(outcomes[winner_index]).strip().lower()

        if winner_text in ['yes', 'up', 'true', '1']:
            return 1
        if winner_text in ['no', 'down', 'false', '0']:
            return 0
            
        return None

    except Exception as e:
        # print(f"Resolution Error: {e}")
        return None

def load_existing_data():
    if os.path.exists(OUTPUT_FILE):
        try:
            df = pd.read_csv(OUTPUT_FILE)
            seen = set(df['debug_question'].unique())
            print(f"📂 Loaded existing DB: {len(df)} rows.")
            return df, seen
        except: pass
    print("NEW: Starting fresh database.")
    return pd.DataFrame(), set()

# --- MAIN LOOP ---
def process_markets(tag_id):
    existing_df, seen_questions = load_existing_data()
    parser = MarketParser()
    market_df = fetch_market_data()
    
    new_dataset = []
    offset = 0
    limit = 50 
    
    search_query = CONFIG['keywords'][0] 
    
    # Load Ignore List Once
    ignored_questions = set()
    try:
        filename = os.path.join(DATA_DIR, "polymarkets_to_ignore.csv")
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                import csv
                ignored_questions = set(row[0].strip() for row in csv.reader(f) if row)
    except: pass

    print(f"\n🔍 Starting Search (Query: {search_query}, Tag: {tag_id})...")
    
    while True:
        if len(existing_df) == 0 and len(new_dataset) >= MIN_SAMPLES_NEEDED:
            print("✅ Collected enough initial samples.")
            break

        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "q": search_query,
            "type": "markets",
            "closed": "true",
            "tagId": tag_id,
            "limit": limit,
            "offset": offset, 
            "order": "startDate",
            "ascending": "false"
        }
        
        try:
            r = requests.get(url, params=params)
            r.raise_for_status()
            batch_data = r.json()
            
            # Extract List
            batch = []
            if isinstance(batch_data, list): batch = batch_data
            elif isinstance(batch_data, dict):
                for key in ['data', 'results', 'markets']:
                    if key in batch_data and isinstance(batch_data[key], list):
                        batch = batch_data[key]; break
                if not batch and 'events' in batch_data:
                    for e in batch_data['events']:
                        if 'markets' in e: batch.extend(e['markets'])

            if not batch: break
            
            batch_rejections = Counter()
            
            for m in batch:
                if 'question' not in m: continue
                q_text = m['question']

                # --- 1. FUTURE CHECK Ignore future markets---
                try:
                    end_dt = pd.to_datetime(m['endDate'])
                    if end_dt.tzinfo is None: end_dt = end_dt.tz_localize('UTC')
                    now = datetime.now(timezone.utc)
                    if end_dt > now:
                        batch_rejections['Future Market'] += 1; continue
                except: continue

                # --- 2. IGNORED CHECK ---
                if q_text in ignored_questions:
                    batch_rejections['Ignored'] += 1; continue
                
                # --- 3. DUPLICATE CHECK ---
                if q_text in seen_questions:
                    batch_rejections['Duplicate'] += 1; continue
                
                # --- 4. KEYWORD CHECK ---
                if not any(k.lower() in q_text.lower() for k in CONFIG['keywords']):
                    batch_rejections['Mismatch'] += 1; continue

                # --- 5. PARSE ---
                parsed = parser.parse_question(q_text)
                if not parsed:
                    batch_rejections['Parse Fail'] += 1; continue
                if parsed.get('asset') != CURRENT_ASSET:
                    batch_rejections['Wrong Asset'] += 1; continue

                # --- 6. RESOLUTION (THE CRITICAL UPDATE) ---
                label = resolve_market_outcome(m)
                if label is None:
                    batch_rejections['No Resolution'] += 1; continue

                # --- 7. FEATURES ---
                try:
                    start_dt = pd.to_datetime(m['startDate'])
                except: batch_rejections['Bad Date'] += 1; continue

                feats = get_point_in_time_features(market_df, start_dt)
                if isinstance(feats, str): 
                    batch_rejections[f"Data ({feats})"] += 1; continue
                
                target = parsed['target_price']
                current = feats['price']
                direction = parsed.get('direction', 1)

                if target == "CURRENT_PRICE": target = current
                if not isinstance(target, (int, float)): 
                    batch_rejections['Bad Target'] += 1; continue

                if direction == 1: moneyness = np.log(current / target)
                elif direction == -1: moneyness = np.log(target / current)
                else: moneyness = -abs(np.log(current / target))

                hours = (end_dt - start_dt).total_seconds() / 3600
                days_left = max(0.1, hours / 24.0)

                new_dataset.append({
                    "moneyness": moneyness, "days_left": days_left,
                    "vol": feats['vol'], "rsi": feats['rsi'], "trend": feats['trend'],
                    "btc_mom": feats['btc_mom'], "qqq_mom": feats['qqq_mom'],
                    "outcome": label, "debug_question": q_text
                })
                seen_questions.add(q_text)
                print(f"      ✅ NEW: {q_text[:40]}... [Outcome:{label}]")

            print(f"   Batch {offset}-{offset+limit} | New: {len(new_dataset)} | Skipped: {dict(batch_rejections)}")
            offset += limit
            time.sleep(0.5)
            
        except Exception as e:
            print(f"❌ Error: {e}"); break

    if new_dataset:
        new_df = pd.DataFrame(new_dataset)
        final_df = pd.concat([existing_df, new_df], ignore_index=True) if not existing_df.empty else new_df
        final_df.drop_duplicates(subset=['debug_question'], inplace=True)
        final_df.to_csv(OUTPUT_FILE, index=False)
        print(f"\n💾 DATABASE UPDATED: {len(final_df)} rows")
    else:
        print("\n✅ Database up to date.")

if __name__ == "__main__":
    # 1. Run for Broad Crypto (Tag 1) - catches most things
    crypto_tag = get_polymarket_tag_for_asset('Crypto')
    if crypto_tag: process_markets(crypto_tag)
    
    # 2. Run for Specific Asset Tag (e.g., Bitcoin) - catches things missed by broad tag
    keywords = ASSET_MAP[args.asset]["keywords"]
    for key_item in keywords:
        lower_key = key_item.lower()
        specific_tag = get_polymarket_tag_for_asset(lower_key)
        if specific_tag and specific_tag != crypto_tag:
            print(f"🚀 process_markets(keyword: {lower_key})")
            process_markets(specific_tag)