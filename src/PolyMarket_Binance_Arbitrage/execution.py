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
        """Initialize CSV file for simulation logging"""
        csv_file = Config.SIM_CSV_FILE
        if not os.path.exists(csv_file):
            with open(csv_file, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "Crypto_Name", "Market_Title", "Token_A", "Token_B", 
                    "Outcome_A", "Outcome_B", "Side", "Price", "Size", 
                    "Status", "Binance_Price", "Pump_Pct", "Side_Description"
                ])
    
    async def execute_arbitrage_trade(self, market: dict, binance_price: float, pump_pct: float, 
                                     crypto_name: str = "Unknown", token_id: str = None, 
                                     label: str = None, side_desc: str = None):
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
            
            # Get price for the chosen token
            if token_id == token_a:
                price = market['price_a']
            else:
                price = market['price_b']
            
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
                    binance_price, pump_pct, crypto_name, side_desc
                )
            else:
                return await self._real_trade(
                    token_id, label, price, trade_size
                )
                
        except Exception as e:
            logger.error(f"Error executing arbitrage trade: {e}")
            return None
    
    async def _simulate_trade(self, market: dict, token_id: str, outcome_label: str, 
                             price: float, size: float, binance_price: float, pump_pct: float, 
                             crypto_name: str = "Unknown", side_desc: str = None):
        """Simulate trade execution"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        direction_emoji = "📈" if pump_pct > 0 else "📉"
        logger.info(f"📊 SIMULATED TRADE:")
        logger.info(f"   Crypto: {crypto_name}")
        logger.info(f"   Market: {market['title'][:60]}...")
        logger.info(f"   Outcome: {outcome_label} ({side_desc or 'N/A'})")
        logger.info(f"   Price: {price:.4f}")
        logger.info(f"   Size: {size:.2f}")
        logger.info(f"   Binance Price: ${binance_price:,.2f}")
        logger.info(f"   Move: {pump_pct:+.2f}% {direction_emoji}")
        
        # Log to CSV
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
                side_desc or "N/A"
            ])
        
        return {
            "success": True,
            "order_id": f"SIM_{datetime.now().timestamp()}",
            "status": "SIMULATED"
        }
    
    async def _real_trade(self, token_id: str, outcome_label: str, price: float, size: float):
        """Execute real trade on Polymarket"""
        try:
            order_args = OrderArgs(
                price=price,
                size=size,
                side=BUY,
                token_id=token_id,
            )
            
            resp = self.client.create_and_post_order(order_args)
            
            if resp and resp.get("success"):
                order_id = resp.get("orderID", "UNKNOWN")
                logger.info(f"✅ ORDER PLACED: {outcome_label} | Price: {price:.4f} | Size: {size:.2f} | ID: {order_id}")
                return {
                    "success": True,
                    "order_id": order_id,
                    "status": "FILLED"
                }
            else:
                logger.error(f"❌ ORDER FAILED: {resp}")
                return {
                    "success": False,
                    "order_id": None,
                    "status": "FAILED"
                }
        except Exception as e:
            logger.error(f"❌ Error placing real order: {e}")
            return {
                "success": False,
                "order_id": None,
                "status": "ERROR"
            }
