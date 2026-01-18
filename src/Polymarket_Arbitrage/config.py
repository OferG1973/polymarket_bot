import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Auth
    HOST = "https://clob.polymarket.com"
    CHAIN_ID = 137
    PRIVATE_KEY = os.getenv("PRIVATE_KEY")
    API_KEY = os.getenv("POLY_API_KEY")
    API_SECRET = os.getenv("POLY_API_SECRET")
    PASSPHRASE = os.getenv("POLY_PASSPHRASE")

    # --- EXPERT DISCOVERY SETTINGS ---
    # Max markets to subscribe to (Prevents CPU meltdown)
    # A standard laptop can handle ~100-200. A VPS can handle 500+.
    MAX_MARKETS_TO_TRACK = 150 
    
    # We don't care about markets with $0 liquidity (can't trade them)
    # Filter out the junk.
    MIN_LIQUIDITY_USDC = 500.0 

    # --- Risk ---
    MAX_TRADE_SIZE_USDC = 50.0
    MIN_PROFIT_SPREAD = 0.015
    SIMULATION_MODE = True
    SIM_CSV_FILE = "sim_trades.csv"