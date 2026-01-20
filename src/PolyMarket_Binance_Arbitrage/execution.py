import logging
import csv
import os
from datetime import datetime
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL
from config import Config

logger = logging.getLogger("Execution")

class PolymarketExecutor:
    """Executes trades on Polymarket"""
    
    def __init__(self):
        self.client = None
        self.simulation_mode = Config.SIMULATION_MODE
        
        if not self.simulation_mode:
            # Initialize real Polymarket client
            creds = ApiCreds(
                api_key=Config.POLY_API_KEY,
                api_secret=Config.POLY_API_SECRET,
                api_passphrase=Config.POLY_PASSPHRASE,
            )
            self.client = ClobClient(
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                api_passphrase=creds.api_passphrase,
                chain_id=Config.POLY_CHAIN_ID,
                host=Config.POLY_HOST,
            )
            logger.info("✅ Initialized Polymarket client for LIVE trading")
        else:
            logger.warning("⚠️ EXECUTION ENGINE IN SIMULATION MODE ⚠️")
            self._init_csv()
    
    def _init_csv(self):
        """Initialize CSV files for simulation logging"""
        # Main CSV file
        csv_file = Config.SIM_CSV_FILE
        if not os.path.exists(csv_file):
            with open(csv_file, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "Crypto_Name", "Market_Title", "Token_A", "Token_B", 
                    "Outcome_A", "Outcome_B", "Side", "Price", "Size", 
                    "Status", "Binance_Price", "Pump_Pct", "Side_Description", "Order_Type", "Strategy"
                ])
        
        # Separate CSV files for strategy comparison (if testing both)
        if Config.SIMULATION_TEST_BOTH_STRATEGIES:
            limit_csv = csv_file.replace('.csv', '_LIMIT.csv')
            market_csv = csv_file.replace('.csv', '_MARKET.csv')
            
            for strategy_file, strategy_name in [(limit_csv, "LIMIT"), (market_csv, "MARKET")]:
                if not os.path.exists(strategy_file):
                    with open(strategy_file, mode='w', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            "Timestamp", "Crypto_Name", "Market_Title", "Token_A", "Token_B", 
                            "Outcome_A", "Outcome_B", "Side", "Price", "Size", 
                            "Status", "Binance_Price", "Pump_Pct", "Side_Description", "Order_Type"
                        ])
    
    async def execute_arbitrage_trade(self, market: dict, binance_price: float, pump_pct: float, 
                                     crypto_name: str = "Unknown", token_id: str = None, 
                                     label: str = None, side_desc: str = None, limit_price: float = None,
                                     market_price: float = None, order_type: str = None):
        """
        Execute arbitrage trade on Polymarket market after Binance move
        
        Strategy: Buy the outcome that benefits from the price move direction
        
        Args:
            market: Polymarket market dictionary
            binance_price: Current Binance price
            pump_pct: Percentage move detected (can be positive or negative)
            crypto_name: Name of the cryptocurrency that moved
            token_id: Token ID to buy (determined by strategy)
            label: Outcome label (YES/NO)
            side_desc: Description of why this outcome was chosen
            limit_price: Maximum price to pay (limit order price). Used for LIMIT orders.
            market_price: Current best ask price. Used for MARKET orders.
            order_type: "LIMIT" or "MARKET". If None, uses Config.ORDER_TYPE
        """
        try:
            token_a = market['token_a']
            token_b = market['token_b']
            label_a = market['label_a']
            label_b = market['label_b']
            title = market['title']
            
            # Use provided token_id and label, or default to token_a/YES
            if token_id is None:
                token_id = token_a
                label = label_a
                side_desc = "YES (default)"
            
            # Determine order type
            if order_type is None:
                order_type = Config.ORDER_TYPE.upper()
            
            # Get price based on order type
            if order_type == "MARKET":
                # Market order: use current best ask price
                if market_price is not None:
                    price = market_price
                elif token_id == token_a:
                    price = market.get('price_a', 0)
                else:
                    price = market.get('price_b', 0)
            else:
                # Limit order: use limit_price (max_bid)
                if limit_price is not None:
                    price = limit_price
                elif token_id == token_a:
                    price = market.get('price_a', 0)
                else:
                    price = market.get('price_b', 0)
            
            if price <= 0:
                logger.error(f"Invalid price for trade: {price}")
                return None
            
            # Calculate trade size
            trade_size = min(
                Config.MAX_TRADE_SIZE_USDC / price,
                market.get('liquidity', 0) / 10  # Use 10% of available liquidity
            )
            
            trade_size = max(trade_size, 1.0)  # Minimum trade size
            trade_size = round(trade_size, 2)
            
            if self.simulation_mode:
                return await self._simulate_trade(
                    market, token_id, label, price, trade_size, 
                    binance_price, pump_pct, crypto_name, side_desc, order_type
                )
            else:
                return await self._real_trade(
                    token_id, label, price, trade_size, order_type
                )
                
        except Exception as e:
            logger.error(f"Error executing arbitrage trade: {e}")
            return None
    
    async def _simulate_trade(self, market: dict, token_id: str, outcome_label: str, 
                             price: float, size: float, binance_price: float, pump_pct: float, 
                             crypto_name: str = "Unknown", side_desc: str = None, order_type: str = "LIMIT"):
        """Simulate trade execution"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        direction_emoji = "📈" if pump_pct > 0 else "📉"
        order_emoji = "🎯" if order_type == "LIMIT" else "⚡"
        logger.info(f"📊 SIMULATED TRADE ({order_type}):")
        logger.info(f"   Crypto: {crypto_name}")
        logger.info(f"   Market: {market['title'][:60]}...")
        logger.info(f"   Outcome: {outcome_label} ({side_desc or 'N/A'})")
        logger.info(f"   Order Type: {order_type} {order_emoji}")
        logger.info(f"   Price: {price:.4f}")
        logger.info(f"   Size: {size:.2f}")
        logger.info(f"   Binance Price: ${binance_price:,.2f}")
        logger.info(f"   Move: {pump_pct:+.2f}% {direction_emoji}")
        
        # Log to main CSV
        csv_file = Config.SIM_CSV_FILE
        with open(csv_file, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp,
                crypto_name,
                market['title'],
                market['token_a'],
                market['token_b'],
                market['label_a'],
                market['label_b'],
                outcome_label,
                price,
                size,
                "SIMULATED",
                binance_price,
                pump_pct,
                side_desc or "N/A",
                order_type,
                order_type  # Strategy column (same as order_type for now)
            ])
        
        # Log to strategy-specific CSV if testing both strategies
        if Config.SIMULATION_TEST_BOTH_STRATEGIES:
            strategy_csv = csv_file.replace('.csv', f'_{order_type}.csv')
            with open(strategy_csv, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    crypto_name,
                    market['title'],
                    market['token_a'],
                    market['token_b'],
                    market['label_a'],
                    market['label_b'],
                    outcome_label,
                    price,
                    size,
                    "SIMULATED",
                    binance_price,
                    pump_pct,
                    side_desc or "N/A",
                    order_type
                ])
        
        return {
            "success": True,
            "order_id": f"SIM_{order_type}_{datetime.now().timestamp()}",
            "status": "SIMULATED",
            "order_type": order_type,
            "price": price
        }
    
    async def _real_trade(self, token_id: str, outcome_label: str, price: float, size: float, order_type: str = "LIMIT"):
        """Execute real trade on Polymarket"""
        try:
            # Note: Polymarket CLOB requires a price even for "market" orders
            # For market orders, we use the current best ask price
            # The difference is: LIMIT uses max_bid, MARKET uses current ask
            order_args = OrderArgs(
                price=price,
                size=size,
                side=BUY,
                token_id=token_id,
            )
            
            order_type_emoji = "🎯" if order_type == "LIMIT" else "⚡"
            logger.info(f"📤 Placing {order_type} order: {outcome_label} | Price: {price:.4f} | Size: {size:.2f} {order_type_emoji}")
            
            resp = self.client.create_and_post_order(order_args)
            
            if resp and resp.get("success"):
                order_id = resp.get("orderID", "UNKNOWN")
                logger.info(f"✅ {order_type} ORDER PLACED: {outcome_label} | Price: {price:.4f} | Size: {size:.2f} | ID: {order_id}")
                return {
                    "success": True,
                    "order_id": order_id,
                    "status": "FILLED",
                    "order_type": order_type
                }
            else:
                logger.error(f"❌ {order_type} ORDER FAILED: {resp}")
                return {
                    "success": False,
                    "order_id": None,
                    "status": "FAILED",
                    "order_type": order_type
                }
        except Exception as e:
            logger.error(f"❌ Error placing {order_type} order: {e}")
            return {
                "success": False,
                "order_id": None,
                "status": "ERROR",
                "order_type": order_type
            }
