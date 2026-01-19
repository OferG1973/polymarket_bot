import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Set
from config import Config

logger = logging.getLogger("Strategy")

class CrossExchangeStrategy:
    """
    Strategy: When Binance pumps >4.5% in 1 minute, buy Polymarket markets
    before the crowd reacts (10-30 second lag)
    """
    
    def __init__(self, executor, markets: List[Dict]):
        self.executor = executor
        self.markets = markets
        
        # Track which markets we've traded recently (cooldown)
        self.market_cooldowns: Dict[str, datetime] = {}
        
        # Track active positions
        self.active_positions: Set[str] = set()
    
    def _is_market_in_cooldown(self, market_id: str) -> bool:
        """Check if market is in cooldown period"""
        if market_id not in self.market_cooldowns:
            return False
        
        last_trade_time = self.market_cooldowns[market_id]
        cooldown_end = last_trade_time + timedelta(seconds=Config.COOLDOWN_SECONDS)
        
        return datetime.now() < cooldown_end
    
    def _update_cooldown(self, market_id: str):
        """Update cooldown timestamp for market"""
        self.market_cooldowns[market_id] = datetime.now()
    
    async def handle_pump(self, pump_info: Dict):
        """
        Handle Binance pump detection
        Execute trades on related Polymarket markets
        """
        binance_price = pump_info['current_price']
        pump_pct = pump_info['price_change_pct']
        symbol = pump_info['symbol']
        crypto_name = pump_info.get('crypto_name', symbol.split('/')[0])
        
        logger.info(f"🎯 HANDLING PUMP: {crypto_name} ({symbol}) pumped {pump_pct:.2f}% to ${binance_price:,.2f}")
        
        # Filter markets that are eligible for trading
        eligible_markets = []
        
        for market in self.markets:
            market_id = str(market.get('market_id', market.get('token_a', '')))
            
            # Skip if in cooldown
            if self._is_market_in_cooldown(market_id):
                logger.debug(f"   Market in cooldown: {market['title'][:50]}...")
                continue
            
            # Skip if already have position
            if market_id in self.active_positions:
                logger.debug(f"   Already have position: {market['title'][:50]}...")
                continue
            
            # Check if market is still valid (has liquidity, etc.)
            if market.get('liquidity', 0) < Config.MIN_LIQUIDITY_USDC:
                continue
            
            eligible_markets.append(market)
        
        if not eligible_markets:
            logger.warning("⚠️ No eligible markets for trading")
            return
        
        logger.info(f"📊 Found {len(eligible_markets)} eligible markets")
        
        # Execute trades on eligible markets
        # Limit to prevent over-trading
        max_trades = min(len(eligible_markets), Config.MAX_POSITIONS_PER_MARKET * len(eligible_markets))
        
        for i, market in enumerate(eligible_markets[:max_trades]):
            try:
                market_id = str(market.get('market_id', market.get('token_a', '')))
                
                logger.info(f"🚀 Executing trade {i+1}/{max_trades}: {market['title'][:60]}...")
                
                # Execute trade
                result = await self.executor.execute_arbitrage_trade(
                    market=market,
                    binance_price=binance_price,
                    pump_pct=pump_pct,
                    crypto_name=crypto_name
                )
                
                if result and result.get('success'):
                    # Mark as traded
                    self._update_cooldown(market_id)
                    self.active_positions.add(market_id)
                    
                    logger.info(f"✅ Trade executed successfully on: {market['title'][:50]}...")
                else:
                    logger.warning(f"⚠️ Trade failed for: {market['title'][:50]}...")
                
                # Small delay between trades to avoid rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error executing trade on market {market.get('title', 'unknown')}: {e}")
                continue
        
        logger.info(f"✅ Completed pump handling: {len(eligible_markets)} markets processed")
    
    def update_markets(self, markets: List[Dict]):
        """Update the list of markets to monitor"""
        self.markets = markets
        logger.info(f"Updated strategy with {len(markets)} markets")
