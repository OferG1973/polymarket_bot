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
    # Polymarket fee structure (based on official docs):
    # - Most markets: NO PLATFORM FEES (fee-free trading)
    # - US-regulated venue (Polymarket US): 0.01% (1 basis point) taker fee on premium
    # - 15-minute crypto markets: taker fees (varies, check specific market)
    #
    # GAS FEES (Blockchain Network Fees - NOT Polymarket fees):
    # - Gas fees are Polygon network transaction costs, NOT Polymarket platform fees
    # - On Polygon: ~$0.01-$0.10 per transaction (very low)
    # - If using Polymarket's Builder/Relayer system with proxy wallets, gas may be covered
    # - If using regular wallet (MetaMask, etc.), you pay gas in MATIC
    # - For arbitrage: 2 transactions (one per outcome) = ~$0.02-$0.20 total
    # - Slippage: 0.5-5% depending on liquidity (already accounted for in order book prices)
    #
    # NOTE: The 2% profit fee previously assumed for international markets appears to be INCORRECT.
    # Most Polymarket markets are fee-free. Only US-regulated venue and specific market types have fees.
    MARKET_TYPE = "standard"  # Options: "standard" (fee-free), "us" (0.01% taker fee), "crypto_15min" (varies)
    
    # Gas fee configuration
    # Set to True if using Polymarket's Builder/Relayer system (gas covered by Polymarket)
    # Set to False if using regular wallet (you pay Polygon gas fees)
    USE_GASLESS_TRADING = False  # Change to True if using builder/relayer system
    
    # --- Risk ---
    MAX_TRADE_SIZE_USDC = 20000.0
    # Minimum gross profit spread to enter arbitrage (before fees)
    # For standard markets: ~0.3-0.5% gross needed to net ~0.2-0.4% after gas (if applicable)
    # For US markets: ~0.4-0.6% gross needed to net ~0.2-0.4% after 0.01% taker fee + gas (if applicable)
    MIN_PROFIT_SPREAD = 0.005 if MARKET_TYPE == "standard" else 0.006  # 0.5% for standard, 0.6% for US
    SIMULATION_MODE = True
    SIM_CSV_FILE = "sim_trades.csv"  # Individual order log
    ARB_CSV_FILE = "arbitrage_trades.csv"  # Complete arbitrage trade log
    
    # Fee rates (as decimals)
    # Most markets are fee-free - no profit fees, no taker fees
    PROFIT_FEE_RATE = 0.0  # No profit fees on Polymarket (previously incorrectly assumed 2%)
    TAKER_FEE_RATE = 0.0001 if MARKET_TYPE == "us" else 0.0  # 0.01% taker fee only for US-regulated venue
    
    # Gas costs (Polygon network fees - only apply if not using gasless trading)
    # Based on official docs: Polygon gas is ~$0.01-$0.10 per transaction
    # Using conservative estimate of $0.05 per transaction
    ESTIMATED_GAS_COST_PER_TRADE = 0.05 if not USE_GASLESS_TRADING else 0.0  # $0.05 per trade on Polygon (or $0 if gasless)
    TOTAL_GAS_COST = ESTIMATED_GAS_COST_PER_TRADE * 2  # 2 trades (one for each outcome) = ~$0.10 total
    
    # Minimum NET profit spread required (after all fees)
    # For standard markets: gross spread needs to be ~0.3-0.5% to net ~0.2-0.4% after gas (if applicable)
    # For US: gross spread needs to be ~0.4-0.6% to net ~0.2-0.4% after 0.01% taker fee + gas (if applicable)
    MIN_NET_PROFIT_SPREAD = 0.002  # Minimum 0.2% net profit after all fees