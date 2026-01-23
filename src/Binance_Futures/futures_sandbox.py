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
from scipy.stats import norm
from futures_polymarket_explorer import scan_polymarket_markets

parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

# --- LOGGING SETUP ---
LOG_DIR = os.path.join("/Volumes/SanDisk_Extreme_SSD", "workingFolder", "binance_futures", "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(LOG_DIR, f"trader_{args.asset}_{timestamp_str}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
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
STOP_LOSS_PRICE_PCT = TAKE_PROFIT_PRICE_PCT/2   

# Minimum profit margin for Polymarket trades (after fees, need meaningful profit)
MIN_POLYMARKET_PROFIT_MARGIN = 0.05  # 5% minimum profit margin
MAX_POLYMARKET_ASK_PRICE = 0.95  # Don't buy if ask price > $0.95 (profit too low)

print(f"\nLOOKAHEAD_HOURS: {LOOKAHEAD_HOURS}")
print(f"TAKE_PROFIT_PRICE_PCT: {TAKE_PROFIT_PRICE_PCT}")
print(f"STOP_LOSS_PRICE_PCT: {STOP_LOSS_PRICE_PCT}\n")

PAPER_BALANCE = 10000.00 
current_position = None 

# --- DATA FETCHING FUNCTIONS ---

def get_binance_history(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": symbol, "interval": "1h", "limit": 100}
        resp = requests.get(url, params=params).json()
        df = pd.DataFrame(resp, columns=["t", "o", "h", "l", "c", "v", "x", "y", "z", "a", "b", "d"])
        df['c'] = df['c'].astype(float)
        return df['c']
    except: return None

def get_binance_volatility(symbol):
    """
    Fetches ~14 days of hourly data to calculate the standard deviation
    of 6-hour percentage changes.
    """
    try:
        url = "https://fapi.binance.com/fapi/v1/klines"
        # 14 days * 24h = 336. We fetch 500 to be safe.
        params = {"symbol": symbol, "interval": "1h", "limit": 500}
        resp = requests.get(url, params=params).json()
        
        df = pd.DataFrame(resp, columns=["t", "o", "h", "l", "c", "v", "x", "y", "z", "a", "b", "d"])
        df['c'] = df['c'].astype(float)
        
        # Calculate 6-hour returns
        df['return_6h'] = df['c'].pct_change(periods=6)
        
        # Calculate Standard Deviation of the last 100 valid periods
        # This gives us the "current" market volatility
        vol = df['return_6h'].tail(100).std()
        
        return float(vol)
    except Exception as e:
        logging.error(f"Error fetching volatility: {e}")
        return 0.015 # Fallback to 1.5% if API fails

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

# --- POLYMARKET MATH ---

def get_smart_probability(current_price, strike_price, probs, volatility_6h, direction=1, include_equal=True):
    """
    Calculates the true probability of price hitting strike given XGBoost sentiment.
    
    Args:
        current_price: Current asset price
        strike_price: Target strike price
        probs: dict {'up': float, 'down': float, 'flat': float}
        volatility_6h: float (calculated dynamically from Binance)
        direction: 1=above, -1=below, 0=range (currently only 1 and -1 are supported)
        include_equal: If True, uses >= or <= (for "reach" markets). If False, uses > or < (strict)
                      For continuous distributions, P(X = strike) = 0, so >= and > are equivalent,
                      but this flag helps with semantic clarity and can be used for discrete adjustments.
    
    Returns:
        Probability that the condition is met (e.g., P(price >= strike) for direction=1, include_equal=True)
    """
    
    # 1. Define the expected price centers for each scenario
    price_up_scenario   = current_price * (1 + volatility_6h)
    price_down_scenario = current_price * (1 - volatility_6h)
    price_flat_scenario = current_price # No change
    
    # 2. In the "Flat" scenario, volatility is assumed lower
    vol_flat = volatility_6h * 0.3
    vol_trend = volatility_6h 

    # 3. Calculate probability of hitting strike for EACH scenario
    def probability_above_strike(expected_price, vol):
        # Avoid division by zero
        if vol == 0: return 0.0
        z = (strike_price - expected_price) / (current_price * vol)
        # For continuous distributions, P(X >= strike) = P(X > strike) = 1 - norm.cdf(z)
        # The include_equal flag is kept for semantic clarity and potential future discrete adjustments
        return 1 - norm.cdf(z)
    
    def probability_below_strike(expected_price, vol):
        # Avoid division by zero
        if vol == 0: return 0.0
        z = (strike_price - expected_price) / (current_price * vol)
        # P(X <= strike) = norm.cdf(z)
        return norm.cdf(z)

    if direction == 1:  # Above
        p_hit_if_up   = probability_above_strike(price_up_scenario, vol_trend)
        p_hit_if_down = probability_above_strike(price_down_scenario, vol_trend)
        p_hit_if_flat = probability_above_strike(price_flat_scenario, vol_flat)
    elif direction == -1:  # Below
        p_hit_if_up   = probability_below_strike(price_up_scenario, vol_trend)
        p_hit_if_down = probability_below_strike(price_down_scenario, vol_trend)
        p_hit_if_flat = probability_below_strike(price_flat_scenario, vol_flat)
    else:  # Range (direction == 0) - not fully implemented yet
        # For range, we'd need two strikes, so default to above for now
        p_hit_if_up   = probability_above_strike(price_up_scenario, vol_trend)
        p_hit_if_down = probability_above_strike(price_down_scenario, vol_trend)
        p_hit_if_flat = probability_above_strike(price_flat_scenario, vol_flat)

    # 4. Weighted Sum
    final_prob = (probs['up'] * p_hit_if_up) + \
                 (probs['down'] * p_hit_if_down) + \
                 (probs['flat'] * p_hit_if_flat)
                 
    return final_prob

# --- MAIN LOOP ---

def main():
    global PAPER_BALANCE, current_position
    logging.info(f"🚀 FUTURES BOT STARTED: {args.asset} (5x)")
    init_csv()
    
    models = []
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
            prob_neutral, prob_long, prob_short = avg[0], avg[1], avg[2]
            
            ts = datetime.now().strftime("%H:%M:%S")
            target = f"{ENTRY_CONFIDENCE:.1%}"
            
            # --- EXPLANATORY LOG ---
            move_pct = TAKE_PROFIT_PRICE_PCT * 100
            increased_target = price * (1 + move_pct / 100)
            decreased_target = price * (1 - move_pct / 100)
            
            predicted_class = np.argmax(avg)
            class_names = ["NEUTRAL (flat)", "LONG (up)", "SHORT (down)"]
            predicted_label = class_names[predicted_class]
            
            logging.info(f"      🔍 SCAN | {price:.2f} | Neutral: {prob_neutral:.1%} | Long: {prob_long:.1%} (>{target}) | Short: {prob_short:.1%} (>{target}) | {ts}")
            logging.info(f"            📊 Prediction: {predicted_label}")
            
            MAX_NEUTRAL_PROB = 0.50  
            
            if prob_long > ENTRY_CONFIDENCE and prob_neutral <= MAX_NEUTRAL_PROB:
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
                
            elif prob_short > ENTRY_CONFIDENCE and prob_neutral <= MAX_NEUTRAL_PROB:
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
            else:
                pass 
                # (Logging reduced to keep output clean, enable if needed)

            # --- 3. POLYMARKET CALCULATION ---
            logging.info(f"      🔍 Scanning Polymarket for {args.asset} price markets...")
            
            # A. Scan Polymarket for relevant markets
            try:
                polymarket_markets = scan_polymarket_markets(args.asset, price, limit=10)
                
                if polymarket_markets:
                    logging.info(f"      ✅ Found {len(polymarket_markets)} {args.asset} price markets")
                    
                    # B. Get Dynamic Volatility
                    vol_6h = get_binance_volatility(TICKER)
                    
                    # C. Format Probs
                    probs = {'up': prob_long, 'down': prob_short, 'flat': prob_neutral}
                    
                    # D. Calculate Fair Price for each market
                    for market in polymarket_markets:
                        strike = market['strike_price']
                        label = market['label']
                        yes_price = market['yes']['price']
                        yes_bid = market['yes']['bid']
                        yes_ask = market['yes']['ask']
                        no_price = market['no']['price']
                        no_bid = market['no']['bid']
                        no_ask = market['no']['ask']
                        
                        # Determine if "reach" means >= (include_equal=True) or > (include_equal=False)
                        # "Reach", "hit", "touch" typically mean >= (equal or above/below)
                        # "Above", "below" can mean either, but often also mean >=
                        question_lower = market['question'].lower()
                        include_equal = any(word in question_lower for word in ['reach', 'hit', 'touch', 'at least', 'at most'])
                        
                        # Calculate the fair price (probability) of the event happening
                        # For example: If the market is will bitcoin reach $150,000 in January 2026? Fair for YES answer = $0.000: The model estimates 0% chance Bitcoin will reach $150,000
                        fair_price = get_smart_probability(price, strike, probs, vol_6h, 
                                                          direction=market['direction'], 
                                                          include_equal=include_equal)
                        
                        # Calculate the fair price (probability) of the event not happening
                        # For example: If the market is will bitcoin reach $150,000 in January 2026? Fair for NO answer = $1.000: The model estimates 100% chance Bitcoin will reach $150,000
                        fair_no_price = 1 - fair_price
                        
                        direction_str = {1: "above", -1: "below", 0: "range"}.get(market['direction'], "unknown")
                        equality_str = ">=" if include_equal else ">"
                        if market['direction'] == -1:
                            equality_str = "<=" if include_equal else "<"
                        elif market['direction'] == 0:
                            equality_str = "range"
                        
                        logging.info(f"      🔮 POLYMARKET | {label[:40]}...")
                        logging.info(f"         Strike: ${strike:,.0f} ({direction_str}, {equality_str}) | Current Vol(6h): {vol_6h:.3%}")
                        # Market price = midpoint between bid and ask (for reference only, use ask for buying)
                        yes_bid_size = market['yes'].get('bid_size', 0.0)
                        yes_ask_size = market['yes'].get('ask_size', 0.0)
                        no_bid_size = market['no'].get('bid_size', 0.0)
                        no_ask_size = market['no'].get('ask_size', 0.0)
                        logging.info(f"         YES: Bid=${yes_bid:.3f} (size: {yes_bid_size:,.0f}) Ask=${yes_ask:.3f} (size: {yes_ask_size:,.0f}) Market=${yes_price:.3f} (midpoint between bid and ask: (bid + ask) / 2) | Fair=${fair_price:.3f} ($0.00 = 100% NOT Happing $1.00 100% Hapenning)")
                        logging.info(f"         NO:  Bid=${no_bid:.3f} (size: {no_bid_size:,.0f}) Ask=${no_ask:.3f} (size: {no_ask_size:,.0f}) Market=${no_price:.3f} (midpoint between bid and ask: (bid + ask) / 2) | Fair=${fair_no_price:.3f} ($0.00 = 100% NOT Happing $1.00 100% Hapenning)")
                        
                        # Calculate edge and profit margin for YES
                        if yes_ask > 0:
                            edge_yes = fair_price - yes_ask  # Use ask price (what you pay)
                            profit_margin_yes = (1.0 - yes_ask) / yes_ask if yes_ask > 0 else 0  # Profit if YES wins
                            
                            if edge_yes > 0:
                                if yes_ask > MAX_POLYMARKET_ASK_PRICE:
                                    logging.info(f"         ❌ YES Edge: +{edge_yes:.1%} but Ask=${yes_ask:.3f} > ${MAX_POLYMARKET_ASK_PRICE:.2f} | Reason: Profit too low (${profit_margin_yes:.1%} after payout, not worth it after fees)")
                                elif profit_margin_yes < MIN_POLYMARKET_PROFIT_MARGIN:
                                    logging.info(f"         ❌ YES Edge: +{edge_yes:.1%} but Profit=${profit_margin_yes:.1%} < {MIN_POLYMARKET_PROFIT_MARGIN:.0%} | Reason: Profit margin too low")
                                else:
                                    logging.info(f"         ✅ YES Edge: +{edge_yes:.1%} | Profit=${profit_margin_yes:.1%} (FAVORABLE - BUY YES)")
                            else:
                                logging.info(f"         ❌ YES Edge: {edge_yes:.1%} (unfavorable - fair price below ask)")
                        
                        # Calculate edge and profit margin for NO
                        if no_ask > 0:
                            edge_no = fair_no_price - no_ask  # Use ask price (what you pay)
                            profit_margin_no = (1.0 - no_ask) / no_ask if no_ask > 0 else 0  # Profit if NO wins
                            
                            if edge_no > 0:
                                if no_ask > MAX_POLYMARKET_ASK_PRICE:
                                    logging.info(f"         ❌ NO Edge: +{edge_no:.1%} but Ask=${no_ask:.3f} > ${MAX_POLYMARKET_ASK_PRICE:.2f} | Reason: Profit too low (${profit_margin_no:.1%} after payout, not worth it after fees)")
                                elif profit_margin_no < MIN_POLYMARKET_PROFIT_MARGIN:
                                    logging.info(f"         ❌ NO Edge: +{edge_no:.1%} but Profit=${profit_margin_no:.1%} < {MIN_POLYMARKET_PROFIT_MARGIN:.0%} | Reason: Profit margin too low")
                                else:
                                    logging.info(f"         ✅ NO Edge: +{edge_no:.1%} | Profit=${profit_margin_no:.1%} (FAVORABLE - BUY NO)")
                            else:
                                logging.info(f"         ❌ NO Edge: {edge_no:.1%} (unfavorable - fair price below ask)")
                else:
                    logging.info(f"      ⚠️ No {args.asset} price markets found on Polymarket")
                    
            except Exception as e:
                logging.error(f"      ❌ Error scanning Polymarket: {e}")
                import traceback
                logging.debug(traceback.format_exc())
            
        time.sleep(60)

if __name__ == "__main__":
    main()