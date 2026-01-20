import aiohttp
import logging
import asyncio
import json
import socket
import ssl
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable
from collections import deque
from config import Config
from websocket_health import health_monitor

logger = logging.getLogger("BinanceFeed")

class BinancePriceFeed:
    """Monitors Binance price movements via WebSocket and detects rapid moves"""
    
    WS_BASE_URL = "wss://stream.binance.com:9443/ws"
    
    def __init__(self, symbol: str = Config.BINANCE_SYMBOL):
        self.symbol = symbol
        # Convert symbol format: BTC/USDT -> btcusdt
        self.stream_symbol = symbol.replace('/', '').lower()
        
        # Price history for delta detection
        # Store (timestamp, price) tuples
        self.price_history: deque = deque(maxlen=120)  # Keep last 2 minutes of data
        
        # Current price
        self.current_price: Optional[float] = None
        self.last_update_time: Optional[datetime] = None
        
        # Move detection callback
        self.pump_callback: Optional[Callable] = None
        
    def set_pump_callback(self, callback: Callable):
        """Set callback function to be called when delta move is detected"""
        self.pump_callback = callback
    
    def _update_price(self, price: float):
        """Update price and add to history"""
        if price and price > 0:
            self.current_price = price
            self.last_update_time = datetime.now()
            
            # Add to history
            self.price_history.append((datetime.now(), price))
            
            return price
        return None
    
    def calculate_price_change(self, start_time: datetime, end_time: datetime) -> Optional[float]:
        """Calculate price change percentage between two timestamps"""
        if len(self.price_history) < 2:
            return None
        
        # Find prices closest to the timestamps
        start_price = None
        end_price = None
        
        for timestamp, price in self.price_history:
            if start_price is None or abs((timestamp - start_time).total_seconds()) < abs((self.price_history[0][0] - start_time).total_seconds()):
                start_price = price
            
            if end_price is None or abs((timestamp - end_time).total_seconds()) < abs((self.price_history[-1][0] - end_time).total_seconds()):
                end_price = price
        
        if start_price and end_price and start_price > 0:
            return ((end_price - start_price) / start_price) * 100
        
        return None
    
    def detect_delta_move(self) -> Optional[Dict]:
        """
        Detect if price has moved more than delta threshold in the detection window
        Returns dict with move details if detected, None otherwise
        """
        if len(self.price_history) < 2:
            return None
        
        now = datetime.now()
        window_start = now - timedelta(seconds=Config.DELTA_DETECTION_WINDOW)
        
        # Get price at start of window and current price (with timestamps)
        start_price = None
        start_price_timestamp = None
        current_price = self.current_price
        current_price_timestamp = now  # Current price timestamp is "now"
        
        # Find price closest to window start
        for timestamp, price in self.price_history:
            if timestamp >= window_start:
                if start_price is None:
                    start_price = price
                    start_price_timestamp = timestamp
                elif timestamp < self.price_history[0][0]:
                    start_price = price
                    start_price_timestamp = timestamp
                break
        
        # If no price in window, use oldest price
        if start_price is None and len(self.price_history) > 0:
            start_price = self.price_history[0][1]
            start_price_timestamp = self.price_history[0][0]
        
        if start_price and current_price and start_price > 0:
            price_change_pct = ((current_price - start_price) / start_price) * 100
            
            # Get crypto name from symbol (e.g., "BTC/USDT" -> "Bitcoin")
            crypto_name = self._get_crypto_name(self.symbol)
            
            # Log every check only if LOG_LEVEL is set to MOVEMENT
            if Config.LOG_LEVEL.upper() == "MOVEMENT":
                direction_emoji = "📈" if price_change_pct > 0 else "📉" if price_change_pct < 0 else "➖"
                start_time_str = start_price_timestamp.strftime('%H:%M:%S.%f')[:-3] if start_price_timestamp else "N/A"
                current_time_str = current_price_timestamp.strftime('%H:%M:%S.%f')[:-3] if current_price_timestamp else "N/A"
                
                MOVEMENT_LEVEL = logging.DEBUG + 2
                if logger.isEnabledFor(MOVEMENT_LEVEL):
                    logger.log(MOVEMENT_LEVEL, f"Potential Lag - Step 1) Checking movement: {crypto_name} ({self.symbol}) | "
                              f"Start price: ${start_price:.2f} @ {start_time_str} | "
                              f"Current price: ${current_price:.2f} @ {current_time_str} | "
                              f"Movement: {price_change_pct:+.2f}% {direction_emoji}")
            
            # Check if move exceeds threshold (positive or negative)
            if abs(price_change_pct) >= Config.DELTA_THRESHOLD_PERCENT:
                move_info = {
                    'symbol': self.symbol,
                    'start_price': start_price,
                    'current_price': current_price,
                    'price_change_pct': price_change_pct,
                    'direction': 'up' if price_change_pct > 0 else 'down',
                    'detection_time': now,
                    'window_start': window_start
                }
                
                logger.info(f"Potential Lag - Step 1) ✅ Threshold exceeded: {crypto_name} ({self.symbol}) moved {price_change_pct:+.2f}% "
                          f"(${start_price:.2f} -> ${current_price:.2f}) within {Config.DELTA_DETECTION_WINDOW} seconds")
                
                return move_info
        
        return None
    
    def _get_crypto_name(self, symbol: str) -> str:
        """Get cryptocurrency name from symbol"""
        # Map common symbols to names
        symbol_to_name = {
            'BTC/USDT': 'Bitcoin',
            'ETH/USDT': 'Ethereum',
            'SOL/USDT': 'Solana',
            'BNB/USDT': 'BNB',
            'XRP/USDT': 'XRP',
            'ADA/USDT': 'Cardano',
            'DOGE/USDT': 'Dogecoin',
            'DOT/USDT': 'Polkadot',
            'MATIC/USDT': 'Polygon',
            'AVAX/USDT': 'Avalanche'
        }
        
        # Check if we have a direct mapping
        if symbol in symbol_to_name:
            return symbol_to_name[symbol]
        
        # Try to find in TOP_CRYPTOS config
        for crypto in Config.TOP_CRYPTOS:
            if crypto.get('symbol') == symbol:
                return crypto.get('name', symbol.split('/')[0])
        
        # Fallback: use the base symbol (e.g., "BTC" from "BTC/USDT")
        return symbol.split('/')[0]
    
    def detect_pump(self) -> Optional[Dict]:
        """Legacy method - redirects to detect_delta_move"""
        return self.detect_delta_move()
    
    async def start_monitoring(self):
        """Start WebSocket monitoring for real-time price updates"""
        ws_url = f"{self.WS_BASE_URL}/{self.stream_symbol}@ticker"
        logger.info(f"🔌 Connecting to Binance WebSocket: {self.symbol} ({ws_url})")
        
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
                        ws_url,
                        heartbeat=30,
                        timeout=timeout
                    ) as ws:
                        print(f"✅ Binance WebSocket Connected for {self.symbol}")
                        logger.info(f"✅ Binance WebSocket Connected for {self.symbol}")
                        
                        # Listen for ticker updates
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                    
                                    # Detailed logging: Log all raw messages
                                    if Config.LOG_LEVEL.upper() == "DETAILED":
                                        try:
                                            DETAILED_LEVEL = logging.DEBUG + 1
                                            if logger.isEnabledFor(DETAILED_LEVEL):
                                                event_type = data.get('e', 'Unknown')
                                                symbol = data.get('s', 'Unknown')
                                                logger.log(DETAILED_LEVEL, f"📨 Binance Raw Message: {symbol} | Event: {event_type} | "
                                                          f"Keys: {list(data.keys())[:10]}")
                                        except Exception:
                                            pass
                                    
                                    # Update health monitor timestamp
                                    health_monitor.update_binance_timestamp()
                                    
                                    await self._handle_ticker_update(data)
                                except json.JSONDecodeError as e:
                                    logger.error(f"Error parsing Binance message: {e}")
                                    if Config.LOG_LEVEL.upper() == "DETAILED":
                                        logger.debug(f"Raw message data: {msg.data[:200] if hasattr(msg, 'data') else 'N/A'}")
                                except Exception as e:
                                    logger.error(f"Error handling Binance message: {e}")
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(f"Binance WebSocket error: {msg.data}")
                                break
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                logger.warning("Binance WebSocket closed")
                                break
                                
                except Exception as e:
                    logger.error(f"Binance WebSocket connection error: {e}, reconnecting in 5s...")
                    await asyncio.sleep(5)
    
    async def _handle_ticker_update(self, data: dict):
        """Handle incoming ticker update from Binance WebSocket"""
        try:
            # Detailed logging: Log every WebSocket message first
            if Config.LOG_LEVEL.upper() == "DETAILED":
                try:
                    DETAILED_LEVEL = logging.DEBUG + 1
                    if logger.isEnabledFor(DETAILED_LEVEL):
                        event_type = data.get('e', 'Unknown')
                        symbol = data.get('s', 'Unknown')
                        price = data.get('c', 0)  # Last price
                        volume = data.get('v', 0)
                        price_change = data.get('P', 0)
                        high_24h = data.get('h', 0)
                        low_24h = data.get('l', 0)
                        
                        logger.log(DETAILED_LEVEL, f"📥 Binance WebSocket: {symbol} | "
                                  f"Event: {event_type} | Price: ${float(price):.2f} | "
                                  f"24h High: ${float(high_24h):.2f} | 24h Low: ${float(low_24h):.2f} | "
                                  f"Change: {float(price_change):.2f}% | Volume: {float(volume):.2f}")
                except Exception as e:
                    logger.debug(f"Error in detailed Binance logging: {e}")
            
            # Binance ticker format: {"e":"24hrTicker","E":123456789,"s":"BTCUSDT","c":"50000.00",...}
            if data.get('e') == '24hrTicker':
                price = float(data.get('c', 0))  # 'c' is the last price
                
                if price > 0:
                    old_price = self.current_price
                    self._update_price(price)
                    
                    # Log price change if we had a previous price
                    if Config.LOG_LEVEL.upper() == "DETAILED" and old_price:
                        try:
                            DETAILED_LEVEL = logging.DEBUG + 1
                            if logger.isEnabledFor(DETAILED_LEVEL):
                                price_change = ((price - old_price) / old_price) * 100
                                logger.log(DETAILED_LEVEL, f"💰 Binance Price Update: {self.symbol} | "
                                          f"${old_price:.2f} → ${price:.2f} | Change: {price_change:+.4f}%")
                        except Exception:
                            pass
                    
                    # Check for delta move
                    move_info = self.detect_delta_move()
                    
                    if move_info and self.pump_callback:
                        # Call callback with move information
                        await self.pump_callback(move_info)
        except Exception as e:
            logger.error(f"Error processing ticker update: {e}")
