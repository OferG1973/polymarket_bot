import logging
import asyncio
import csv
import os
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
    
    def __init__(self, executor, markets: List[Dict], poly_monitor, log_dir: str = None):
        self.executor = executor
        self.markets = markets
        self.poly_monitor = poly_monitor
        
        # Track active positions: market_id -> {entry_time, entry_price, token_id, size}
        self.active_positions: Dict[str, Dict] = {}
        
        # Track last known Polymarket prices for each market
        self.last_poly_prices: Dict[str, Dict[str, float]] = {}  # market_id -> {token_a: price, token_b: price, timestamp}
        
        # Track Binance price history per crypto
        self.binance_history: Dict[str, List[tuple]] = {}  # symbol -> [(timestamp, price), ...]
        
        # CSV logging for positions
        self.log_dir = log_dir or Config.LOG_DIR
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        # Create CSV file for position tracking
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.positions_csv_file = os.path.join(self.log_dir, f"positions_{timestamp_str}.csv")
        self._init_positions_csv()
    
    def _init_positions_csv(self):
        """Initialize CSV file for position tracking"""
        if not os.path.exists(self.positions_csv_file):
            with open(self.positions_csv_file, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Market", "Outcome", "Entry", "Exit", "Hold Time", "Profit/Loss"
                ])
            logger.info(f"📊 Position tracking CSV initialized: {self.positions_csv_file}")
    
    def _write_position_to_csv(self, market: Dict, label: str, entry_price: float, 
                               exit_price: float, hold_time_seconds: float, profit_pct: float, profit_usd: float):
        """Write complete position (entry + exit) to CSV"""
        try:
            with open(self.positions_csv_file, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    market.get('title', 'Unknown Market'),
                    label,
                    f"${entry_price:.4f}",
                    f"${exit_price:.4f}",
                    f"{hold_time_seconds:.1f}s",
                    f"{profit_pct:+.2f}% (${profit_usd:+.2f})"
                ])
        except Exception as e:
            logger.error(f"Error writing position to CSV: {e}")
    
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
        
        # Find markets related to this crypto
        related_markets = self._find_related_markets(crypto_name, symbol)
        
        # Step 2: Log market matching result
        if related_markets:
            market_names = [m.get('title', 'Unknown')[:60] for m in related_markets]
            logger.info(f"Potential Lag - Step 2) Market match found: {len(related_markets)} market(s) found for {crypto_name}: "
                       f"{', '.join(market_names[:3])}{'...' if len(market_names) > 3 else ''}")
        else:
            logger.info(f"Potential Lag - Step 2) Market match not found: No related markets found for {crypto_name} "
                       f"(moved {move_pct:+.2f}% to ${binance_price:,.2f})")
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
            market_title = market.get('title', 'unknown')[:60]
            logger.info(
                f"Potential Lag - Step 3) Skipping lag check for market: {market_title} - "
                f"active position already open for this market"
            )
            return
        
        # Check market spread before proceeding
        market_title = market.get('title', 'unknown')[:60]
        spread_acceptable, spread_reason = self.poly_monitor.check_market_spread(market_id)
        
        if not spread_acceptable:
            logger.info(f"Potential Lag - Step 3) Market filtered out: {market_title} - {spread_reason}")
            return
        
        # Get current Polymarket prices
        poly_prices = self.poly_monitor.get_market_prices(market_id)
        
        if not poly_prices:
            market_title = market.get('title', 'unknown')[:60]
            # Check which tokens are missing prices for better diagnostics
            token_a = str(market.get('token_a', ''))
            token_b = str(market.get('token_b', ''))
            price_a = self.poly_monitor.get_market_price(market_id, token_a) if token_a else None
            price_b = self.poly_monitor.get_market_price(market_id, token_b) if token_b else None
            
            missing_tokens = []
            if price_a is None:
                missing_tokens.append(f"Token A ({token_a[:8]}...)")
            if price_b is None:
                missing_tokens.append(f"Token B ({token_b[:8]}...)")
            
            missing_info = f"missing prices for: {', '.join(missing_tokens)}" if missing_tokens else "no orderbook data received yet"
            logger.info(
                f"Potential Lag - Step 3) No lag detected for market: {market_title} - "
                f"no Polymarket orderbook/price data available yet ({missing_info})"
            )
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
                
                # Step 3: Log lag detection with details
                logger.info(f"Potential Lag - Step 3) 🎯 LAG DETECTED for market: {market.get('title', 'unknown')[:60]}")
                logger.info(f"   Market Type: {market_direction.upper()}")
                logger.info(f"   Binance moved: {move_info['price_change_pct']:+.2f}% ({move_direction})")
                logger.info(f"   Buying: {side_desc}")
                logger.info(f"   Polymarket {label} price: {last_poly_price:.4f} -> {current_poly_price:.4f} ({poly_price_change_pct:+.2f}%)")
                logger.info(f"   Expected Poly move: {expected_poly_move:.2f}%")
                logger.info(f"   Time since Poly update: {time_since_update:.1f}s")
                logger.info(f"   Lag Details: Binance moved {binance_move_pct:.2f}% but Polymarket only moved {abs(poly_price_change_pct):.2f}% "
                           f"(expected ~{expected_poly_move:.2f}%), indicating {time_since_update:.1f}s lag")
                
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
                
                # Execute trade with determined outcome
                await self._execute_lag_trade(market, move_info, current_poly_price, token_id, label, side_desc)
            else:
                # Step 3: Log when lag is NOT detected
                market_title = market.get('title', 'unknown')[:60]
                if binance_move_pct <= Config.DELTA_THRESHOLD_PERCENT:
                    logger.info(f"Potential Lag - Step 3) No lag detected for market: {market_title} - "
                               f"Binance move ({binance_move_pct:.2f}%) below threshold ({Config.DELTA_THRESHOLD_PERCENT:.2f}%)")
                elif abs(poly_price_change_pct) >= expected_poly_move:
                    logger.info(f"Potential Lag - Step 3) No lag detected for market: {market_title} - "
                               f"Polymarket already reacted (moved {abs(poly_price_change_pct):.2f}%, expected {expected_poly_move:.2f}%)")
                elif time_since_update <= Config.EXPECTED_LAG_MIN:
                    logger.info(f"Potential Lag - Step 3) No lag detected for market: {market_title} - "
                               f"Polymarket updated too recently ({time_since_update:.1f}s ago, min lag: {Config.EXPECTED_LAG_MIN}s)")
                else:
                    logger.info(f"Potential Lag - Step 3) No lag detected for market: {market_title} - "
                               f"Conditions not met (Binance: {binance_move_pct:.2f}%, Poly: {abs(poly_price_change_pct):.2f}%, "
                               f"Time: {time_since_update:.1f}s)")
        else:
            # First time seeing this market, store both prices
            market_title = market.get('title', 'unknown')[:60]
            logger.info(
                f"Potential Lag - Step 3) No lag evaluation yet for market: {market_title} - "
                "first Polymarket observation, initializing baseline prices for future lag checks"
            )
            self.last_poly_prices[market_id] = {
                'token_a': poly_prices.get('token_a', 0),
                'token_b': poly_prices.get('token_b', 0),
                'timestamp': datetime.now()
            }
    
    def _calculate_max_bid(self, current_poly_price: float, binance_move_pct: float) -> float:
        """
        Calculate maximum bid price that will still produce profit
        
        Logic:
        1. Estimate expected Polymarket price movement based on Binance move
        2. Calculate expected exit price after Polymarket catches up
        3. Calculate max_bid that ensures minimum profit target
        
        Args:
            current_poly_price: Current Polymarket price for the outcome
            binance_move_pct: Binance price movement percentage (absolute value)
        
        Returns:
            max_bid: Maximum price we can pay and still make profit
        """
        # Estimate expected Polymarket move (conservative: 10% of Binance move)
        # This is the same ratio used in lag detection
        expected_poly_move_pct = abs(binance_move_pct) * 0.1
        
        # Calculate expected exit price after Polymarket catches up
        # For upward Binance move, Polymarket price should increase
        # For downward Binance move, Polymarket price should decrease
        # We use absolute value since we're buying the correct outcome
        expected_exit_price = current_poly_price * (1 + expected_poly_move_pct)
        
        # Calculate max_bid: maximum price we can pay and still achieve MIN_EXIT_PROFIT_PCT
        # Formula: (exit_price - entry_price) / entry_price >= MIN_EXIT_PROFIT_PCT
        # Solving for entry_price: entry_price <= exit_price / (1 + MIN_EXIT_PROFIT_PCT)
        max_bid = expected_exit_price / (1 + Config.MIN_EXIT_PROFIT_PCT)
        
        return max_bid
    
    async def _execute_lag_trade(self, market: Dict, move_info: Dict, entry_price: float, 
                                 token_id: str, label: str, side_desc: str):
        """Execute trade when lag is detected"""
        market_id = str(market.get('market_id', market.get('token_a', '')))
        
        market_title = market.get('title', 'unknown')[:60]
        binance_move_pct = move_info.get('price_change_pct', 0.0)
        binance_price = move_info.get('current_price', 0.0)
        
        # Determine order type for this trade
        if Config.SIMULATION_MODE and Config.SIMULATION_TEST_BOTH_STRATEGIES:
            # In simulation testing mode, we'll test both strategies
            use_limit_check = True  # Check max_bid for LIMIT strategy
        else:
            # Real trading: use configured order type
            order_type = Config.ORDER_TYPE.upper()
            use_limit_check = (order_type == "LIMIT")
        
        # Calculate max_bid: maximum price we can pay and still make profit (for LIMIT orders)
        max_bid = self._calculate_max_bid(entry_price, binance_move_pct) if use_limit_check else None
        
        # Check if current Polymarket price is acceptable (only for LIMIT orders)
        if use_limit_check and entry_price > max_bid:
            logger.info(
                f"Potential Lag - Step 4) Trade NOT executed for market: {market_title} ({label}) - "
                f"price too high: ${entry_price:.4f} > max_bid ${max_bid:.4f} "
                f"(would not achieve {Config.MIN_EXIT_PROFIT_PCT*100:.1f}% profit target)"
            )
            return
        
        # Calculate trade size
        trade_size = min(
            Config.MAX_TRADE_SIZE_USDC / entry_price,
            market.get('liquidity', 0) / 10
        )
        trade_size = max(trade_size, 1.0)
        trade_size = round(trade_size, 2)
        
        # Calculate expected profit for logging (using same logic as _calculate_max_bid)
        expected_poly_move_pct = abs(binance_move_pct) * 0.1
        expected_exit_price = entry_price * (1 + expected_poly_move_pct)
        expected_profit_pct = ((expected_exit_price - entry_price) / entry_price) * 100
        price_buffer = ((max_bid - entry_price) / entry_price) * 100 if max_bid and max_bid >= entry_price else 0

        # Step 4: Log trade decision details
        logger.info(f"Potential Lag - Step 4) Preparing trade for market: {market_title}")
        logger.info(
            f"   Outcome: {label} ({side_desc}) | Entry Price: {entry_price:.4f} | "
            f"Trade Size: {trade_size:.2f} | Binance Price: ${binance_price:,.2f} | "
            f"Binance Move: {binance_move_pct:+.2f}%"
        )
        if max_bid:
            logger.info(
                f"   Max Bid: ${max_bid:.4f} | Price Buffer: {price_buffer:+.2f}% | "
                f"Expected Exit: ${expected_exit_price:.4f} | Expected Profit: {expected_profit_pct:+.2f}%"
            )
        else:
            logger.info(
                f"   Order Type: MARKET | Expected Exit: ${expected_exit_price:.4f} | Expected Profit: {expected_profit_pct:+.2f}%"
            )

        logger.info(f"🚀 Executing LAG TRADE:")
        logger.info(f"   Market: {market_title}")
        logger.info(f"   Outcome: {label} ({side_desc})")
        if max_bid:
            logger.info(f"   Entry Price: {entry_price:.4f} (max_bid: ${max_bid:.4f})")
        else:
            logger.info(f"   Entry Price: {entry_price:.4f} (MARKET order)")
        logger.info(f"   Trade Size: {trade_size:.2f}")
        
        crypto_name = move_info.get('crypto_name', move_info['symbol'].split('/')[0])
        
        # In simulation mode: Test both LIMIT and MARKET strategies if enabled
        if Config.SIMULATION_MODE and Config.SIMULATION_TEST_BOTH_STRATEGIES:
            logger.info(f"🧪 SIMULATION MODE: Testing both LIMIT and MARKET strategies")
            
            # Strategy 1: LIMIT order with max_bid
            logger.info(f"   Testing LIMIT strategy (max_bid: ${max_bid:.4f})")
            limit_result = await self.executor.execute_arbitrage_trade(
                market=market,
                binance_price=move_info['current_price'],
                pump_pct=move_info['price_change_pct'],
                crypto_name=crypto_name,
                token_id=token_id,
                label=label,
                side_desc=side_desc,
                limit_price=entry_price,  # Use entry_price (which is <= max_bid)
                order_type="LIMIT"
            )
            
            # Strategy 2: MARKET order with current ask price
            logger.info(f"   Testing MARKET strategy (current ask: ${entry_price:.4f})")
            market_result = await self.executor.execute_arbitrage_trade(
                market=market,
                binance_price=move_info['current_price'],
                pump_pct=move_info['price_change_pct'],
                crypto_name=crypto_name,
                token_id=token_id,
                label=label,
                side_desc=side_desc,
                market_price=entry_price,  # Use current ask price
                order_type="MARKET"
            )
            
            # Record both positions for comparison (use LIMIT result for tracking)
            if limit_result and limit_result.get('success'):
                entry_time = datetime.now()
                self.active_positions[market_id] = {
                    'entry_time': entry_time,
                    'entry_price': entry_price,
                    'token_id': token_id,
                    'label': label,
                    'size': trade_size,
                    'market': market,
                    'order_type': 'LIMIT',  # Track which strategy
                    'market_price': entry_price  # Store market price for comparison
                }
                logger.info(f"Potential Lag - Step 4) LIMIT trade simulated successfully")
            
            if market_result and market_result.get('success'):
                # Also track MARKET position separately if needed
                market_position_id = f"{market_id}_MARKET"
                entry_time = datetime.now()
                self.active_positions[market_position_id] = {
                    'entry_time': entry_time,
                    'entry_price': entry_price,
                    'token_id': token_id,
                    'label': label,
                    'size': trade_size,
                    'market': market,
                    'order_type': 'MARKET',
                    'limit_price': max_bid  # Store max_bid for comparison
                }
                logger.info(f"Potential Lag - Step 4) MARKET trade simulated successfully")
            
            if limit_result and limit_result.get('success'):
                logger.info(f"✅ Position opened (LIMIT): {market_title[:50]} ({label})")
                asyncio.create_task(self._schedule_exit(market_id))
            if market_result and market_result.get('success'):
                logger.info(f"✅ Position opened (MARKET): {market_title[:50]} ({label})")
                asyncio.create_task(self._schedule_exit(market_position_id))
        else:
            # Real trading or single strategy simulation: Use configured order type
            order_type = Config.ORDER_TYPE.upper()
            
            if order_type == "MARKET":
                # Market order: use current ask price (no max_bid check)
                result = await self.executor.execute_arbitrage_trade(
                    market=market,
                    binance_price=move_info['current_price'],
                    pump_pct=move_info['price_change_pct'],
                    crypto_name=crypto_name,
                    token_id=token_id,
                    label=label,
                    side_desc=side_desc,
                    market_price=entry_price,
                    order_type="MARKET"
                )
            else:
                # Limit order: use max_bid (already checked above)
                result = await self.executor.execute_arbitrage_trade(
                    market=market,
                    binance_price=move_info['current_price'],
                    pump_pct=move_info['price_change_pct'],
                    crypto_name=crypto_name,
                    token_id=token_id,
                    label=label,
                    side_desc=side_desc,
                    limit_price=entry_price,
                    order_type="LIMIT"
                )
            
            if result and result.get('success'):
                # Record position
                entry_time = datetime.now()
                self.active_positions[market_id] = {
                    'entry_time': entry_time,
                    'entry_price': entry_price,
                    'token_id': token_id,
                    'label': label,
                    'size': trade_size,
                    'market': market,
                    'order_type': order_type
                }
                
                logger.info(f"Potential Lag - Step 4) Trade executed successfully for market: {market_title} ({label}) [{order_type}]")
                logger.info(f"✅ Position opened: {market_title[:50]} ({label})")
                
                # Schedule exit after hold time
                asyncio.create_task(self._schedule_exit(market_id))
            else:
                logger.warning(f"⚠️ Trade failed: {market_title[:50]}")
                logger.info(
                    f"Potential Lag - Step 4) Trade NOT executed for market: {market_title} ({label}) - "
                    f"executor returned failure or no confirmation"
                )
    
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
        
        # Write complete position (entry + exit) to CSV
        self._write_position_to_csv(market, label, entry_price, current_price, 
                                    hold_time_seconds, profit_pct, profit_usd)
        
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
