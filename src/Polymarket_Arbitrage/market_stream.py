import asyncio
import json
import logging
import aiohttp
import socket # Needed to force IPv4
from typing import Dict, Callable, Optional
from models import LocalOrderBook

logger = logging.getLogger("MarketStream")

class MarketStream:
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self, client, books: Dict[str, LocalOrderBook], update_callback: Optional[Callable] = None):
        self.client = client
        self.books = books 
        self.tokens_to_sub = []
        self.update_callback = update_callback  # Callback to trigger table refresh
        self.last_update_time = 0
        self.update_throttle = 0.5  # Minimum seconds between updates 

    async def start(self):
        if not self.tokens_to_sub:
            logger.warning("❌ No tokens to subscribe to.")
            return

        tokens = [str(t).strip() for t in self.tokens_to_sub]
        
        logger.info(f"🔌 Connecting... (Forcing IPv4 + No SSL Verify) Queue: {len(tokens)}")

        # 1. NETWORK TWEAK: Force IPv4 and proper SSL handling
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,  # Force IPv4
            ssl=ssl_context
        )

        async with aiohttp.ClientSession(connector=connector) as session:
            while True:
                try:
                    # 2. Connect with proper timeout and heartbeat
                    timeout = aiohttp.ClientTimeout(total=30, connect=10)
                    async with session.ws_connect(
                        self.WS_URL, 
                        heartbeat=30,
                        timeout=timeout
                    ) as ws:
                        logger.info("✅ WebSocket Connected.")

                        # 3. Send subscription payload with CORRECT format
                        # Polymarket expects "assets_ids" not "assets"
                        payload = {
                            "type": "market",
                            "assets_ids": tokens  # Key fix: use "assets_ids" not "assets"
                        }
                        
                        logger.info(f"📡 Sending subscription for {len(tokens)} tokens: {tokens[:3]}...")
                        
                        try:
                            await asyncio.wait_for(ws.send_json(payload), timeout=5.0)
                            logger.info(f"✅ Subscription sent! Waiting for data...")
                        except asyncio.TimeoutError:
                            logger.error("⚠️ Send Timed Out. Retrying...")
                            continue

                        # 4. Listen Loop with timeout protection
                        message_count = 0
                        last_message_time = asyncio.get_event_loop().time()
                        
                        try:
                            async for msg in ws:
                                current_time = asyncio.get_event_loop().time()
                                
                                # Check for timeout (no messages for 60 seconds)
                                if current_time - last_message_time > 60:
                                    logger.warning("⚠️ No messages received for 60s. Reconnecting...")
                                    break
                                
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    raw = msg.data
                                    if not raw: 
                                        continue
                                    
                                    last_message_time = current_time
                                    message_count += 1
                                    
                                    # Log first few messages for debugging
                                    if message_count <= 3:
                                        logger.info(f"📥 Message #{message_count}: {raw[:200]}...")
                                    
                                    try:
                                        data = json.loads(raw)
                                        
                                        # Handle different message formats
                                        if isinstance(data, list):
                                            for item in data: 
                                                self._process_update(item)
                                        elif isinstance(data, dict):
                                            # Check if it's a book update or other message type
                                            if "bids" in data or "asks" in data:
                                                self._process_update(data)
                                            elif "event_type" in data:
                                                logger.debug(f"Event: {data.get('event_type')}")
                                        else:
                                            self._process_update(data)
                                    except json.JSONDecodeError as e:
                                        logger.warning(f"Failed to parse JSON: {raw[:100]}... Error: {e}")
                                    except Exception as e:
                                        logger.warning(f"Error processing message: {e}")

                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    logger.error(f"⚠️ WebSocket Error: {msg.data}")
                                    break
                                elif msg.type == aiohttp.WSMsgType.CLOSED:
                                    logger.warning("⚠️ WebSocket Closed by server.")
                                    break
                                elif msg.type == aiohttp.WSMsgType.PING:
                                    await ws.pong()
                                elif msg.type == aiohttp.WSMsgType.PONG:
                                    pass  # Heartbeat response
                                    
                        except asyncio.TimeoutError:
                            logger.error("⚠️ Receive timeout. Reconnecting...")
                        except Exception as e:
                            logger.error(f"⚠️ Error in message loop: {e}")

                except Exception as e:
                    logger.error(f"Connection Error: {e}. Retry in 5s...")
                    await asyncio.sleep(5)

    def _process_update(self, data):
        """Process order book update from WebSocket"""
        if not isinstance(data, dict):
            return
            
        # Polymarket can send updates in different formats
        # Try multiple possible field names for token ID
        token_id = (
            data.get("asset_id") or 
            data.get("token_id") or 
            data.get("asset") or
            data.get("id")
        )
        
        if not token_id:
            # Sometimes the token ID is in a nested structure
            if "asset" in data and isinstance(data["asset"], dict):
                token_id = data["asset"].get("id") or data["asset"].get("token_id")
        
        if not token_id:
            return
        
        # Convert to string for consistent lookup
        token_id_str = str(token_id)
        
        # Find the book - try multiple formats
        book = self.books.get(token_id_str)
        if not book and token_id_str.isdigit():
            book = self.books.get(int(token_id_str))
        if not book:
            book = self.books.get(token_id)
        
        if not book:
            # Token not in our subscription list, skip
            return
        
        # Process bids
        if "bids" in data and data["bids"]:
            for x in data["bids"]: 
                p, s = self._p(x)
                if p is not None and s is not None:
                    book.update("buy", p, s)
        
        # Process asks
        if "asks" in data and data["asks"]:
            for x in data["asks"]: 
                p, s = self._p(x)
                if p is not None and s is not None:
                    book.update("sell", p, s)
        
        # Trigger table update callback if provided (throttled)
        if self.update_callback:
            import time
            current_time = time.time()
            if current_time - self.last_update_time >= self.update_throttle:
                try:
                    self.update_callback()
                    self.last_update_time = current_time
                except Exception as e:
                    logger.warning(f"Update callback error: {e}")

    def _p(self, item):
        """Parse price and size from order book entry"""
        try:
            # Try dict format first
            if isinstance(item, dict):
                price = float(item.get("price", 0))
                size = float(item.get("size", 0))
                return price, size
            # Try list/tuple format [price, size]
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                return float(item[0]), float(item[1])
        except (ValueError, TypeError, IndexError):
            pass
        return None, None