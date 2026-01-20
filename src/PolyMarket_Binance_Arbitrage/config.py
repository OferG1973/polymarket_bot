import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # --- Polymarket Auth ---
    POLY_HOST = "https://clob.polymarket.com"
    POLY_CHAIN_ID = 137
    POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY", '0xd5f9ac31269e40ba14abc41336db2a97a96f708cc382349e1a1ac682834d2b2e')
    POLY_API_KEY = os.getenv("POLY_API_KEY")
    POLY_API_SECRET = os.getenv("POLY_API_SECRET")
    POLY_PASSPHRASE = os.getenv("POLY_PASSPHRASE")
    
    # --- Binance Configuration ---
    # Top 10 cryptocurrencies by market cap to monitor
    # Each crypto has keywords and Polymarket tag_ids for filtering events
    TOP_CRYPTOS = [
        {"symbol": "BTC/USDT", "name": "Bitcoin", "keywords": ["bitcoin", "btc", "BTC"], "tag_ids": ["21", "235", "620"]},
        {"symbol": "ETH/USDT", "name": "Ethereum", "keywords": ["ethereum", "eth", "ETH"], "tag_ids": ["157", "39"]},
        {"symbol": "SOL/USDT", "name": "Solana", "keywords": ["solana", "sol", "SOL"], "tag_ids": ["818", "787"]},
        #{"symbol": "BNB/USDT", "name": "BNB", "keywords": ["bnb", "binance coin", "BNB"], "tag_ids": ["21"]},
        # {"symbol": "XRP/USDT", "name": "XRP", "keywords": ["xrp", "ripple", "XRP"], "tag_ids": ["21"]},
        # {"symbol": "ADA/USDT", "name": "Cardano", "keywords": ["cardano", "ada", "ADA"], "tag_ids": ["21"]},
        # {"symbol": "DOGE/USDT", "name": "Dogecoin", "keywords": ["dogecoin", "doge", "DOGE"], "tag_ids": ["21"]},
        # {"symbol": "AVAX/USDT", "name": "Avalanche", "keywords": ["avalanche", "avax", "AVAX"], "tag_ids": ["21"]},
        # {"symbol": "SHIB/USDT", "name": "Shiba Inu", "keywords": ["shiba", "shib", "SHIB"], "tag_ids": ["21"]},
        # {"symbol": "DOT/USDT", "name": "Polkadot", "keywords": ["polkadot", "dot", "DOT"], "tag_ids": ["21"]},
    ]
    
    # Collect all unique tag_ids from all cryptos
    ALL_TAG_IDS = []
    for crypto in TOP_CRYPTOS:
        ALL_TAG_IDS.extend(crypto.get("tag_ids", []))
    ALL_TAG_IDS = list(set(ALL_TAG_IDS))  # Remove duplicates
    
    BINANCE_SYMBOL = TOP_CRYPTOS[0]["symbol"]  # Default to Bitcoin (backward compatibility)
    BINANCE_EXCHANGE = "binance"  # Exchange name for ccxt
    
    # --- Delta Lag Strategy Parameters (High Frequency) ---
    # Trigger: If price moves more than this percentage in detection window
    DELTA_THRESHOLD_PERCENT = 0.2  # 0.2% move threshold (happens frequently)
    
    # Time window for detecting delta move (in seconds)
    DELTA_DETECTION_WINDOW = 10  # 10 seconds (much faster than 60s)
    
    # Expected lag between Binance and Polymarket (in seconds)
    EXPECTED_LAG_MIN = 2  # Minimum lag: 2 seconds
    EXPECTED_LAG_MAX = 10  # Maximum lag: 10 seconds
    
    # Exit strategy: Hold time before selling
    EXIT_HOLD_SECONDS = 30  # Wait 30 seconds for Polymarket to catch up
    
    # Minimum profit target for exit (as percentage)
    MIN_EXIT_PROFIT_PCT = 0.01  # 1% minimum profit before exiting
    
    # --- Market Discovery ---
    # Keywords to search for in Polymarket markets (all top 10 cryptos)
    CRYPTO_KEYWORDS = []
    for crypto in TOP_CRYPTOS:
        CRYPTO_KEYWORDS.extend(crypto["keywords"])
    
    # Legacy support
    BITCOIN_KEYWORDS = CRYPTO_KEYWORDS
    
    # Minimum liquidity required to trade
    MIN_LIQUIDITY_USDC = 1000.0
    
    # Maximum allowed spread percentage (bid/ask spread) for a market to be tradeable
    # Spread = (Ask - Bid) / Bid * 100
    # Markets with spreads wider than this will be filtered out
    MAX_SPREAD_PCT = 2.0  # 2% maximum spread (e.g., $0.45 bid, $0.46 ask = 2.2% spread)
    
    # Maximum number of markets to monitor
    MAX_MARKETS_TO_MONITOR = 60  # 20 markets per crypto (3 cryptos: BTC, ETH, SOL)
    
    # --- Trading Parameters ---
    MAX_TRADE_SIZE_USDC = 100.0  # Maximum trade size per opportunity
    MIN_PROFIT_SPREAD = 0.01  # Minimum 1% spread to enter
    
    # --- Risk Management ---
    MAX_POSITIONS_PER_MARKET = 1  # Only one position per market at a time
    COOLDOWN_SECONDS = 300  # 5 minutes cooldown between trades on same market
    
    # --- Execution Settings ---
    SIMULATION_MODE = True  # Set to False for live trading
    SIM_CSV_FILE = "binance_polymarket_trades.csv"
    
    # --- Logging ---
    LOG_LEVEL = "INFO"  # Options: "INFO", "DETAILED", or "MOVEMENT"
    # DETAILED level will log:
    # - Each market being monitored
    # - Every Binance WebSocket message
    # - Every Polymarket WebSocket message
    # MOVEMENT level will log:
    # - Every movement check with timestamps (Step 1 checks) to see if the price has moved more than 0.2% in 10 seconds (thus potential arbitrage opportunity)
    LOG_DIR = os.path.join("/Volumes/SanDisk_Extreme_SSD", "workingFolder", "binance_polymarket_arbitrage", "log")
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    
    # --- Price Feed Settings ---
    BINANCE_UPDATE_INTERVAL = 1.0  # Check Binance price every 1 second
    POLY_UPDATE_INTERVAL = 2.0  # Check Polymarket markets every 2 seconds
    
    # --- Fee Configuration ---
    # Most Polymarket markets are fee-free
    POLY_TAKER_FEE_RATE = 0.0  # No taker fees on most markets
    POLY_PROFIT_FEE_RATE = 0.0  # No profit fees
    
    # Gas costs (only if not using gasless trading)
    USE_GASLESS_TRADING = False
    ESTIMATED_GAS_COST_PER_TRADE = 0.05 if not USE_GASLESS_TRADING else 0.0
    TOTAL_GAS_COST = ESTIMATED_GAS_COST_PER_TRADE * 2  # 2 trades (buy both outcomes)
    
    MIN_NET_PROFIT_SPREAD = 0.005  # Minimum 0.5% net profit after fees
    
    # --- Order Type Configuration ---
    # Options: "LIMIT" or "MARKET"
    # LIMIT: Uses max_bid calculation, only executes if price <= max_bid
    # MARKET: Executes immediately at best available price (no max_bid check)
    ORDER_TYPE = "LIMIT"  # For real trading: "LIMIT" or "MARKET"
    
    # Simulation mode: Set to True to test BOTH strategies simultaneously
    SIMULATION_TEST_BOTH_STRATEGIES = True  # If True, simulates both LIMIT and MARKET orders
