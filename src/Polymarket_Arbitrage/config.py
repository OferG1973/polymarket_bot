import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Auth
    HOST = "https://clob.polymarket.com"
    CHAIN_ID = 137
    PRIVATE_KEY = '0xd5f9ac31269e40ba14abc41336db2a97a96f708cc382349e1a1ac682834d2b2e' #os.getenv("PRIVATE_KEY")
    API_KEY = os.getenv("POLY_API_KEY")
    API_SECRET = os.getenv("POLY_API_SECRET")
    PASSPHRASE = os.getenv("POLY_PASSPHRASE")

    # --- EXPERT DISCOVERY SETTINGS ---
    # Max markets to subscribe to (Prevents CPU meltdown)
    # 
    # SWEET SPOT RECOMMENDATIONS:
    # - Conservative (safe): 25-50 markets (50-100 tokens)
    # - Balanced (recommended): 50-100 markets (100-200 tokens) 
    # - Aggressive (monitor closely): 100-200 markets (200-400 tokens)
    # - Maximum (risky): 200-300 markets (400-600 tokens)
    #
    # FACTORS:
    # - WebSocket: Polymarket typically handles 100-500 tokens per connection
    # - Speed: Your strategy loop (0.01s) can scan 100 markets in ~1ms (very fast)
    # - Execution: Network latency (~50-200ms) is the real bottleneck, not scanning
    # - Risk: Too many subscriptions may cause connection drops or rate limiting
    #
    # RECOMMENDED: Start with 50, monitor for 24h, then scale to 100 if stable
    MAX_MARKETS_TO_TRACK = 150  # Number of markets to actually monitor
    
    # Discovery settings
    MARKETS_TO_SCAN = 1000  # Scan this many markets, then select best MAX_MARKETS_TO_TRACK 
    
    # We don't care about markets with $0 liquidity (can't trade them)
    # Filter out the junk.
    MIN_LIQUIDITY_USDC = 500.0
    
    # Market validation thresholds
    MIN_VOLUME_USDC = 100.0  # Minimum trading volume to ensure market is active
    MIN_HOURS_UNTIL_END = 1.0  # Markets must end at least this many hours in the future 

    # --- Fee Configuration ---
    # Polymarket fee structure:
    # - International markets: ~2% fee on profits (not on trades)
    # - US markets: 0.01% (1 basis point) taker fee on premium
    # - Gas fees: ~$0.01-$0.50 per trade on Polygon (2 trades = ~$0.02-$1.00)
    # - Slippage: 0.5-5% depending on liquidity (already accounted for in order book prices)
    MARKET_TYPE = "international"  # Options: "international" or "us"
    
    # --- Risk ---
    MAX_TRADE_SIZE_USDC = 50.0
    # Minimum gross profit spread to enter arbitrage (before fees)
    # For international markets: 2.5% gross needed to net ~0.5-1% after 2% profit fee + gas
    # For US markets: 1.5-2% gross needed to net ~0.5-1% after 0.01% taker fee + gas
    MIN_PROFIT_SPREAD = 0.025 if MARKET_TYPE == "international" else 0.015  # 2.5% for international, 1.5% for US
    SIMULATION_MODE = True
    SIM_CSV_FILE = "sim_trades.csv"  # Individual order log
    ARB_CSV_FILE = "arbitrage_trades.csv"  # Complete arbitrage trade log
    
    # Fee rates (as decimals)
    PROFIT_FEE_RATE = 0.02 if MARKET_TYPE == "international" else 0.0  # 2% on profits for international, 0% for US
    TAKER_FEE_RATE = 0.0001 if MARKET_TYPE == "us" else 0.0  # 0.01% taker fee for US markets
    ESTIMATED_GAS_COST_PER_TRADE = 0.25  # Estimated gas cost per trade in USDC (~$0.01-$0.50, using mid-range)
    TOTAL_GAS_COST = ESTIMATED_GAS_COST_PER_TRADE * 2  # 2 trades (one for each outcome)
    
    # Minimum NET profit spread required (after all fees)
    # For international: gross spread needs to be ~2.5-3% to net ~0.5-1% after 2% profit fee + gas
    # For US: gross spread needs to be ~1.5-2% to net ~0.5-1% after 0.01% taker fee + gas
    MIN_NET_PROFIT_SPREAD = 0.005  # Minimum 0.5% net profit after all fees