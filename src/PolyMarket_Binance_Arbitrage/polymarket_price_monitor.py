import asyncio
import aiohttp
import logging
import socket
import ssl
import json
from typing import Dict, Optional, Callable, Tuple
from datetime import datetime
from models import LocalOrderBook
from config import Config
from websocket_health import health_monitor

logger = logging.getLogger("PolyPriceMonitor")

class PolymarketPriceMonitor:
    """Monitors Polymarket prices in real-time via WebSocket"""
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    def __init__(self, markets: list, price_update_callback: Optional[Callable] = None):
        """
        Initialize Polymarket price monitor
        
        Args:
            markets: List of market dicts with token_a and token_b
            price_update_callback: Callback when price updates (market_id, token_id, price, size)
        """
        self.markets = markets
        self.price_update_callback = price_update_callback
        
        # Create order books for each token
        self.books: Dict[str, LocalOrderBook] = {}
        self.token_ids = set()
        
        for market in markets:
            token_a = str(market.get('token_a'))
            token_b = str(market.get('token_b'))
            if token_a:
                self.token_ids.add(token_a)
                if token_a not in self.books:
                    self.books[token_a] = LocalOrderBook(token_a)
            if token_b:
                self.token_ids.add(token_b)
                if token_b not in self.books:
                    self.books[token_b] = LocalOrderBook(token_b)
        
        # Track last known prices for each market
        self.last_prices: Dict[str, Dict[str, float]] = {}  # market_id -> {token_a: price, token_b: price}
        
        # Track last price update time for periodic logging
        self.last_summary_log = datetime.now()
        self.price_update_count = 0
        
        # Track which tokens have received their first WebSocket data (for INFO level logging)
        self.first_token_data_received: set = set()  # Set of token_ids that have received first data
        self.both_tokens_initialized: set = set()  # Set of market_ids where both tokens have prices
        
        logger.info(f"✅ Initialized price monitor for {len(self.token_ids)} tokens across {len(markets)} markets")
        
        # Detailed logging: Log each market being monitored
        if Config.LOG_LEVEL.upper() == "DETAILED":
            try:
                DETAILED_LEVEL = logging.DEBUG + 1
                if logger.isEnabledFor(DETAILED_LEVEL):
                    logger.log(DETAILED_LEVEL, f"📊 Monitoring {len(markets)} Polymarket markets:")
                    for i, market in enumerate(markets, 1):
                        market_title = market.get('title', 'Unknown Market')
                        market_id = market.get('market_id', 'Unknown')
                        token_a = market.get('token_a', 'N/A')
                        token_b = market.get('token_b', 'N/A')
                        logger.log(DETAILED_LEVEL, f"   {i}. {market_title}")
                        logger.log(DETAILED_LEVEL, f"      Market ID: {market_id}")
                        logger.log(DETAILED_LEVEL, f"      Token A: {token_a}, Token B: {token_b}")
            except Exception:
                pass  # Don't break on logging errors
    
    def get_market_price(self, market_id: str, token_id: str) -> Optional[float]:
        """Get current best ask price for a token in a market"""
        book = self.books.get(str(token_id))
        if book:
            price, _ = book.get_best_ask()
            return price
        return None
    
    def get_market_prices(self, market_id: str) -> Optional[Dict[str, float]]:
        """Get current prices for both tokens in a market"""
        market = next((m for m in self.markets if str(m.get('market_id', '')) == market_id), None)
        if not market:
            return None
        
        token_a = str(market.get('token_a'))
        token_b = str(market.get('token_b'))
        
        price_a = self.get_market_price(market_id, token_a)
        price_b = self.get_market_price(market_id, token_b)
        
        if price_a is not None and price_b is not None:
            return {
                'token_a': price_a,
                'token_b': price_b,
                'total': price_a + price_b
            }
        return None
    
    def get_token_spread_pct(self, token_id: str) -> Optional[float]:
        """Get the bid/ask spread percentage for a token"""
        book = self.books.get(str(token_id))
        if not book:
            return None
        
        bid_price, _ = book.get_best_bid()
        ask_price, _ = book.get_best_ask()
        
        if bid_price is None or ask_price is None or bid_price <= 0:
            return None
        
        spread_pct = ((ask_price - bid_price) / bid_price) * 100
        return spread_pct
    
    def check_market_spread(self, market_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if market spread is acceptable for trading
        Returns: (is_acceptable, reason_if_not)
        """
        market = next((m for m in self.markets if str(m.get('market_id', '')) == market_id), None)
        if not market:
            return False, "Market not found"
        
        token_a = str(market.get('token_a'))
        token_b = str(market.get('token_b'))
        
        # Get spreads for both tokens
        spread_a = self.get_token_spread_pct(token_a)
        spread_b = self.get_token_spread_pct(token_b)
        
        # Check if we have valid spreads
        if spread_a is None and spread_b is None:
            return False, "No bid/ask data available for either token"
        
        # Check token A spread
        if spread_a is not None and spread_a > Config.MAX_SPREAD_PCT:
            label_a = market.get('label_a', 'YES')
            return False, f"{label_a} token spread ({spread_a:.2f}%) exceeds maximum ({Config.MAX_SPREAD_PCT:.2f}%)"
        
        # Check token B spread
        if spread_b is not None and spread_b > Config.MAX_SPREAD_PCT:
            label_b = market.get('label_b', 'NO')
            return False, f"{label_b} token spread ({spread_b:.2f}%) exceeds maximum ({Config.MAX_SPREAD_PCT:.2f}%)"
        
        # If we only have one token's spread, that's acceptable if it's within limit
        if spread_a is None or spread_b is None:
            # At least one token has acceptable spread
            return True, None
        
        # Both tokens have acceptable spreads
        return True, None
    
    def _check_and_log_both_tokens_initialized(self, asset_id: str):
        """Check if both tokens for any market containing this asset_id are now initialized"""
        asset_id_str = str(asset_id)
        
        for market in self.markets:
            market_id = str(market.get('market_id', market.get('token_a', '')))
            token_a = str(market.get('token_a', ''))
            token_b = str(market.get('token_b', ''))
            
            # Check if this asset_id belongs to this market
            if asset_id_str == token_a or asset_id_str == token_b:
                # Skip if already initialized
                if market_id in self.both_tokens_initialized:
                    continue
                
                # Get prices for both tokens
                token_a_price = None
                token_b_price = None
                book_a = self.books.get(token_a)
                book_b = self.books.get(token_b)
                
                if book_a:
                    ask_a, _ = book_a.get_best_ask()
                    if ask_a:
                        token_a_price = ask_a
                
                if book_b:
                    ask_b, _ = book_b.get_best_ask()
                    if ask_b:
                        token_b_price = ask_b
                
                # If both tokens have prices, log initialization
                if token_a_price is not None and token_b_price is not None:
                    self.both_tokens_initialized.add(market_id)
                    market_title = market.get('title', 'Unknown Market')
                    label_a = market.get('label_a', 'YES')
                    label_b = market.get('label_b', 'NO')
                    total_price = token_a_price + token_b_price
                    spread_pct = abs(total_price - 1.0) * 100
                    logger.info(f"✅ Market fully initialized (both tokens): {market_title} | "
                               f"{label_a}: ${token_a_price:.4f} | {label_b}: ${token_b_price:.4f} | "
                               f"Total: ${total_price:.4f} (spread: {spread_pct:.2f}%)")
                break  # Found the market, no need to continue
    
    def _log_all_market_prices(self):
        """Log all market prices in a summary format"""
        try:
            DETAILED_LEVEL = logging.DEBUG + 1
            if not logger.isEnabledFor(DETAILED_LEVEL):
                return
            
            logger.log(DETAILED_LEVEL, "\n" + "=" * 100)
            logger.log(DETAILED_LEVEL, f"📊 POLYMARKET PRICE SUMMARY (Update #{self.price_update_count})")
            logger.log(DETAILED_LEVEL, "=" * 100)
            
            markets_with_prices = 0
            for market in self.markets:
                token_a = str(market.get('token_a', ''))
                token_b = str(market.get('token_b', ''))
                
                book_a = self.books.get(token_a)
                book_b = self.books.get(token_b)
                
                if book_a and book_b:
                    ask_a, size_a = book_a.get_best_ask()
                    ask_b, size_b = book_b.get_best_ask()
                    
                    if ask_a is not None and ask_b is not None:
                        markets_with_prices += 1
                        total = ask_a + ask_b
                        spread = abs(total - 1.0) * 100
                        
                        market_name = market.get('title', 'Unknown')[:50]
                        label_a = market.get('label_a', 'YES')
                        label_b = market.get('label_b', 'NO')
                        
                        logger.log(DETAILED_LEVEL, f"  {market_name:<50} | {label_a}: ${ask_a:.4f} | {label_b}: ${ask_b:.4f} | Total: ${total:.4f} | Spread: {spread:.2f}%")
            
            logger.log(DETAILED_LEVEL, f"Total markets with prices: {markets_with_prices}/{len(self.markets)}")
            logger.log(DETAILED_LEVEL, "=" * 100 + "\n")
            
        except Exception as e:
            logger.debug(f"Error logging all market prices: {e}")
    
    async def start_monitoring(self):
        """Start WebSocket monitoring"""
        if not self.token_ids:
            logger.warning("❌ No tokens to monitor")
            return
        
        tokens = list(self.token_ids)
        logger.info(f"🔌 Connecting to Polymarket WebSocket for {len(tokens)} tokens...")
        
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            ssl=ssl_context
        )
        
        async with aiohttp.ClientSession(connector=connector) as session:
            while True:
                try:
                    timeout = aiohttp.ClientTimeout(total=30, connect=10)
                    async with session.ws_connect(
                        self.WS_URL,
                        heartbeat=30,
                        timeout=timeout
                    ) as ws:
                        print("✅ Polymarket WebSocket Connected")
                        logger.info("✅ Polymarket WebSocket Connected")
                        
                        # Subscribe to all tokens
                        payload = {
                            "type": "market",
                            "assets_ids": tokens
                        }
                        
                        await ws.send_json(payload)
                        print(f"✅ Subscribed to {len(tokens)} Polymarket tokens")
                        logger.info(f"✅ Subscribed to {len(tokens)} tokens")
                        
                        # Listen for updates
                        message_count = 0
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = msg.json()
                                    
                                    # Log raw message reception in detailed mode
                                    if Config.LOG_LEVEL.upper() == "DETAILED":
                                        message_count += 1
                                        if message_count % 10 == 0:  # Log every 10th message to avoid spam
                                            DETAILED_LEVEL = logging.DEBUG + 1
                                            if logger.isEnabledFor(DETAILED_LEVEL):
                                                logger.log(DETAILED_LEVEL, f"📨 Polymarket WebSocket: Received {message_count} messages so far...")
                                    
                                    # Update health monitor timestamp
                                    health_monitor.update_polymarket_timestamp()
                                    
                                    # Handle both dict and list messages
                                    if isinstance(data, list):
                                        # If message is a list, process each item
                                        for item in data:
                                            if isinstance(item, dict):
                                                await self._handle_message(item)
                                    elif isinstance(data, dict):
                                        await self._handle_message(data)
                                    else:
                                        logger.debug(f"Unexpected message type: {type(data)}")
                                except Exception as e:
                                    logger.error(f"Error handling message: {e}")
                                    logger.error(f"Message data: {msg.data[:200] if hasattr(msg, 'data') else 'N/A'}")
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(f"WebSocket error: {msg.data}")
                                break
                                
                except Exception as e:
                    logger.error(f"WebSocket connection error: {e}, reconnecting in 5s...")
                    await asyncio.sleep(5)
    
    async def _handle_message(self, data):
        """Handle incoming WebSocket message"""
        # Ensure data is a dictionary
        if not isinstance(data, dict):
            logger.debug(f"Received non-dict message: {type(data)}")
            return
        
        # Handle different message types
        msg_type = data.get("type") or data.get("event_type")  # Check both fields
        asset_id_raw = data.get("asset_id")
        
        # Process the message first to update orderbooks
        # Then check if we need to log first data or both tokens initialized
        
        # Handle "book" type messages first (update orderbooks)
        if msg_type == "book" and asset_id_raw:
            asset_id = str(asset_id_raw)
            if asset_id in self.books:
                book = self.books[asset_id]
                book.clear()  # Clear existing book for full refresh
                
                # Process bids
                bids = data.get("bids", [])
                if isinstance(bids, list):
                    for bid in bids:
                        if isinstance(bid, (list, tuple)) and len(bid) >= 2:
                            try:
                                price = float(bid[0])
                                size = float(bid[1])
                                book.update("buy", price, size)
                            except (ValueError, IndexError, TypeError):
                                pass
                
                # Process asks
                asks = data.get("asks", [])
                if isinstance(asks, list):
                    for ask in asks:
                        if isinstance(ask, (list, tuple)) and len(ask) >= 2:
                            try:
                                price = float(ask[0])
                                size = float(ask[1])
                                book.update("sell", price, size)
                            except (ValueError, IndexError, TypeError):
                                pass
        
        # Check for first data for ANY message type that has an asset_id
        # This ensures we log first data even if it's not delta/snapshot
        if asset_id_raw:
            asset_id = str(asset_id_raw)
            # Check if this is the first data for this specific token
            is_first_token_data = asset_id not in self.first_token_data_received
            
            # Check if this token belongs to any market
            for market in self.markets:
                market_id = str(market.get('market_id', market.get('token_a', '')))
                token_a = str(market.get('token_a', ''))
                token_b = str(market.get('token_b', ''))
                
                if asset_id == token_a or asset_id == token_b:
                    market_title = market.get('title', 'Unknown Market')
                    outcome_label = market.get('label_a', 'YES') if asset_id == token_a else market.get('label_b', 'NO')
                    
                    # Extract prices from this message (for logging the current token's bid/ask)
                    bids = data.get("bids", [])
                    asks = data.get("asks", [])
                    best_bid_price = None
                    best_bid_size = 0
                    best_ask_price = None
                    best_ask_size = 0
                    
                    # Extract best bid/ask from message
                    if isinstance(bids, list) and len(bids) > 0:
                        try:
                            best_bid = bids[0]
                            if isinstance(best_bid, (list, tuple)) and len(best_bid) >= 2:
                                best_bid_price = float(best_bid[0])
                                best_bid_size = float(best_bid[1])
                            elif isinstance(best_bid, dict):
                                best_bid_price = float(best_bid.get("price", best_bid.get(0, 0)))
                                best_bid_size = float(best_bid.get("size", best_bid.get(1, 0)))
                        except (ValueError, IndexError, TypeError):
                            pass
                    
                    if isinstance(asks, list) and len(asks) > 0:
                        try:
                            best_ask = asks[0]
                            if isinstance(best_ask, (list, tuple)) and len(best_ask) >= 2:
                                best_ask_price = float(best_ask[0])
                                best_ask_size = float(best_ask[1])
                            elif isinstance(best_ask, dict):
                                best_ask_price = float(best_ask.get("price", best_ask.get(0, 0)))
                                best_ask_size = float(best_ask.get("size", best_ask.get(1, 0)))
                        except (ValueError, IndexError, TypeError):
                            pass
                    
                    # ALWAYS read prices from BOTH orderbooks (after current message has been processed)
                    # The orderbook update happens at the top of _handle_message (lines 336-364)
                    # So by the time we get here, the current message's orderbook is already updated
                    token_a_price = None
                    token_b_price = None
                    book_a = self.books.get(token_a)
                    book_b = self.books.get(token_b)
                    
                    # Read from orderbooks (these should have data from previous messages + current message)
                    if book_a:
                        ask_a, _ = book_a.get_best_ask()
                        if ask_a:
                            token_a_price = ask_a
                    
                    if book_b:
                        ask_b, _ = book_b.get_best_ask()
                        if ask_b:
                            token_b_price = ask_b
                    
                    # If orderbooks don't have prices yet, use prices from this current message
                    # This handles the case where this is the first message for a token
                    if token_a_price is None and asset_id == token_a and best_ask_price:
                        token_a_price = best_ask_price
                    elif token_b_price is None and asset_id == token_b and best_ask_price:
                        token_b_price = best_ask_price
                    
                    # Build price info string - prioritize showing YES/NO prices
                    # This happens for ALL messages, not just first token data
                    price_info_parts = []
                    label_a = market.get('label_a', 'YES')
                    label_b = market.get('label_b', 'NO')
                    
                    # Check if we have prices for both tokens
                    has_both_prices = token_a_price is not None and token_b_price is not None
                    
                    # Always try to show both YES and NO prices first
                    if has_both_prices:
                        total_price = token_a_price + token_b_price
                        spread_pct = abs(total_price - 1.0) * 100
                        price_info_parts.append(f"{label_a}: ${token_a_price:.4f} | {label_b}: ${token_b_price:.4f} | Total: ${total_price:.4f} (spread: {spread_pct:.2f}%)")
                    elif token_a_price is not None:
                        price_info_parts.append(f"{label_a}: ${token_a_price:.4f} | {label_b}: N/A (waiting for {label_b} token data)")
                    elif token_b_price is not None:
                        price_info_parts.append(f"{label_a}: N/A (waiting for {label_a} token data) | {label_b}: ${token_b_price:.4f}")
                    
                    # Add bid/ask for the specific token (with explanation)
                    if best_bid_price is not None or best_ask_price is not None:
                        token_bid_ask = []
                        if best_bid_price is not None:
                            token_bid_ask.append(f"{outcome_label} Bid: ${best_bid_price:.4f} (size: {best_bid_size:.0f})")
                        if best_ask_price is not None:
                            token_bid_ask.append(f"{outcome_label} Ask: ${best_ask_price:.4f} (size: {best_ask_size:.0f})")
                        if token_bid_ask:
                            # Add explanation: Bid = buy price, Ask = sell price, Size = tokens available
                            price_info_parts.append(f"Orderbook: {', '.join(token_bid_ask)}")
                    
                    # Build final price info string
                    if not price_info_parts:
                        price_info = f"No prices available yet"
                    else:
                        price_info = " | ".join(price_info_parts)
                    
                    # Mark this token as having received data
                    if is_first_token_data:
                        self.first_token_data_received.add(asset_id)
                        
                        # Log first WebSocket message for this token at INFO level
                        if has_both_prices:
                            status_note = "✅ Both tokens have prices"
                        else:
                            missing_token = label_b if asset_id == token_a else label_a
                            status_note = f"⏳ Waiting for {missing_token} token data"
                        
                        logger.info(f"📥 First {outcome_label} message for market: {market_title} | "
                                   f"Token ID: {asset_id[:16]}... | "
                                   f"Message type: {msg_type or 'unknown'} | "
                                   f"{status_note} | "
                                   f"{price_info}")
                    else:
                        # Additional messages only shown in DETAILED mode
                        if Config.LOG_LEVEL.upper() == "DETAILED":
                            DETAILED_LEVEL = logging.DEBUG + 1
                            if logger.isEnabledFor(DETAILED_LEVEL):
                                logger.log(DETAILED_LEVEL, f"📥 Additional {outcome_label} message for market: {market_title} | "
                                          f"Token ID: {asset_id[:16]}... | "
                                          f"Message type: {msg_type or 'unknown'} | "
                                          f"{price_info}")
                    
                    # Always check if both tokens are now initialized (for ANY message)
                    # This ensures we log initialization even if second token arrives after first token's second message
                    if has_both_prices and market_id not in self.both_tokens_initialized:
                        self.both_tokens_initialized.add(market_id)
                        total_price = token_a_price + token_b_price
                        spread_pct = abs(total_price - 1.0) * 100
                        logger.info(f"✅ Market fully initialized (both tokens): {market_title} | "
                                   f"{label_a}: ${token_a_price:.4f} | {label_b}: ${token_b_price:.4f} | "
                                   f"Total: ${total_price:.4f} (spread: {spread_pct:.2f}%)")
                    
                    break  # Found the market, no need to continue
        
        # We'll log after processing to show actual prices
        
        # Handle "book" type messages (same as snapshot - full orderbook)
        if msg_type == "book":
            # Treat book messages like snapshots
            asset_id = str(asset_id_raw) if asset_id_raw else ""
            if asset_id in self.books:
                book = self.books[asset_id]
                book.clear()  # Clear existing book for full refresh
                
                # Process bids
                bids = data.get("bids", [])
                if isinstance(bids, list):
                    for bid in bids:
                        if isinstance(bid, (list, tuple)) and len(bid) >= 2:
                            try:
                                price = float(bid[0])
                                size = float(bid[1])
                                book.update("buy", price, size)
                            except (ValueError, IndexError, TypeError):
                                pass
                
                # Process asks
                asks = data.get("asks", [])
                if isinstance(asks, list):
                    for ask in asks:
                        if isinstance(ask, (list, tuple)) and len(ask) >= 2:
                            try:
                                price = float(ask[0])
                                size = float(ask[1])
                                book.update("sell", price, size)
                            except (ValueError, IndexError, TypeError):
                                pass
                
                # Notify callback if we have prices
                if self.price_update_callback:
                    price, size = book.get_best_ask()
                    if price is not None:
                        await self.price_update_callback(asset_id, price, size)
                
                # Check if both tokens are now initialized (after processing book message)
                self._check_and_log_both_tokens_initialized(asset_id)
        
        if msg_type == "delta":
            asset_id = str(asset_id_raw) if asset_id_raw else ""
            
            if asset_id in self.books:
                book = self.books[asset_id]
                
                # Store old prices for logging
                old_best_bid, old_best_bid_size = book.get_best_bid()
                old_best_ask, old_best_ask_size = book.get_best_ask()
                
                # Process bid updates
                bids = data.get("bids", [])
                bids_processed = 0
                if isinstance(bids, list):
                    for bid in bids:
                        if isinstance(bid, (list, tuple)) and len(bid) >= 2:
                            try:
                                price = float(bid[0])
                                size = float(bid[1])
                                book.update("buy", price, size)
                                bids_processed += 1
                            except (ValueError, IndexError) as e:
                                logger.debug(f"Error processing bid: {e}")
                
                # Process ask updates
                asks = data.get("asks", [])
                asks_processed = 0
                if isinstance(asks, list):
                    for ask in asks:
                        if isinstance(ask, (list, tuple)) and len(ask) >= 2:
                            try:
                                price = float(ask[0])
                                size = float(ask[1])
                                book.update("sell", price, size)
                                asks_processed += 1
                            except (ValueError, IndexError) as e:
                                logger.debug(f"Error processing ask: {e}")
                
                # Get new prices after update
                new_best_bid, new_best_bid_size = book.get_best_bid()
                new_best_ask, new_best_ask_size = book.get_best_ask()
                
                # Check if both tokens are now initialized (after processing delta)
                self._check_and_log_both_tokens_initialized(asset_id)
                
                # Detailed logging: Log price updates with actual prices
                if Config.LOG_LEVEL.upper() == "DETAILED":
                    try:
                        DETAILED_LEVEL = logging.DEBUG + 1
                        if logger.isEnabledFor(DETAILED_LEVEL):
                            asset_id_str = str(asset_id)
                            # Find market name for this asset_id
                            market_name = None
                            outcome_label = None
                            for market in self.markets:
                                token_a = str(market.get('token_a', ''))
                                token_b = str(market.get('token_b', ''))
                                if token_a == asset_id_str:
                                    market_name = market.get('title', 'Unknown Market')
                                    outcome_label = market.get('label_a', 'YES')
                                    break
                                elif token_b == asset_id_str:
                                    market_name = market.get('title', 'Unknown Market')
                                    outcome_label = market.get('label_b', 'NO')
                                    break
                            
                            if market_name:
                                # Log with actual prices
                                bid_str = f"${new_best_bid:.4f}" if new_best_bid else "N/A"
                                ask_str = f"${new_best_ask:.4f}" if new_best_ask else "N/A"
                                spread = ((new_best_ask - new_best_bid) / new_best_bid * 100) if (new_best_bid and new_best_ask and new_best_bid > 0) else 0
                                
                                logger.log(DETAILED_LEVEL, f"📥 Polymarket WebSocket: {market_name} ({outcome_label}) | "
                                          f"Bid: {bid_str} (size: {new_best_bid_size:.2f}) | "
                                          f"Ask: {ask_str} (size: {new_best_ask_size:.2f}) | "
                                          f"Spread: {spread:.2f}% | Updates: {bids_processed} bids, {asks_processed} asks")
                            else:
                                # Log even if market not found (might be a token we're not tracking)
                                logger.log(DETAILED_LEVEL, f"📥 Polymarket WebSocket: Asset {asset_id_str} | "
                                          f"Bid: ${new_best_bid:.4f} | Ask: ${new_best_ask:.4f} | "
                                          f"Updates: {bids_processed} bids, {asks_processed} asks")
                    except Exception as e:
                        logger.debug(f"Error in detailed Polymarket logging: {e}")
                
                # Log combined YES/NO prices for the market (if we have both tokens)
                if Config.LOG_LEVEL.upper() == "DETAILED":
                    try:
                        DETAILED_LEVEL = logging.DEBUG + 1
                        if logger.isEnabledFor(DETAILED_LEVEL):
                            self.price_update_count += 1
                            
                            # Find the market this token belongs to
                            for market in self.markets:
                                token_a = str(market.get('token_a', ''))
                                token_b = str(market.get('token_b', ''))
                                
                                if asset_id_str == token_a or asset_id_str == token_b:
                                    market_name = market.get('title', 'Unknown Market')
                                    
                                    # Get prices for both tokens
                                    book_a = self.books.get(token_a)
                                    book_b = self.books.get(token_b)
                                    
                                    if book_a and book_b:
                                        ask_a, size_a = book_a.get_best_ask()
                                        ask_b, size_b = book_b.get_best_ask()
                                        
                                        if ask_a is not None and ask_b is not None:
                                            total = ask_a + ask_b
                                            spread_market = abs(total - 1.0) * 100
                                            
                                            label_a = market.get('label_a', 'YES')
                                            label_b = market.get('label_b', 'NO')
                                            
                                            logger.log(DETAILED_LEVEL, f"💰 Polymarket Price Update: {market_name[:60]} | "
                                                      f"{label_a}: ${ask_a:.4f} (size: {size_a:.0f}) | "
                                                      f"{label_b}: ${ask_b:.4f} (size: {size_b:.0f}) | "
                                                      f"Total: ${total:.4f} | Spread: {spread_market:.2f}%")
                                            
                                            # Log periodic summary every 10 updates
                                            if self.price_update_count % 10 == 0:
                                                self._log_all_market_prices()
                                    break
                    except Exception as e:
                        logger.debug(f"Error in combined price logging: {e}")
                
                # Notify callback of price update
                if self.price_update_callback:
                    price, size = book.get_best_ask()
                    if price is not None:
                        await self.price_update_callback(asset_id, price, size)
        
        elif msg_type == "snapshot":
            # Handle initial snapshot
            asset_id = str(asset_id_raw) if asset_id_raw else ""
            
            if asset_id in self.books:
                book = self.books[asset_id]
                
                # Process snapshot bids
                bids = data.get("bids", [])
                bids_processed = 0
                if isinstance(bids, list):
                    for bid in bids:
                        if isinstance(bid, (list, tuple)) and len(bid) >= 2:
                            try:
                                price = float(bid[0])
                                size = float(bid[1])
                                book.update("buy", price, size)
                                bids_processed += 1
                            except (ValueError, IndexError) as e:
                                logger.debug(f"Error processing snapshot bid: {e}")
                
                # Process snapshot asks
                asks = data.get("asks", [])
                asks_processed = 0
                if isinstance(asks, list):
                    for ask in asks:
                        if isinstance(ask, (list, tuple)) and len(ask) >= 2:
                            try:
                                price = float(ask[0])
                                size = float(ask[1])
                                book.update("sell", price, size)
                                asks_processed += 1
                            except (ValueError, IndexError) as e:
                                logger.debug(f"Error processing snapshot ask: {e}")
                
                # Get prices after snapshot
                best_bid, best_bid_size = book.get_best_bid()
                best_ask, best_ask_size = book.get_best_ask()
                
                # Detailed logging: Log snapshot with actual prices
                if Config.LOG_LEVEL.upper() == "DETAILED":
                    try:
                        DETAILED_LEVEL = logging.DEBUG + 1
                        if logger.isEnabledFor(DETAILED_LEVEL):
                            asset_id_str = str(asset_id)
                            # Find market name for this asset_id
                            market_name = None
                            outcome_label = None
                            for market in self.markets:
                                token_a = str(market.get('token_a', ''))
                                token_b = str(market.get('token_b', ''))
                                if token_a == asset_id_str:
                                    market_name = market.get('title', 'Unknown Market')
                                    outcome_label = market.get('label_a', 'YES')
                                    break
                                elif token_b == asset_id_str:
                                    market_name = market.get('title', 'Unknown Market')
                                    outcome_label = market.get('label_b', 'NO')
                                    break
                            
                            if market_name:
                                bid_str = f"${best_bid:.4f}" if best_bid else "N/A"
                                ask_str = f"${best_ask:.4f}" if best_ask else "N/A"
                                logger.log(DETAILED_LEVEL, f"📊 Polymarket Snapshot: {market_name} ({outcome_label}) | "
                                          f"Bid: {bid_str} (size: {best_bid_size:.2f}) | "
                                          f"Ask: {ask_str} (size: {best_ask_size:.2f}) | "
                                          f"Loaded: {bids_processed} bids, {asks_processed} asks")
                    except Exception as e:
                        logger.debug(f"Error in detailed snapshot logging: {e}")
        
        else:
            # Unknown message type, log for debugging
            logger.debug(f"Unknown message type: {msg_type}, data keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")