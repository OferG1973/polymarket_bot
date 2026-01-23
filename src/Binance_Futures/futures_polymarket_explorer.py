import requests
import json
import logging
from typing import Dict, List, Optional
from py_clob_client.client import ClobClient
from datetime import datetime
import sys
import os

# Add parent directory to path to import bedrock_parser
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Polymarket'))
from bedrock_parser import MarketParser

# --- CONFIG ---
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

# Asset mapping for Polymarket tags and keywords
ASSET_TAGS_MAP = {
    "BTC": ["21", "235", "620"],  # Crypto tag, Bitcoin tag
    "ETH": ["21", "157"],          # Crypto tag, Ethereum tag
    "SOL": ["21", "455"]           # Crypto tag, Solana tag
}

ASSET_KEYWORDS_MAP = {
    "BTC": ["Bitcoin", "BTC"],
    "ETH": ["Ethereum", "ETH"],
    "SOL": ["Solana", "SOL"]
}

def parse_group_title(title: str) -> tuple[Optional[float], Optional[int]]:
    """
    Parses group titles like "90000-95000", "<90000", ">95000", "90000"
    Returns: (strike_price, direction) where direction: 1=above, -1=below, 0=range
    """
    try:
        title = title.lower().replace(",", "").replace("$", "").strip()
        
        # Range: "90000-95000"
        if "-" in title:
            parts = title.split("-")
            low = float(parts[0].strip())
            high = float(parts[1].strip())
            strike = (low + high) / 2  # Use midpoint as strike
            return strike, 0  # 0 = range
        
        # Below: "<90000"
        if "<" in title:
            val = float(title.replace("<", "").strip())
            return val, -1  # -1 = below
        
        # Above: ">90000"
        if ">" in title:
            val = float(title.replace(">", "").strip())
            return val, 1  # 1 = above
        
        # Exact: "90000"
        try:
            val = float(title)
            return val, 1  # Default to above for exact price
        except:
            pass
            
    except Exception as e:
        logging.debug(f"Error parsing group title '{title}': {e}")
    
    return None, None

def has_price_related_keywords(question: str, group_title: str = "") -> bool:
    """
    Checks if the question or group title contains price-related keywords.
    """
    text = (question + " " + group_title).lower()
    price_keywords = [
        "price", "above", "below", "over", "under", "reach", "hit", "touch",
        "higher", "lower", "exceed", "drop", "rise", "fall", "$", "usd"
    ]
    return any(keyword in text for keyword in price_keywords)

