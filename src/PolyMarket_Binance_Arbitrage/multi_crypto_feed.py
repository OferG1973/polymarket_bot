import asyncio
import logging
from typing import List, Dict, Callable
from binance_feed import BinancePriceFeed
from config import Config

logger = logging.getLogger("MultiCryptoFeed")

class MultiCryptoFeed:
    """Monitors multiple cryptocurrencies simultaneously for pump detection"""
    
    def __init__(self, cryptos: List[Dict] = None):
        """
        Initialize multi-crypto feed
        
        Args:
            cryptos: List of crypto dicts with 'symbol' and 'name' keys
        """
        self.cryptos = cryptos or Config.TOP_CRYPTOS
        self.feeds: Dict[str, BinancePriceFeed] = {}
        self.pump_callback: Callable = None
        
        # Initialize feed for each crypto
        for crypto in self.cryptos:
            symbol = crypto['symbol']
            name = crypto['name']
            feed = BinancePriceFeed(symbol=symbol)
            feed.symbol_name = name  # Store crypto name for logging
            self.feeds[symbol] = feed
            logger.info(f"✅ Initialized feed for {name} ({symbol})")
    
    def set_pump_callback(self, callback: Callable):
        """Set callback function to be called when pump is detected on any crypto"""
        self.pump_callback = callback
        # Set callback for all feeds
        for feed in self.feeds.values():
            feed.set_pump_callback(self._handle_pump)
    
    async def _handle_pump(self, pump_info: Dict):
        """Internal handler that adds crypto name to pump info before calling main callback"""
        # Find crypto name from symbol
        symbol = pump_info['symbol']
        crypto_name = None
        for crypto in self.cryptos:
            if crypto['symbol'] == symbol:
                crypto_name = crypto['name']
                break
        
        # Add crypto name to pump info
        pump_info['crypto_name'] = crypto_name or symbol.split('/')[0]
        
        # Call main callback
        if self.pump_callback:
            await self.pump_callback(pump_info)
    
    async def start_monitoring(self):
        """Start monitoring all cryptocurrencies concurrently"""
        logger.info(f"🚀 Starting multi-crypto monitoring for {len(self.feeds)} cryptocurrencies")
        logger.info(f"   Monitoring: {', '.join([c['name'] for c in self.cryptos])}")
        
        # Create tasks for all feeds
        tasks = []
        for symbol, feed in self.feeds.items():
            task = asyncio.create_task(feed.start_monitoring())
            tasks.append(task)
            logger.info(f"   Started monitoring task for {feed.symbol_name} ({symbol})")
        
        # Wait for all tasks (they run indefinitely)
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in multi-crypto monitoring: {e}")
            # Cancel all tasks
            for task in tasks:
                task.cancel()
            raise
    
    def get_current_prices(self) -> Dict[str, float]:
        """Get current prices for all monitored cryptocurrencies"""
        prices = {}
        for symbol, feed in self.feeds.items():
            price = feed.current_price
            if price:
                prices[symbol] = price
        return prices
