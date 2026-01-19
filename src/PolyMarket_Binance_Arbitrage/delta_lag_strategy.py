import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from config import Config

logger = logging.getLogger("DeltaLagStrategy")

class DeltaLagStrategy:
    """
    High-Frequency Delta Lag Strategy
    
    Concept:
    - Binance moves instantly (leader)
    - Polymarket lags 2-10 seconds (laggard)
    - Detect when Binance moves >0.2% but Polymarket hasn't updated yet
    - Buy immediately, exit after 30 seconds when Polymarket catches up
    """
    
    def __init__(self, executor, markets: List[Dict], poly_monitor):
        self.executor = executor
        self.markets = markets
        self.poly_monitor = poly_monitor
        
        # Track active positions: market_id -> {entry_time, entry_price, token_id, size}
        self.active_positions: Dict[str, Dict] = {}
        
        # Track last known Polymarket prices for each market
        self.last_poly_prices: Dict[str, Dict[str, float]] = {}  # market_id -> {token_a: price, token_b: price, timestamp}
        
        # Track Binance price history per crypto
        self.binance_history: Dict[str, List[tuple]] = {}  # symbol -> [(timestamp, price), ...]
    
    async def handle_binance_move(self, move_info: Dict):
        """
        Handle Binance delta move detection
        Check if Polymarket has lagged behind
        Now supports both upward and downward moves
        """
        symbol = move_info['symbol']
        crypto_name = move_info.get('crypto_name', symbol.split('/')[0])
        binance_price = move_info['current_price']
        move_pct = move_info['price_change_pct']
        direction = move_info['direction']
        
        # Trade on both upward and downward moves
        direction_emoji = "📈" if direction == 'up' else "📉"
        logger.info(f"{direction_emoji} Binance Move: {crypto_name} moved {move_pct:+.2f}% to ${binance_price:,.2f}")
        
        # Find markets related to this crypto
        related_markets = self._find_related_markets(crypto_name, symbol)
        
        if not related_markets:
            logger.debug(f"   No related markets found for {crypto_name}")
            return
        
        # Check each market for lag opportunity
        for market in related_markets:
            await self._check_lag_opportunity(market, move_info)
    
    def _find_related_markets(self, crypto_name: str, symbol: str) -> List[Dict]:
        """Find Polymarket markets related to this cryptocurrency"""
        related = []
        crypto_keywords = [crypto_name.lower(), symbol.split('/')[0].lower()]
        
        for market in self.markets:
            title = market.get('title', '').lower()
            # Check if market title contains crypto keywords
            if any(keyword in title for keyword in crypto_keywords):
                related.append(market)
        
        return related
    
    def _determine_market_direction(self, market: Dict) -> str:
        """
        Determine if market is bullish (above X) or bearish (below X)
        Returns: 'bullish' or 'bearish'
        """
        title = market.get('title', '').lower()
        
        # Check for bearish indicators (below, under, less than, dip to)
        bearish_keywords = ['below', 'under', 'less than', 'dip to', 'drop to', 'fall to', '<']
        if any(keyword in title for keyword in bearish_keywords):
            return 'bearish'
        
        # Check for bullish indicators (above, over, reach, hit, exceed, >)
        bullish_keywords = ['above', 'over', 'reach', 'hit', 'exceed', '>', 'higher']
        if any(keyword in title for keyword in bullish_keywords):
            return 'bullish'
        
        # Default to bullish (most markets are "above X" type)
        return 'bullish'
    
    def _determine_outcome_to_buy(self, market: Dict, move_direction: str) -> tuple:
        """
        Determine which outcome to buy based on market direction and price move direction
        
        Returns: (token_id, label, price, side_description)
        """
        market_direction = self._determine_market_direction(market)
        
        # Logic:
        # Bullish market (e.g., "Bitcoin > $100k"):
        #   - Upward move → Buy YES (price going up makes "above X" more likely)
        #   - Downward move → Buy NO (price going down makes "above X" less likely)
        # Bearish market (e.g., "Bitcoin < $50k"):
        #   - Upward move → Buy NO (price going up makes "below X" less likely)
        #   - Downward move → Buy YES (price going down makes "below X" more likely)
        
        if market_direction == 'bullish':
            if move_direction == 'up':
                # Bullish market + upward move = Buy YES
                return (market.get('token_a'), market.get('label_a', 'YES'), 
                       market.get('price_a', 0), 'YES (bullish market, price up)')
            else:
                # Bullish market + downward move = Buy NO
                return (market.get('token_b'), market.get('label_b', 'NO'), 
                       market.get('price_b', 0), 'NO (bullish market, price down)')
        else:  # bearish
            if move_direction == 'up':
                # Bearish market + upward move = Buy NO
                return (market.get('token_b'), market.get('label_b', 'NO'), 
                       market.get('price_b', 0), 'NO (bearish market, price up)')
            else:
                # Bearish market + downward move = Buy YES
                return (market.get('token_a'), market.get('label_a', 'YES'), 
                       market.get('price_a', 0), 'YES (bearish market, price down)')
    
    async def _check_lag_opportunity(self, market: Dict, move_info: Dict):
        """Check if there's a lag opportunity for this market"""
        market_id = str(market.get('market_id', market.get('token_a', '')))
        
        # Skip if already have position
        if market_id in self.active_positions:
            return
        
        # Get current Polymarket prices
        poly_prices = self.poly_monitor.get_market_prices(market_id)
        
        if not poly_prices:
            logger.debug(f"   No Polymarket price data for {market.get('title', 'unknown')[:50]}")
            return
        
        # Get last known Polymarket price
        last_poly = self.last_poly_prices.get(market_id)
        
        # Determine which outcome to buy based on market and move direction
        move_direction = move_info['direction']
        token_id, label, price, side_desc = self._determine_outcome_to_buy(market, move_direction)
        
        # Get current and last prices for the relevant outcome
        if token_id == market.get('token_a'):
            current_poly_price = poly_prices.get('token_a', 0)
            last_poly_price_key = 'token_a'
        else:
            current_poly_price = poly_prices.get('token_b', 0)
            last_poly_price_key = 'token_b'
        
        if last_poly:
            last_poly_price = last_poly.get(last_poly_price_key, current_poly_price)
            last_timestamp = last_poly.get('timestamp', datetime.now())
            time_since_update = (datetime.now() - last_timestamp).total_seconds()
            
            # Check if Polymarket price hasn't moved despite Binance move
            poly_price_change = current_poly_price - last_poly_price
            poly_price_change_pct = ((current_poly_price - last_poly_price) / last_poly_price * 100) if last_poly_price > 0 else 0
            
            # Binance move magnitude (absolute value)
            binance_move_pct = abs(move_info['price_change_pct'])
            
            # Lag condition: Binance moved significantly, but Polymarket hasn't reacted proportionally
            # Expected: If Bitcoin moves 0.3%, Polymarket price should move ~0.03% (10% of Binance move)
            # If Polymarket hasn't moved much (< expected), there's lag
            expected_poly_move = binance_move_pct * 0.1  # Rough estimate: 10% of Binance move
            
            # Check lag for both directions (absolute move threshold)
            if (binance_move_pct > Config.DELTA_THRESHOLD_PERCENT and 
                abs(poly_price_change_pct) < expected_poly_move and
                time_since_update > Config.EXPECTED_LAG_MIN):
                # LAG DETECTED! Polymarket hasn't reacted yet
                market_direction = self._determine_market_direction(market)
                direction_emoji = "📈" if move_direction == 'up' else "📉"
                
                print("\n" + "="*80)
                print("🚨 TRADE SIGNALS 🚨")
                print("="*80)
                print(f"MICRO-LAG DETECTED!")
                print(f"Market: {market.get('title', 'unknown')}")
                print(f"Market Type: {market_direction.upper()}")
                print(f"Binance moved: {move_info['price_change_pct']:+.2f}% ({direction_emoji})")
                print(f"Buying: {side_desc}")
                print(f"Polymarket {label} price: {last_poly_price:.4f} -> {current_poly_price:.4f} ({poly_price_change_pct:+.2f}%)")
                print(f"Expected Poly move: {expected_poly_move:.2f}%")
                print(f"Time since Poly update: {time_since_update:.1f}s")
                print("="*80 + "\n")
                
                logger.info(f"🎯 LAG DETECTED: {market.get('title', 'unknown')[:60]}")
                logger.info(f"   Market Type: {market_direction.upper()}")
                logger.info(f"   Binance moved: {move_info['price_change_pct']:+.2f}% ({move_direction})")
                logger.info(f"   Buying: {side_desc}")
                logger.info(f"   Polymarket {label} price: {last_poly_price:.4f} -> {current_poly_price:.4f} ({poly_price_change_pct:+.2f}%)")
                logger.info(f"   Expected Poly move: {expected_poly_move:.2f}%")
                logger.info(f"   Time since Poly update: {time_since_update:.1f}s")
                
                # Execute trade with determined outcome
                await self._execute_lag_trade(market, move_info, current_poly_price, token_id, label, side_desc)
        else:
            # First time seeing this market, store both prices
            self.last_poly_prices[market_id] = {
                'token_a': poly_prices.get('token_a', 0),
                'token_b': poly_prices.get('token_b', 0),
                'timestamp': datetime.now()
            }
    
    async def _execute_lag_trade(self, market: Dict, move_info: Dict, entry_price: float, 
                                 token_id: str, label: str, side_desc: str):
        """Execute trade when lag is detected"""
        market_id = str(market.get('market_id', market.get('token_a', '')))
        
        # Calculate trade size
        trade_size = min(
            Config.MAX_TRADE_SIZE_USDC / entry_price,
            market.get('liquidity', 0) / 10
        )
        trade_size = max(trade_size, 1.0)
        trade_size = round(trade_size, 2)
        
        logger.info(f"🚀 Executing LAG TRADE:")
        logger.info(f"   Market: {market.get('title', 'unknown')[:60]}")
        logger.info(f"   Outcome: {label} ({side_desc})")
        logger.info(f"   Entry Price: {entry_price:.4f}")
        logger.info(f"   Trade Size: {trade_size:.2f}")
        
        # Execute buy order
        crypto_name = move_info.get('crypto_name', move_info['symbol'].split('/')[0])
        result = await self.executor.execute_arbitrage_trade(
            market=market,
            binance_price=move_info['current_price'],
            pump_pct=move_info['price_change_pct'],
            crypto_name=crypto_name,
            token_id=token_id,
            label=label,
            side_desc=side_desc
        )
        
        if result and result.get('success'):
            # Record position
            self.active_positions[market_id] = {
                'entry_time': datetime.now(),
                'entry_price': entry_price,
                'token_id': token_id,
                'label': label,
                'size': trade_size,
                'market': market
            }
            
            logger.info(f"✅ Position opened: {market.get('title', 'unknown')[:50]} ({label})")
            
            # Schedule exit after hold time
            asyncio.create_task(self._schedule_exit(market_id))
        else:
            logger.warning(f"⚠️ Trade failed: {market.get('title', 'unknown')[:50]}")
    
    async def _schedule_exit(self, market_id: str):
        """Schedule exit after hold time"""
        await asyncio.sleep(Config.EXIT_HOLD_SECONDS)
        
        if market_id in self.active_positions:
            await self._exit_position(market_id)
    
    async def _exit_position(self, market_id: str):
        """Exit a position after Polymarket has caught up"""
        if market_id not in self.active_positions:
            return
        
        position = self.active_positions[market_id]
        market = position['market']
        entry_price = position['entry_price']
        entry_time = position['entry_time']
        
        # Get current Polymarket price
        poly_prices = self.poly_monitor.get_market_prices(market_id)
        
        if not poly_prices:
            logger.warning(f"⚠️ Cannot exit: No price data for {market.get('title', 'unknown')[:50]}")
            return
        
        # Get current price for the token we bought
        token_id = position['token_id']
        label = position.get('label', 'Unknown')
        if token_id == market.get('token_a'):
            current_price = poly_prices.get('token_a', entry_price)
        else:
            current_price = poly_prices.get('token_b', entry_price)
        
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        profit_usd = (current_price - entry_price) * position['size']
        hold_time_seconds = (datetime.now() - entry_time).total_seconds()
        
        profit_emoji = "💰" if profit_pct > 0 else "📉" if profit_pct < 0 else "➖"
        logger.info(f"{profit_emoji} EXITING POSITION:")
        logger.info(f"   Market: {market.get('title', 'unknown')[:60]}")
        logger.info(f"   Outcome: {label}")
        logger.info(f"   Entry: ${entry_price:.4f} @ {entry_time.strftime('%H:%M:%S')}")
        logger.info(f"   Exit: ${current_price:.4f} @ {datetime.now().strftime('%H:%M:%S')}")
        logger.info(f"   Hold Time: {hold_time_seconds:.1f}s")
        logger.info(f"   Profit/Loss: {profit_pct:+.2f}% (${profit_usd:+.2f})")
        
        # Check if profit meets minimum threshold
        if profit_pct >= Config.MIN_EXIT_PROFIT_PCT * 100:
            # Execute sell (in real trading, this would place a sell order)
            logger.info(f"✅ Exiting position with {profit_pct:.2f}% profit")
            del self.active_positions[market_id]
        else:
            logger.info(f"⏳ Holding position: Profit {profit_pct:.2f}% below threshold {Config.MIN_EXIT_PROFIT_PCT*100:.2f}%")
    
    async def handle_poly_price_update(self, token_id: str, price: float, size: float):
        """Handle Polymarket price update - update our tracking"""
        # Find which market this token belongs to
        for market in self.markets:
            market_id = str(market.get('market_id', market.get('token_a', '')))
            if str(market.get('token_a')) == str(token_id) or str(market.get('token_b')) == str(token_id):
                # Update last known price
                self.last_poly_prices[market_id] = {
                    'token_a': price if str(market.get('token_a')) == str(token_id) else self.last_poly_prices.get(market_id, {}).get('token_a', price),
                    'token_b': price if str(market.get('token_b')) == str(token_id) else self.last_poly_prices.get(market_id, {}).get('token_b', price),
                    'timestamp': datetime.now()
                }
                
                # Check if we should exit any positions
                if market_id in self.active_positions:
                    await self._check_exit_conditions(market_id)
                break
    
    async def _check_exit_conditions(self, market_id: str):
        """Check if position should be exited based on current prices"""
        if market_id not in self.active_positions:
            return
        
        position = self.active_positions[market_id]
        entry_time = position['entry_time']
        entry_price = position['entry_price']
        hold_time = (datetime.now() - entry_time).total_seconds()
        
        # Get current Polymarket price for the position
        poly_prices = self.poly_monitor.get_market_prices(market_id)
        if not poly_prices:
            return
        
        market = position['market']
        token_id = position['token_id']
        label = position.get('label', 'Unknown')
        
        # Get current price for the token we bought
        if token_id == market.get('token_a'):
            current_price = poly_prices.get('token_a', entry_price)
        else:
            current_price = poly_prices.get('token_b', entry_price)
        
        # Calculate current profit/loss
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        profit_usd = (current_price - entry_price) * position['size']
        
        # Log profit/loss update (every 5 seconds to avoid spam)
        if not hasattr(position, 'last_profit_log_time'):
            position['last_profit_log_time'] = entry_time
        
        time_since_last_log = (datetime.now() - position['last_profit_log_time']).total_seconds()
        if time_since_last_log >= 5.0:  # Log every 5 seconds
            profit_emoji = "💰" if profit_pct > 0 else "📉" if profit_pct < 0 else "➖"
            logger.info(f"{profit_emoji} Position P&L: {market.get('title', 'unknown')[:50]} ({label}) | "
                       f"Entry: ${entry_price:.4f} | Current: ${current_price:.4f} | "
                       f"Profit: {profit_pct:+.2f}% (${profit_usd:+.2f}) | Hold: {hold_time:.1f}s")
            position['last_profit_log_time'] = datetime.now()
        
        # Check for early exit if profit threshold met before hold time
        if profit_pct >= Config.MIN_EXIT_PROFIT_PCT * 100 and hold_time >= 10:  # At least 10 seconds
            logger.info(f"✅ Early exit triggered: Profit {profit_pct:.2f}% reached before hold time")
            await self._exit_position(market_id)
        # Exit if hold time exceeded
        elif hold_time >= Config.EXIT_HOLD_SECONDS:
            await self._exit_position(market_id)
