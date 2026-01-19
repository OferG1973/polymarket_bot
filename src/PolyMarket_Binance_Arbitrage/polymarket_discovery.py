import requests
import logging
import json
import time
from datetime import datetime, timezone
from typing import List, Dict, Set
from config import Config

logger = logging.getLogger("PolyMarketDiscovery")

class PolymarketDiscovery:
    """Discovers crypto price-related markets on Polymarket using events API with tag_id filtering"""
    
    EVENTS_API = "https://gamma-api.polymarket.com/events"
    
    def __init__(self, keywords: List[str] = None):
        """
        Initialize discovery with keywords
        
        Args:
            keywords: List of crypto keywords to search for (defaults to all crypto keywords from config)
        """
        self.keywords = keywords or Config.CRYPTO_KEYWORDS
        self.discovered_markets: List[Dict] = []
        
        # Build tag_id to crypto keyword mapping
        self.tag_id_to_keywords = {}
        # Build crypto to keywords mapping for market categorization
        self.crypto_to_keywords = {}
        for crypto in Config.TOP_CRYPTOS:
            tag_ids = crypto.get("tag_ids", [])
            crypto_keywords = crypto.get("keywords", [])
            crypto_name = crypto.get("name", "").lower()
            primary_keyword = crypto_keywords[0] if crypto_keywords else None
            
            # Map crypto name to its keywords
            self.crypto_to_keywords[crypto_name] = [k.lower() for k in crypto_keywords]
            
            for tag_id in tag_ids:
                if tag_id not in self.tag_id_to_keywords:
                    self.tag_id_to_keywords[tag_id] = []
                # Store all keywords for this tag_id
                self.tag_id_to_keywords[tag_id].extend(crypto_keywords)
    
    def search_markets(self, limit: int = 1000) -> List[Dict]:
        """
        Search for crypto price-related markets using events API with tag_id filtering
        Returns list of market dictionaries
        """
        markets = []
        all_tag_ids = Config.ALL_TAG_IDS
        
        logger.info(f"🔍 Searching Polymarket events for crypto price markets...")
        logger.info(f"   Using tag_ids: {all_tag_ids}")
        logger.info(f"   Keywords: {self.keywords[:10]}... (and more)")
        
        internal_limit = limit // len(all_tag_ids)  # Divide and round down to nearest int
        # Search events for each tag_id
        currencyCount = 0;
        for tag_id in all_tag_ids:
            if len(markets) >= limit:
                break
            
            # Get appropriate keyword for this tag_id
            tag_keywords = self.tag_id_to_keywords.get(tag_id, [])
            if not tag_keywords:
                logger.warning(f"   ⚠️  No keywords mapped for tag_id {tag_id}, skipping...")
                continue
            
            # Use primary keyword for this tag_id
            search_q = tag_keywords[0]
            logger.info(f"   Searching tag_id: {tag_id} with keyword: {search_q}...")
            offset = 0
            batch_size = 10
            currencyCount+=1
            new_limit = internal_limit * currencyCount
            while len(markets) < new_limit:
                try:
                    # If tag_id == 21, do not include "q" in the params
                    params = {
                        "active": "true",
                        "closed": "false",
                        "tag_id": tag_id,
                        "order": "volume",
                        "ascending": "false",
                        "limit": batch_size,
                        "offset": offset
                    }
                    if tag_id != 21:
                        params["q"] = search_q
                    
                    resp = requests.get(self.EVENTS_API, params=params, timeout=10)
                    resp.raise_for_status()
                    events = resp.json()
                    
                    if not isinstance(events, list) or len(events) == 0:
                        break
                    
                    # Process each event
                    for event in events:
                        if len(markets) >= new_limit:
                            break
                        
                        event_title = event.get('title', '').lower()
                        
                        # Filter events by keywords specific to this tag_id
                        # Use tag-specific keywords to ensure we get the right crypto events
                        tag_keywords_lower = [k.lower() for k in tag_keywords]
                        if not any(keyword in event_title for keyword in tag_keywords_lower):
                            continue
                        
                        # Extract markets from event
                        event_markets = event.get('markets', [])
                        
                        for market in event_markets:
                            if len(markets) >= new_limit:
                                break
                            
                            # Validate and process market
                            validated_market = self._validate_and_format_market(market, event)
                            if validated_market:
                                markets.append(validated_market)
                                market_title = validated_market.get('title', 'Unknown')
                                liquidity = validated_market.get('liquidity', 0)
                                logger.info(f"   ✅ Found crypto price market: {market_title[:80]}... (Liquidity: ${liquidity:,.0f})")
                    
                    offset += batch_size
                    time.sleep(0.5)  # Rate limiting
                    
                except Exception as e:
                    logger.error(f"Error fetching events for tag_id {tag_id}: {e}")
                    break
        
        logger.info(f"\n✅ Discovery Complete: Found {len(markets)} valid crypto price markets")
        if markets:
            logger.info("   Markets discovered:")
            for i, market in enumerate(markets, 1):
                market_title = market.get('title', 'Unknown Market')
                liquidity = market.get('liquidity', 0)
                logger.info(f"      {i}. {market_title} (Liquidity: ${liquidity:,.0f})")
        
        self.discovered_markets = markets
        return markets
    
    def _validate_and_format_market(self, market: Dict, event: Dict = None) -> Dict:
        """
        Validate and format a market from an event
        Returns formatted market dict if valid, None otherwise
        """
        try:
            # 1. Check liquidity
            liquidity = float(market.get('liquidity', 0))
            if liquidity < Config.MIN_LIQUIDITY_USDC:
                return None
            
            # 2. Check if market question contains crypto keywords
            question = market.get('question', '').lower()
            if not any(keyword.lower() in question for keyword in self.keywords):
                return None
            
            # 3. Validate outcomes - must be binary (yes/no, up/down, true/false)
            raw_outcomes = market.get('outcomes')
            if isinstance(raw_outcomes, str):
                outcomes = json.loads(raw_outcomes)
            else:
                outcomes = raw_outcomes
            
            if not outcomes or len(outcomes) != 2:
                return None
            
            # Check if outcomes are valid binary pairs
            out_set = set(str(o).strip().lower() for o in outcomes)
            valid_pairs = [{'yes', 'no'}, {'up', 'down'}, {'true', 'false'}]
            if not any(out_set == pair for pair in valid_pairs):
                return None
            
            # 4. Check if market is active and not closed
            if not market.get("active", False) or market.get("closed", True):
                return None
            
            # 5. Check if has token IDs
            clob_ids = market.get("clobTokenIds")
            if isinstance(clob_ids, str):
                clob_ids = json.loads(clob_ids)
            
            if not clob_ids or len(clob_ids) != 2:
                return None
            
            # 6. Check end date (must be in future)
            end_iso = market.get("endDate", "")
            if end_iso:
                try:
                    if end_iso.endswith("Z"):
                        end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
                    else:
                        end_dt = datetime.fromisoformat(end_iso)
                    
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    
                    now = datetime.now(timezone.utc)
                    if end_dt <= now:
                        return None
                except:
                    return None
            
            # 7. Format market data
            prices_raw = market.get("outcomePrices")
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw
            
            end_date = None
            if end_iso:
                try:
                    if end_iso.endswith("Z"):
                        end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
                    else:
                        end_dt = datetime.fromisoformat(end_iso)
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    end_date = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    end_date = end_iso
            
            return {
                "title": market.get("question", ""),
                "token_a": clob_ids[0] if clob_ids else None,
                "token_b": clob_ids[1] if clob_ids else None,
                "label_a": outcomes[0] if outcomes else "",
                "label_b": outcomes[1] if outcomes else "",
                "price_a": float(prices[0]) if prices else 0.5,
                "price_b": float(prices[1]) if prices else 0.5,
                "liquidity": liquidity,
                "volume": float(market.get("volume", 0)),
                "end_date": end_date,
                "market_id": market.get("id"),
                "slug": market.get("slug"),
                "event_title": event.get("title", "") if event else ""
            }
            
        except Exception as e:
            logger.debug(f"Error validating/formatting market: {e}")
            return None
    
    def _categorize_market_by_crypto(self, market: Dict) -> str:
        """Determine which crypto a market belongs to based on keywords"""
        title = market.get('title', '').lower()
        
        # Check each crypto's keywords
        for crypto_name, keywords in self.crypto_to_keywords.items():
            if any(keyword in title for keyword in keywords):
                return crypto_name
        
        return "unknown"
    
    def get_top_markets(self, limit: int = Config.MAX_MARKETS_TO_MONITOR) -> List[Dict]:
        """
        Get top markets with balanced representation across all cryptos
        Ensures we get markets from Bitcoin, Ethereum, Solana, etc.
        """
        if not self.discovered_markets:
            self.search_markets(limit=limit * 3)  # Search more to get better selection
        
        # Group markets by crypto
        markets_by_crypto = {}
        for market in self.discovered_markets:
            crypto = self._categorize_market_by_crypto(market)
            if crypto not in markets_by_crypto:
                markets_by_crypto[crypto] = []
            markets_by_crypto[crypto].append(market)
        
        # Log distribution
        logger.info(f"📊 Markets found by crypto:")
        for crypto, markets in markets_by_crypto.items():
            logger.info(f"   {crypto.capitalize()}: {len(markets)} markets")
        
        # Calculate markets per crypto (balanced distribution)
        num_cryptos = len([c for c in markets_by_crypto.keys() if c != "unknown"])
        if num_cryptos == 0:
            # Fallback: just sort by liquidity
            sorted_markets = sorted(
                self.discovered_markets,
                key=lambda x: x.get("liquidity", 0),
                reverse=True
            )
            return sorted_markets[:limit]
        
        markets_per_crypto = max(1, limit // num_cryptos)
        remaining = limit - (markets_per_crypto * num_cryptos)
        
        selected_markets = []
        
        # Select top markets from each crypto
        for crypto, markets in markets_by_crypto.items():
            if crypto == "unknown":
                continue
            
            # Sort by liquidity within this crypto
            sorted_crypto_markets = sorted(
                markets,
                key=lambda x: x.get("liquidity", 0),
                reverse=True
            )
            
            # Take top N markets for this crypto
            take_count = markets_per_crypto
            if remaining > 0:
                take_count += 1
                remaining -= 1
            
            selected_markets.extend(sorted_crypto_markets[:take_count])
        
        # Sort final selection by liquidity
        final_markets = sorted(
            selected_markets,
            key=lambda x: x.get("liquidity", 0),
            reverse=True
        )
        
        logger.info(f"✅ Selected {len(final_markets)} markets (balanced across {num_cryptos} cryptos)")
        
        return final_markets[:limit]
