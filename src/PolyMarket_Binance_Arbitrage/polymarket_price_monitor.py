import asyncio
import aiohttp
import logging
import socket
import ssl
import json
from typing import Dict, Optional, Callable
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
        msg_type = data.get("type")
        asset_id = data.get("asset_id")
        
        # We'll log after processing to show actual prices
        
        if msg_type == "delta":
            asset_id = str(data.get("asset_id", ""))
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
            asset_id = str(data.get("asset_id", ""))
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