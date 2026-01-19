import asyncio
import logging
import os
import sys
from datetime import datetime
from config import Config
from multi_crypto_feed import MultiCryptoFeed
from polymarket_discovery import PolymarketDiscovery
from execution import PolymarketExecutor
from delta_lag_strategy import DeltaLagStrategy
from polymarket_price_monitor import PolymarketPriceMonitor

# --- LOGGING SETUP ---
if not os.path.exists(Config.LOG_DIR):
    os.makedirs(Config.LOG_DIR)

timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(Config.LOG_DIR, f"binance_polymarket_{timestamp_str}.log")

# Add custom DETAILED logging level
DETAILED_LEVEL = logging.DEBUG + 1  # Between DEBUG and INFO
logging.addLevelName(DETAILED_LEVEL, "DETAILED")

def detailed(self, message, *args, **kws):
    """Custom logging method for DETAILED level"""
    if self.isEnabledFor(DETAILED_LEVEL):
        self._log(DETAILED_LEVEL, message, args, **kws)

logging.Logger.detailed = detailed

# Set logging level based on config
if Config.LOG_LEVEL.upper() == "DETAILED":
    log_level = DETAILED_LEVEL
else:
    log_level = logging.INFO

# Configure logging
logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("Main")
logger.info(f"Logging level set to: {Config.LOG_LEVEL.upper()}")

async def main():
    """Main orchestration function"""
    logger.info("=" * 80)
    logger.info("🚀 Starting Binance-Polymarket Cross-Exchange Arbitrage Bot")
    logger.info("=" * 80)
    logger.info(f"Mode: {'SIMULATION' if Config.SIMULATION_MODE else 'LIVE TRADING'}")
    logger.info(f"Strategy: Delta Lag (High Frequency)")
    logger.info(f"Monitoring {len(Config.TOP_CRYPTOS)} cryptocurrencies:")
    for crypto in Config.TOP_CRYPTOS:
        logger.info(f"   - {crypto['name']} ({crypto['symbol']})")
    logger.info(f"Delta Threshold: {Config.DELTA_THRESHOLD_PERCENT}% in {Config.DELTA_DETECTION_WINDOW}s")
    logger.info(f"Expected Lag: {Config.EXPECTED_LAG_MIN}-{Config.EXPECTED_LAG_MAX} seconds")
    logger.info(f"Exit Hold Time: {Config.EXIT_HOLD_SECONDS} seconds")
    logger.info(f"Min Exit Profit: {Config.MIN_EXIT_PROFIT_PCT*100:.1f}%")
    logger.info("=" * 80)
    
    try:
        # 1. Initialize components
        logger.info("📡 Initializing components...")
        
        # Multi-crypto price feed (monitors all top 10 cryptos)
        multi_crypto_feed = MultiCryptoFeed(cryptos=Config.TOP_CRYPTOS)
        logger.info(f"✅ Multi-crypto feed initialized for {len(Config.TOP_CRYPTOS)} cryptocurrencies")
        
        # Polymarket discovery (searches for all crypto keywords)
        polymarket_discovery = PolymarketDiscovery(keywords=Config.CRYPTO_KEYWORDS)
        logger.info("✅ Polymarket discovery initialized")
        logger.info(f"   Searching for markets with keywords: {Config.CRYPTO_KEYWORDS[:10]}... (and more)")
        
        # Discover crypto-related markets
        logger.info("🔍 Discovering crypto-related markets on Polymarket...")
        markets = polymarket_discovery.get_top_markets(limit=Config.MAX_MARKETS_TO_MONITOR)
        logger.info(f"✅ Found {len(markets)} markets to monitor")
        
        if not markets:
            logger.error("❌ No markets found! Exiting.")
            return
        
        # Log all discovered markets
        logger.info(f"\n📊 All {len(markets)} Markets to Monitor:")
        for i, market in enumerate(markets, 1):
            market_title = market.get('title', 'Unknown Market')
            liquidity = market.get('liquidity', 0)
            market_id = market.get('market_id', 'Unknown')
            token_a = market.get('token_a', 'N/A')
            token_b = market.get('token_b', 'N/A')
            
            if Config.LOG_LEVEL.upper() == "DETAILED":
                logger.detailed(f"   {i}. {market_title}")
                logger.detailed(f"      Market ID: {market_id}")
                logger.detailed(f"      Token A: {token_a}, Token B: {token_b}")
                logger.detailed(f"      Liquidity: ${liquidity:,.0f}")
            else:
                logger.info(f"   {i}. {market_title} (Liquidity: ${liquidity:,.0f})")
        
        # Detailed logging: Log when markets are set up for monitoring
        if Config.LOG_LEVEL.upper() == "DETAILED":
            logger.detailed(f"\n🔍 Setting up monitoring for {len(markets)} markets:")
            for i, market in enumerate(markets, 1):
                market_title = market.get('title', 'Unknown Market')
                market_id = market.get('market_id', 'Unknown')
                token_a = market.get('token_a', 'N/A')
                token_b = market.get('token_b', 'N/A')
                logger.detailed(f"   {i}. {market_title} (ID: {market_id})")
                logger.detailed(f"      Monitoring tokens: {token_a}, {token_b}")
        
        # Execution engine
        executor = PolymarketExecutor()
        logger.info("✅ Execution engine initialized")
        
        # Polymarket price monitor (WebSocket)
        async def poly_price_callback(token_id: str, price: float, size: float):
            """Callback when Polymarket price updates"""
            await strategy.handle_poly_price_update(token_id, price, size)
        
        poly_monitor = PolymarketPriceMonitor(markets=markets, price_update_callback=poly_price_callback)
        logger.info("✅ Polymarket price monitor initialized")
        
        # Delta lag strategy
        strategy = DeltaLagStrategy(executor=executor, markets=markets, poly_monitor=poly_monitor)
        logger.info("✅ Delta lag strategy initialized")
        
        # Set Binance move callback
        multi_crypto_feed.set_pump_callback(strategy.handle_binance_move)
        
        # 2. Start monitoring
        print("\n" + "=" * 80)
        print("🎯 Starting WebSocket Monitoring...")
        print("=" * 80)
        print(f"Connecting to Binance WebSocket for {len(Config.TOP_CRYPTOS)} cryptocurrencies:")
        for crypto in Config.TOP_CRYPTOS:
            print(f"   - {crypto['name']} ({crypto['symbol']})")
        print(f"Connecting to Polymarket WebSocket for {len(markets)} markets")
        print(f"Delta Threshold: {Config.DELTA_THRESHOLD_PERCENT}% move in {Config.DELTA_DETECTION_WINDOW}s")
        print("=" * 80 + "\n")
        
        logger.info("\n" + "=" * 80)
        logger.info("🎯 Starting monitoring...")
        logger.info("=" * 80)
        logger.info(f"Monitoring {len(Config.TOP_CRYPTOS)} cryptocurrencies on Binance:")
        for crypto in Config.TOP_CRYPTOS:
            logger.info(f"   - {crypto['name']} ({crypto['symbol']})")
        logger.info(f"Monitoring {len(markets)} markets on Polymarket")
        logger.info(f"Delta Threshold: {Config.DELTA_THRESHOLD_PERCENT}% move in {Config.DELTA_DETECTION_WINDOW}s")
        logger.info("=" * 80 + "\n")
        
        # Start both Binance and Polymarket monitoring concurrently
        await asyncio.gather(
            multi_crypto_feed.start_monitoring(),
            poly_monitor.start_monitoring()
        )
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
    finally:
        logger.info("👋 Shutting down...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Bot stopped by user")
