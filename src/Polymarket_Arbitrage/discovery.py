import requests
import logging
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger("Discovery")

class MarketDiscovery:
    GAMMA_API = "https://gamma-api.polymarket.com/markets"

    @staticmethod
    def get_top_markets(limit: int = 20) -> List[Dict]:
        logger.info("🔭 Scanning Polymarket for active opportunities...")
        
        params = {
            "active": "true",
            "closed": "false",
            "order": "volume:desc",
            "limit": str(limit * 3)
        }

        try:
            resp = requests.get(MarketDiscovery.GAMMA_API, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Discovery Failed: {e}")
            return []

        valid_markets = []

        for m in data:
            try:
                # 1. Parse Outcomes (e.g. ["Yes", "No"])
                outcomes_raw = m.get("outcomes")
                outcomes = eval(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                
                # 2. Parse Prices (e.g. ["0.60", "0.40"])
                prices_raw = m.get("outcomePrices")
                prices = eval(prices_raw) if isinstance(prices_raw, str) else prices_raw

                # Validation: We need exactly 2 outcomes and 2 prices
                if not outcomes or len(outcomes) != 2: continue
                if not prices or len(prices) != 2: continue
                
                # 3. Parse Token IDs
                clob_ids = m.get("clobTokenIds")
                clob_ids = eval(clob_ids) if isinstance(clob_ids, str) else clob_ids
                
                if not clob_ids or len(clob_ids) != 2: continue

                # 4. Metadata
                start_iso = m.get("startDate", "")
                end_iso = m.get("endDate", "")
                start_date = datetime.fromisoformat(start_iso.replace("Z", "")).strftime("%Y-%m-%d") if start_iso else "-"
                end_date = datetime.fromisoformat(end_iso.replace("Z", "")).strftime("%Y-%m-%d") if end_iso else "-"
                
                valid_markets.append({
                    "title": m.get("question"),
                    "token_a": clob_ids[0],
                    "token_b": clob_ids[1],
                    "label_a": outcomes[0],
                    "label_b": outcomes[1],
                    "price_a": float(prices[0]), # Convert "0.65" string to float
                    "price_b": float(prices[1]),
                    "start_date": start_date,
                    "end_date": end_date,
                    "volume": float(m.get("volume", 0)),
                    "liquidity": float(m.get("liquidity", 0))
                })

                if len(valid_markets) >= limit:
                    break

            except Exception:
                continue
        
        # 5. Print the Table
        MarketDiscovery._print_table(valid_markets)
        
        return valid_markets

    @staticmethod
    def _print_table(markets: List[Dict]):
        """Prints a detailed ASCII table"""
        # Define column widths
        w_name = 40
        w_date = 10
        w_outcome = 16
        w_liq = 12

        # Header
        print("\n" + "="*145)
        header = (
            f"| {'MARKET NAME':<{w_name}} | "
            f"{'START':<{w_date}} | "
            f"{'END':<{w_date}} | "
            f"{'OUTCOME A':<{w_outcome}} | "
            f"{'OUTCOME B':<{w_outcome}} | "
            f"{'OUTCOME Total':<{w_outcome}} | "
            f"{'LIQUIDITY':<{w_liq}} |"
        )
        print(header)
        print("="*145)
        
        for m in markets:
            # Format Data
            title = (m['title'][:w_name-2] + '..') if len(m['title']) > w_name else m['title']
            
            # Combine Label + Price (e.g., "Yes: 0.65")
            out_a = f"{m['label_a']}: {m['price_a']:.2f}"
            out_b = f"{m['label_b']}: {m['price_b']:.2f}"
            out_total = m['price_a'] + m['price_b']
            liq_str = f"${m['liquidity']:,.0f}"
            
            row = (
                f"| {title:<{w_name}} | "
                f"{m['start_date']:<{w_date}} | "
                f"{m['end_date']:<{w_date}} | "
                f"{out_a:<{w_outcome}} | "
                f"{out_b:<{w_outcome}} | "
                f"{out_total:<{w_outcome}} | "
                f"{liq_str:<{w_liq}} |"
            )
            print(row)
        
        print("="*145 + "\n")