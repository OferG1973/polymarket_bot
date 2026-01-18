import asyncio
import json
import logging
import aiohttp
from typing import Dict, List
from config import Config
from models import LocalOrderBook

logger = logging.getLogger("MarketStream")

class MarketStream:
    # Polymarket CLOB WebSocket Endpoint
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self, client, books: Dict[str, LocalOrderBook]):
        self.client = client # We keep this for reference, but we won't use its WS method
        self.books = books 
        self.tokens_to_sub = [] 

    async def start(self):
        """
        Manages the WebSocket connection directly using aiohttp.
        """
        if not self.tokens_to_sub:
            logger.warning("No tokens to subscribe to. Streamer is idle.")
            return

        logger.info(f"🔌 Connecting to WebSocket Feed for {len(self.tokens_to_sub)} tokens...")

        async with aiohttp.ClientSession() as session:
            while True: # Reconnection Loop
                try:
                    async with session.ws_connect(self.WS_URL) as ws:
                        logger.info("✅ WebSocket Connected.")
                        
                        # 1. Send Subscription Payload
                        payload = {
                            "assets": self.tokens_to_sub,
                            "type": "market"
                        }
                        await ws.send_json(payload)
                        logger.info("📡 Subscription Sent.")

                        # 2. Listen for Messages
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                
                                # Handle lists (snapshots) or dicts (deltas)
                                if isinstance(data, list):
                                    for item in data:
                                        self._process_update(item)
                                else:
                                    self._process_update(data)
                                    
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(f"WebSocket Error: {msg.data}")
                                break
                                
                except Exception as e:
                    logger.error(f"WebSocket Connection Lost: {e}. Reconnecting in 5s...")
                    await asyncio.sleep(5)

    def _process_update(self, data):
        """
        Normalizes the data and updates the correct LocalOrderBook.
        """
        try:
            # 1. Filter out non-book messages
            event_type = data.get("event_type")
            if event_type and event_type != "book":
                # We can handle 'price_change' or 'last_trade' here if we wanted
                return

            # 2. Extract Token ID
            token_id = data.get("asset_id") or data.get("token_id")
            
            if not token_id or token_id not in self.books:
                return

            book = self.books[token_id]

            # 3. Update Bids
            if "bids" in data:
                for item in data["bids"]:
                    # Item format might be {"price": "0.5", "size": "100"} or ["0.5", "100"]
                    price, size = self._parse_level(item)
                    if price is not None:
                        book.update("buy", price, size)
            
            # 4. Update Asks
            if "asks" in data:
                for item in data["asks"]:
                    price, size = self._parse_level(item)
                    if price is not None:
                        book.update("sell", price, size)

        except Exception as e:
            # logger.debug(f"Stream Parse Error: {e}") # Debug only to avoid spam
            pass

    def _parse_level(self, item):
        """Helper to parse price/size from various formats"""
        try:
            if isinstance(item, dict):
                return float(item.get("price", 0)), float(item.get("size", 0))
            elif isinstance(item, list) or isinstance(item, tuple):
                return float(item[0]), float(item[1])
        except:
            pass
        return None, None