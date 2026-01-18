import asyncio
import logging
from typing import Dict, List
from models import LocalOrderBook
from execution import ExecutionEngine
from config import Config

logger = logging.getLogger("Strategy")

class ArbStrategy:
    def __init__(self, books: Dict[str, LocalOrderBook], market_pairs: List[Dict], executor: ExecutionEngine):
        self.books = books
        self.market_pairs = market_pairs
        self.executor = executor
        self.is_executing = False

    async def run_loop(self):
        logger.info("🧠 Global Strategy Engine Active")
        # Optimize scan interval based on number of markets
        # More markets = slightly longer sleep to reduce CPU load
        # But still fast enough to catch arbitrage opportunities
        scan_interval = 0.01 if len(self.market_pairs) < 50 else 0.02
        
        while True:
            if not self.is_executing:
                # Scan all markets (this is very fast - just dict lookups)
                for market in self.market_pairs:
                    await self.scan_market(market)
            await asyncio.sleep(scan_interval)

    async def scan_market(self, market: Dict):
        # 1. Extract IDs and Labels dynamically
        id_a = market['token_a']
        id_b = market['token_b']
        lbl_a = market['label_a'] # "Up", "Yes", "Biden"
        lbl_b = market['label_b'] # "Down", "No", "Trump"

        if id_a not in self.books or id_b not in self.books:
            return

        book_a = self.books[id_a]
        book_b = self.books[id_b]

        p_a, s_a = book_a.get_best_ask()
        p_b, s_b = book_b.get_best_ask()

        if not p_a or not p_b:
            return

        total_cost = p_a + p_b
        threshold = 1.0 - Config.MIN_PROFIT_SPREAD

        if total_cost < threshold:
            logger.info(f"🚨 ARB FOUND: {market['title'][:30]}... [{lbl_a}:{p_a:.2f} + {lbl_b}:{p_b:.2f} = {total_cost:.3f}]")
            await self.execute_arb(id_a, id_b, p_a, s_a, p_b, s_b, lbl_a, lbl_b)

    async def execute_arb(self, id_a, id_b, p_a, s_a, p_b, s_b, lbl_a, lbl_b):
        self.is_executing = True
        
        available_liq = min(s_a, s_b)
        max_cap_size = Config.MAX_TRADE_SIZE_USDC / (p_a + p_b)
        trade_size = min(available_liq, max_cap_size)
        trade_size = round(trade_size, 2)

        if trade_size < 2: 
            self.is_executing = False
            return

        # Pass the DYNAMIC labels to the executor
        task_a = self.executor.place_order(id_a, "BUY", p_a, trade_size, lbl_a)
        task_b = self.executor.place_order(id_b, "BUY", p_b, trade_size, lbl_b)
        
        await asyncio.gather(task_a, task_b)
        
        await asyncio.sleep(0.5) 
        self.is_executing = False