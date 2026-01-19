import asyncio
import logging
import csv
import os
from datetime import datetime
from typing import Dict, List
from models import LocalOrderBook
from execution import ExecutionEngine
from config import Config

logger = logging.getLogger("Strategy")

class ArbStrategy:
    def __init__(self, books: Dict[str, LocalOrderBook], market_pairs: List[Dict], executor: ExecutionEngine, 
                 market_removal_callback=None):
        self.books = books
        self.market_pairs = market_pairs
        self.executor = executor
        self.is_executing = False
        self.market_removal_callback = market_removal_callback  # Callback to remove market after arbitrage
        self._executed_markets = set()  # Track markets that have executed arbitrage to prevent duplicates
        self._init_arb_csv()
    
    def _init_arb_csv(self):
        """Initialize CSV file for complete arbitrage trades"""
        if not os.path.exists(Config.ARB_CSV_FILE):
            with open(Config.ARB_CSV_FILE, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp",
                    "Market_Title",
                    "Outcome_A",
                    "Outcome_B",
                    "Price_A",
                    "Price_B",
                    "Total_Cost",
                    "Gross_Profit_Spread_%",
                    "Trade_Size",
                    "Total_Investment_USDC",
                    "Gross_Profit_USDC",
                    "Total_Fees_USDC",
                    "Net_Profit_USDC",
                    "Token_ID_A",
                    "Token_ID_B",
                    "Order_ID_A",
                    "Order_ID_B",
                    "Status"
                ])

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
        # Skip markets that have already executed arbitrage (will be removed)
        market_key = f"{market['token_a']}_{market['token_b']}"
        if market_key in self._executed_markets:
            return
        
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
            profit_spread = 1.0 - total_cost
            logger.info(f"🚨 ARB FOUND: {market['title'][:30]}... [{lbl_a}:{p_a:.4f} + {lbl_b}:{p_b:.4f} = {total_cost:.4f}] (Profit: {profit_spread*100:.2f}%)")
            await self.execute_arb(id_a, id_b, p_a, s_a, p_b, s_b, lbl_a, lbl_b, market['title'], market)

    async def execute_arb(self, id_a, id_b, p_a, s_a, p_b, s_b, lbl_a, lbl_b, market_title: str = "", market: Dict = None):
        self.is_executing = True
        
        # Mark this market as executed to prevent duplicate executions
        if market:
            market_key = f"{market['token_a']}_{market['token_b']}"
            if market_key in self._executed_markets:
                logger.warning(f"⚠️ Market already executed, skipping: {market_title[:50]}...")
                self.is_executing = False
                return
            self._executed_markets.add(market_key)
        
        # Calculate optimal trade size to maximize profit
        total_cost = p_a + p_b
        profit_spread = 1.0 - total_cost
        
        # Constraint 1: Available liquidity (limited by smaller side)
        available_liq = min(s_a, s_b)
        
        # Constraint 2: Maximum trade size in USDC
        max_cap_size = Config.MAX_TRADE_SIZE_USDC / total_cost
        
        # Constraint 3: Minimum viable trade size (to avoid dust)
        min_trade_size = 2.0
        
        # Optimal trade size = minimum of all constraints
        trade_size = min(available_liq, max_cap_size)
        trade_size = max(trade_size, 0)  # Ensure non-negative
        trade_size = round(trade_size, 2)

        if trade_size < min_trade_size: 
            logger.warning(f"⚠️ Trade size too small: {trade_size:.2f} (min: {min_trade_size}, liq: {available_liq:.2f}, max_cap: {max_cap_size:.2f})")
            # Remove from executed set if trade failed
            if market:
                market_key = f"{market['token_a']}_{market['token_b']}"
                self._executed_markets.discard(market_key)
            self.is_executing = False
            return

        # Calculate trade metrics
        total_investment = total_cost * trade_size
        gross_profit = profit_spread * trade_size
        
        # Get market type (per-market if available, otherwise use global config)
        market_type = market.get("market_type", Config.MARKET_TYPE) if market else Config.MARKET_TYPE
        
        # Calculate fees based on market type
        # NOTE: Most Polymarket markets are fee-free. Only US-regulated venue and specific market types have fees.
        # 1. Taker fee (US-regulated venue only): applied to premium (total investment)
        taker_fee_rate = 0.0001 if market_type == "us" else 0.0  # 0.01% for US-regulated venue only
        taker_fee = total_investment * taker_fee_rate
        
        # 2. Gas costs: Polygon network fees (only if not using gasless trading)
        # Gas fees are blockchain network fees, NOT Polymarket platform fees
        # If using Polymarket's Builder/Relayer system, gas may be covered (set USE_GASLESS_TRADING = True)
        gas_cost = Config.TOTAL_GAS_COST if not Config.USE_GASLESS_TRADING else 0.0
        
        # 3. Profit fee: NONE on Polymarket (previously incorrectly assumed 2% for international)
        profit_fee = 0.0  # No profit fees on Polymarket
        
        # Calculate net profit after all fees
        total_fees = taker_fee + gas_cost + profit_fee
        net_profit = gross_profit - total_fees
        net_profit_percentage = (net_profit / total_investment) * 100 if total_investment > 0 else 0
        
        # Check if net profit meets minimum threshold
        net_profit_spread = net_profit / trade_size if trade_size > 0 else 0
        
        if net_profit_spread < Config.MIN_NET_PROFIT_SPREAD:
            logger.warning(f"⚠️ Net profit too low after fees: {net_profit_spread*100:.2f}% (min: {Config.MIN_NET_PROFIT_SPREAD*100:.2f}%)")
            logger.warning(f"   Gross: ${gross_profit:.2f} | Fees: ${total_fees:.2f} (Taker: ${taker_fee:.2f}, Gas: ${gas_cost:.2f}, Profit: ${profit_fee:.2f}) | Net: ${net_profit:.2f}")
            # Remove from executed set if trade doesn't meet net profit threshold
            if market:
                market_key = f"{market['token_a']}_{market['token_b']}"
                self._executed_markets.discard(market_key)
            self.is_executing = False
            return
        
        # Log trade sizing details with fee breakdown
        logger.info(f"💰 Trade Sizing: Size={trade_size:.2f} shares | Investment=${total_investment:.2f}")
        logger.info(f"   Gross Profit: ${gross_profit:.2f} ({profit_spread*100:.2f}%)")
        logger.info(f"   Fees: ${total_fees:.2f} (Taker: ${taker_fee:.2f}, Gas: ${gas_cost:.2f}, Profit Fee: ${profit_fee:.2f})")
        logger.info(f"   Net Profit: ${net_profit:.2f} ({net_profit_percentage:.2f}%)")
        logger.info(f"   Constraints: Liquidity={available_liq:.2f} | Max Cap={max_cap_size:.2f} | Using={trade_size:.2f}")

        # Pass the DYNAMIC labels to the executor
        task_a = self.executor.place_order(id_a, "BUY", p_a, trade_size, lbl_a)
        task_b = self.executor.place_order(id_b, "BUY", p_b, trade_size, lbl_b)
        
        order_ids = await asyncio.gather(task_a, task_b)
        order_id_a = order_ids[0] if order_ids[0] else "FAILED"
        order_id_b = order_ids[1] if order_ids[1] else "FAILED"
        
        # Log complete arbitrage trade to CSV
        self._log_arbitrage_trade(
            market_title=market_title,
            outcome_a=lbl_a,
            outcome_b=lbl_b,
            price_a=p_a,
            price_b=p_b,
            total_cost=total_cost,
            profit_spread=profit_spread,
            trade_size=trade_size,
            total_investment=total_investment,
            expected_profit=net_profit,  # Use net profit instead of gross
            token_id_a=id_a,
            token_id_b=id_b,
            order_id_a=order_id_a,
            order_id_b=order_id_b,
            status="FILLED" if order_id_a != "FAILED" and order_id_b != "FAILED" else "PARTIAL/FAILED",
            gross_profit=gross_profit,
            total_fees=total_fees
        )
        
        # After successful execution, remove market from monitoring and trigger replacement
        if market and self.market_removal_callback:
            logger.info(f"🔄 Removing market from monitoring: {market_title[:50]}... (arbitrage executed)")
            self.market_removal_callback(market)
        
        await asyncio.sleep(0.5) 
        self.is_executing = False
    
    def _log_arbitrage_trade(self, market_title, outcome_a, outcome_b, price_a, price_b, 
                            total_cost, profit_spread, trade_size, total_investment, 
                            expected_profit, token_id_a, token_id_b, order_id_a, order_id_b, status,
                            gross_profit=0, total_fees=0):
        """Log complete arbitrage trade to CSV"""
        try:
            timestamp = datetime.now().isoformat()
            with open(Config.ARB_CSV_FILE, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    market_title[:100] if market_title else "Unknown Market",  # Truncate if too long
                    outcome_a,
                    outcome_b,
                    f"{price_a:.6f}",
                    f"{price_b:.6f}",
                    f"{total_cost:.6f}",
                    f"{profit_spread*100:.4f}%",  # Gross profit spread percentage
                    f"{trade_size:.2f}",
                    f"{total_investment:.4f}",
                    f"{gross_profit:.4f}",  # Gross profit before fees
                    f"{total_fees:.4f}",  # Total fees (taker + gas + profit fee)
                    f"{expected_profit:.4f}",  # Net profit after fees
                    str(token_id_a),
                    str(token_id_b),
                    str(order_id_a),
                    str(order_id_b),
                    status
                ])
            logger.info(f"📝 Arbitrage trade logged to {Config.ARB_CSV_FILE}")
        except Exception as e:
            logger.error(f"Failed to log arbitrage trade to CSV: {e}")