def scan_polymarket_markets(asset: str, current_price: float, limit: int = 50) -> List[Dict]:
    """
    Scans Polymarket for markets related to cryptocurrency price predictions.
    
    Args:
        asset: Cryptocurrency symbol (BTC, ETH, SOL)
        current_price: Current price of the asset (for filtering relevance)
        limit: Maximum number of markets to scan per tag
        
    Returns:
        List of dictionaries, each containing:
        {
            "strike_price": float,
            "label": str,  # Binary option label/outcome
            "direction": int,  # 1=above, -1=below, 0=range
            "option_0": {
                "price": float,  # Current market price (midpoint or ask)
                "bid": float,   # Best bid price
                "ask": float,   # Best ask price
                "bid_size": float,  # Available liquidity at best bid
                "ask_size": float,  # Available liquidity at best ask
                "label": str    # Actual option label (e.g., "YES", "Up", "True")
            },
            "option_1": {
                "price": float,
                "bid": float,
                "ask": float,
                "bid_size": float,
                "ask_size": float,
                "label": str    # Actual option label (e.g., "NO", "Down", "False")
            },
            "option_0_label": str,  # First option label from Polymarket
            "option_1_label": str,   # Second option label from Polymarket
            "question": str,
            "market_id": str,
            "liquidity": float
        }
    """
    if asset not in ASSET_TAGS_MAP:
        logging.error(f"Unsupported asset: {asset}. Supported: BTC, ETH, SOL")
        return []
    
    tags = ASSET_TAGS_MAP[asset]
    keywords = ASSET_KEYWORDS_MAP[asset]
    results = []
    
    # Initialize ClobClient for order book access
    client = ClobClient(HOST, chain_id=CHAIN_ID)
    
    # Initialize MarketParser for LLM-based strike price extraction
    # This uses Local LLM (Qwen via Ollama) as per bedrock_parser.py implementation
    try:
        market_parser = MarketParser()
        logging.info(f"      ✅ MarketParser initialized (Local LLM: Qwen via Ollama)")
    except Exception as e:
        logging.warning(f"      ⚠️ Failed to initialize MarketParser: {e}. Will use group title parsing only.")
        market_parser = None
    
    logging.info(f"🔍 Scanning Polymarket for {asset} price markets...")
    
    for tag_id in tags:
        offset = 0
        markets_found = 0
        
        while markets_found < limit:
            # Use events API to get markets grouped by events
            url = "https://gamma-api.polymarket.com/events"
            params = {
                "active": "true",
                "closed": "false",
                "tag_id": tag_id,
                "q": keywords[0],  # Primary keyword
                "order": "volume",
                "ascending": "false",
                "limit": 10,
                "offset": offset
            }
            
            try:
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code != 200:
                    logging.warning(f"API error: {resp.status_code}")
                    break
                    
                events = resp.json()
                if not isinstance(events, list) or len(events) == 0:
                    break
                
                for event in events:
                    # Filter events by keyword
                    event_title = event.get('title', '').lower()
                    if not any(k.lower() in event_title for k in keywords):
                        continue
                    
                    markets = event.get('markets', [])
                    if not markets:
                        continue
                    
                    for market in markets:
                        if markets_found >= limit:
                            break
                            
                        question = market.get('question', '')
                        group_title = market.get('groupItemTitle', '')
                        
                        # Filter by keywords
                        if not any(k.lower() in question.lower() for k in keywords):
                            continue
                        
                        # Filter for price-related markets
                        if not has_price_related_keywords(question, group_title):
                            continue
                        
                        # Check for valid binary outcomes
                        try:
                            raw_outcomes = market.get('outcomes')
                            if isinstance(raw_outcomes, str):
                                outcomes = json.loads(raw_outcomes)
                            else:
                                outcomes = raw_outcomes
                            
                            if not outcomes:
                                continue
                            
                            out_set = set(str(o).strip().lower() for o in outcomes)
                            valid_pairs = [{'yes', 'no'}, {'up', 'down'}, {'true', 'false'}]
                            if not any(out_set == pair for pair in valid_pairs):
                                continue
                        except:
                            continue
                        
                        # Parse strike price from group title first (fast path)
                        strike_price, direction = parse_group_title(group_title)
                        
                        # If group title parsing failed, use LLM to parse question
                        if strike_price is None and market_parser is not None:
                            try:
                                logging.info(f"      🤖 Using Local LLM to parse: {question[:60]}...")
                                parsed = market_parser.parse_question(question)
                                if parsed and parsed.get('asset') == asset:
                                    target_price = parsed.get('target_price')
                                    if target_price and target_price != "CURRENT_PRICE":
                                        strike_price = float(target_price)
                                        direction = parsed.get('direction', 1)
                                        logging.info(f"      ✅ LLM extracted strike: ${strike_price:,.0f}, direction: {direction}")
                                    elif target_price == "CURRENT_PRICE":
                                        strike_price = current_price
                                        direction = 0  # Range/current price
                                        logging.info(f"      ✅ LLM determined current price: ${strike_price:,.0f}")
                                else:
                                    logging.debug(f"      ⚠️ LLM parsing failed or asset mismatch for: {question[:60]}...")
                            except Exception as e:
                                logging.debug(f"Error parsing question with LLM: {e}")
                        
                        # Skip if we still can't determine strike price
                        if strike_price is None:
                            continue
                        
                        # Get token IDs and outcome labels
                        try:
                            tokens = market.get('clobTokenIds')
                            if isinstance(tokens, str):
                                tokens = json.loads(tokens)
                            if not tokens or len(tokens) < 2:
                                continue
                            
                            # Get actual outcome labels (e.g., ["YES", "NO"] or ["Up", "Down"])
                            outcome_labels = outcomes if outcomes else ["YES", "NO"]
                            label_0 = str(outcome_labels[0]).strip() if len(outcome_labels) > 0 else "YES"
                            label_1 = str(outcome_labels[1]).strip() if len(outcome_labels) > 1 else "NO"
                            
                            token_0 = tokens[0]  # First token corresponds to first outcome
                            token_1 = tokens[1]  # Second token corresponds to second outcome
                        except:
                            continue
                        
                        # Get order book data - use dynamic labels instead of "yes"/"no"
                        option_0_data = {"price": 0.0, "bid": 0.0, "ask": 0.0, "bid_size": 0.0, "ask_size": 0.0, "label": label_0}
                        option_1_data = {"price": 0.0, "bid": 0.0, "ask": 0.0, "bid_size": 0.0, "ask_size": 0.0, "label": label_1}
                        
                        try:
                            # First option token order book
                            ob_0 = client.get_order_book(token_0)
                            # Get best bid (highest price buyers will pay)
                            if hasattr(ob_0, 'bids') and ob_0.bids and len(ob_0.bids) > 0:
                                bid_order = ob_0.bids[0]
                                option_0_data["bid"] = float(bid_order.price)
                                # Get bid size (available liquidity at best bid)
                                if hasattr(bid_order, 'size'):
                                    option_0_data["bid_size"] = float(bid_order.size)
                                else:
                                    option_0_data["bid_size"] = 0.0
                            # Get best ask (lowest price sellers will accept)
                            if hasattr(ob_0, 'asks') and ob_0.asks and len(ob_0.asks) > 0:
                                ask_order = ob_0.asks[0]
                                option_0_data["ask"] = float(ask_order.price)
                                # Get ask size (available liquidity at best ask)
                                if hasattr(ask_order, 'size'):
                                    option_0_data["ask_size"] = float(ask_order.size)
                                else:
                                    option_0_data["ask_size"] = 0.0
                            # Use midpoint if both available, otherwise use ask or bid
                            if option_0_data["bid"] > 0 and option_0_data["ask"] > 0:
                                option_0_data["price"] = (option_0_data["bid"] + option_0_data["ask"]) / 2  # Market price = midpoint
                            elif option_0_data["ask"] > 0:
                                option_0_data["price"] = option_0_data["ask"]
                            elif option_0_data["bid"] > 0:
                                option_0_data["price"] = option_0_data["bid"]
                        except Exception as e:
                            logging.debug(f"Error fetching {label_0} order book for {token_0}: {e}")
                        
                        try:
                            # Second option token order book
                            ob_1 = client.get_order_book(token_1)
                            # Get best bid (highest price buyers will pay)
                            if hasattr(ob_1, 'bids') and ob_1.bids and len(ob_1.bids) > 0:
                                bid_order = ob_1.bids[0]
                                option_1_data["bid"] = float(bid_order.price)
                                # Get bid size (available liquidity at best bid)
                                if hasattr(bid_order, 'size'):
                                    option_1_data["bid_size"] = float(bid_order.size)
                                else:
                                    option_1_data["bid_size"] = 0.0
                            # Get best ask (lowest price sellers will accept)
                            if hasattr(ob_1, 'asks') and ob_1.asks and len(ob_1.asks) > 0:
                                ask_order = ob_1.asks[0]
                                option_1_data["ask"] = float(ask_order.price)
                                # Get ask size (available liquidity at best ask)
                                if hasattr(ask_order, 'size'):
                                    option_1_data["ask_size"] = float(ask_order.size)
                                else:
                                    option_1_data["ask_size"] = 0.0
                            # Use midpoint if both available, otherwise use ask or bid
                            if option_1_data["bid"] > 0 and option_1_data["ask"] > 0:
                                option_1_data["price"] = (option_1_data["bid"] + option_1_data["ask"]) / 2  # Market price = midpoint
                            elif option_1_data["ask"] > 0:
                                option_1_data["price"] = option_1_data["ask"]
                            elif option_1_data["bid"] > 0:
                                option_1_data["price"] = option_1_data["bid"]
                        except Exception as e:
                            logging.debug(f"Error fetching {label_1} order book for {token_1}: {e}")
                        
                        # Get liquidity
                        liquidity = 0.0
                        try:
                            liquidity = float(market.get('liquidity', 0))
                        except:
                            pass
                        
                        # Build result - use dynamic option labels
                        # Map first option to "option_0" and second to "option_1" for consistency
                        # But also include the actual labels for display
                        result = {
                            "strike_price": strike_price,
                            "label": group_title if group_title else question[:50],
                            "direction": direction,
                            "option_0": option_0_data,  # First option (e.g., YES, Up, True)
                            "option_1": option_1_data,  # Second option (e.g., NO, Down, False)
                            "option_0_label": label_0,   # Actual label from Polymarket
                            "option_1_label": label_1,   # Actual label from Polymarket
                            "question": question,
                            "market_id": market.get('conditionId', ''),
                            "liquidity": liquidity
                        }
                        
                        results.append(result)
                        markets_found += 1
                        
                        # Direction mapping: 1=above/bullish, -1=below/bearish, 0=range
                        direction_map = {1: "above", -1: "below", 0: "range"}
                        direction_str = direction_map.get(direction, f"unknown({direction})")
                        logging.info(f"  ✓ Found market: {question[:60]}... | Strike: ${strike_price:,.0f} | Direction: {direction_str} ({direction})")
                
                offset += 10
                if len(events) < 10:  # No more events
                    break
                    
            except Exception as e:
                logging.error(f"Error fetching markets for tag {tag_id}: {e}")
                break
    
    logging.info(f"✅ Found {len(results)} {asset} price markets")
    return results

def get_polymarket_markets_json(asset: str, current_price: float, limit: int = 50) -> str:
    """
    Convenience function that returns JSON string of markets.
    
    Args:
        asset: Cryptocurrency symbol (BTC, ETH, SOL)
        current_price: Current price of the asset
        limit: Maximum number of markets to scan
        
    Returns:
        JSON string containing list of market data
    """
    markets = scan_polymarket_markets(asset, current_price, limit)
    return json.dumps(markets, indent=2)

if __name__ == "__main__":
    # Test the function
    import sys
    
    asset = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    current_price = float(sys.argv[2]) if len(sys.argv) > 2 else 90000.0
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    markets = scan_polymarket_markets(asset, current_price, limit=10)
    print(json.dumps(markets, indent=2))
