import logging
import csv
import os
import uuid
from datetime import datetime
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL
from config import Config

logger = logging.getLogger("Execution")

class ExecutionEngine:
    def __init__(self, client: ClobClient):
        self.client = client
        if Config.SIMULATION_MODE:
            logger.warning("⚠️ EXECUTION ENGINE IN SIMULATION MODE ⚠️")
            self._init_csv()

    def _init_csv(self):
        if not os.path.exists(Config.SIM_CSV_FILE):
            with open(Config.SIM_CSV_FILE, mode='w', newline='') as f:
                writer = csv.writer(f)
                # Added 'Outcome' column for better CSV tracking too
                writer.writerow(["Timestamp", "Token_ID", "Outcome", "Side", "Price", "Size", "Type", "Status"])

    # CHANGED: Added outcome_label parameter (default empty for backward compat)
    async def place_order(self, token_id: str, side: str, price: float, size: float, outcome_label: str = ""):
        """
        Submits an order. 
        Accepts outcome_label ("YES"/"NO") purely for logging purposes.
        """
        try:
            # 1. SIMULATION LOGIC
            if Config.SIMULATION_MODE:
                return self._simulate_trade(token_id, side, price, size, outcome_label)

            # 2. REAL EXECUTION LOGIC
            clob_side = BUY if side.upper() == "BUY" else SELL
            
            order_args = OrderArgs(
                price=price,
                size=size,
                side=clob_side,
                token_id=token_id,
            )

            resp = self.client.create_and_post_order(order_args)
            
            if resp and resp.get("success"):
                # Log with Label
                logger.info(f"🚀 LIVE ORDER SENT: {side} {outcome_label} {size} @ {price} | ID: {resp.get('orderID')}")
                return resp.get("orderID")
            else:
                logger.error(f"❌ LIVE ORDER REJECTED: {resp.get('errorMsg')}")
                return None

        except Exception as e:
            logger.error(f"Execution Exception: {e}")
            return None

    def _simulate_trade(self, token_id, side, price, size, outcome_label):
        fake_order_id = f"sim-{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now().isoformat()
        
        # CHANGED: Added outcome_label to the log string
        logger.info(f"🧪 SIMULATED ORDER: {side} {outcome_label} {size} @ {price} | ID: {fake_order_id}")
        
        try:
            with open(Config.SIM_CSV_FILE, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    token_id,
                    outcome_label, # Added to CSV
                    side,
                    f"{price:.4f}",
                    f"{size:.2f}",
                    "FOK",
                    "FILLED (SIM)"
                ])
        except Exception as e:
            logger.error(f"Failed to write to CSV: {e}")

        return fake_order_id