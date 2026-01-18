import requests
import logging
from datetime import datetime, timezone
from typing import List, Dict
from config import Config

logger = logging.getLogger("Discovery")

class MarketDiscovery:
    GAMMA_API = "https://gamma-api.polymarket.com/markets"

    @staticmethod
    def _calculate_market_score(market: Dict, hours_until_end: float) -> float:
        """
        Calculate a score for market quality (higher = better for arbitrage)
        
        Scoring factors:
        1. Liquidity (40% weight) - Higher liquidity = more capacity to trade
        2. Volume (30% weight) - Higher volume = more active, more opportunities
        3. Price Efficiency (20% weight) - Closer to 1.0 = more arbitrage opportunities
        4. Time Until End (10% weight) - Sweet spot: 24-168 hours (1-7 days)
        
        Returns: Score from 0-100 (higher is better)
        """
        liquidity = market.get('liquidity', 0)
        volume = market.get('volume', 0)
        price_a = market.get('price_a', 0.5)
        price_b = market.get('price_b', 0.5)
        total_price = price_a + price_b
        
        # 1. Liquidity Score (0-40 points)
        # Normalize: $500 = 0, $50,000+ = 40
        liquidity_score = min(40, (liquidity / 50000) * 40)
        
        # 2. Volume Score (0-30 points)
        # Normalize: $100 = 0, $10,000+ = 30
        volume_score = min(30, (volume / 10000) * 30)
        
        # 3. Price Efficiency Score (0-20 points)
        # Markets with total_price close to 1.0 are more likely to have arbitrage
        # Perfect efficiency (1.0) = 20 points, 0.90-1.10 range
        price_diff = abs(1.0 - total_price)
        if price_diff <= 0.01:  # Very efficient (0.99-1.01)
            price_score = 20
        elif price_diff <= 0.05:  # Good efficiency (0.95-1.05)
            price_score = 15
        elif price_diff <= 0.10:  # Acceptable (0.90-1.10)
            price_score = 10
        else:
            price_score = 0
        
        # 4. Time Until End Score (0-10 points)
        # Sweet spot: 24-168 hours (1-7 days) = 10 points
        # Too soon (<24h) or too far (>30 days) = lower score
        if 24 <= hours_until_end <= 168:  # 1-7 days
            time_score = 10
        elif 168 < hours_until_end <= 720:  # 7-30 days
            time_score = 7
        elif 12 <= hours_until_end < 24:  # 12-24 hours
            time_score = 5
        elif hours_until_end > 720:  # >30 days
            time_score = 3
        else:  # <12 hours
            time_score = 1
        
        total_score = liquidity_score + volume_score + price_score + time_score
        return total_score

    @staticmethod
    def get_top_markets(limit: int = Config.MAX_MARKETS_TO_TRACK, skip_token_ids: set = None) -> List[Dict]:
        """
        Scan MARKETS_TO_SCAN markets, then select the best 'limit' markets based on scoring.
        
        Selection Logic:
        1. Scan up to MARKETS_TO_SCAN markets that meet minimum requirements
        2. Calculate a quality score for each market
        3. Sort by score (descending)
        4. Return top 'limit' markets
        
        Args:
            limit: Number of markets to return
            skip_token_ids: Set of token IDs to skip (to avoid duplicates when fetching more markets)
        """
        if skip_token_ids is None:
            skip_token_ids = set()
        
        scan_limit = Config.MARKETS_TO_SCAN
        logger.info(f"🔭 Scanning up to {scan_limit} markets, then selecting top {limit}...")
        
        valid_markets = []
        offset = 0
        batch_size = 100 # Max allowed by Gamma API per call is usually 100
        
        while len(valid_markets) < scan_limit:
            # 1. Fetch Batch
            params = {
                "active": "true",
                "closed": "false",
                "order": "volume:desc", # Still sort by volume to get 'best' first
                "limit": str(batch_size),
                "offset": str(offset)
            }

            try:
                resp = requests.get(MarketDiscovery.GAMMA_API, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                # If no more data, stop
                if not data:
                    break
                    
            except Exception as e:
                logger.error(f"Discovery Batch Failed: {e}")
                break

            # 2. Process Batch
            for m in data:
                try:
                    # VALIDATION 1: Market Status - Must be active and not closed
                    is_active = m.get("active", False)
                    is_closed = m.get("closed", True)
                    
                    if not is_active or is_closed:
                        continue  # Skip inactive or closed markets
                    
                    # VALIDATION 2: Liquidity Check (Skip dead markets)
                    liquidity = float(m.get("liquidity", 0))
                    if liquidity < Config.MIN_LIQUIDITY_USDC:
                        continue
                    
                    # VALIDATION 3: End Date - Must be in the future
                    end_iso = m.get("endDate", "")
                    if not end_iso:
                        continue  # Skip markets without end date
                    
                    try:
                        # Parse end date (handle both with and without timezone)
                        if end_iso.endswith("Z"):
                            end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
                        else:
                            end_dt = datetime.fromisoformat(end_iso)
                        
                        # Ensure timezone-aware comparison
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                        
                        now = datetime.now(timezone.utc)
                        
                        # Market must end in the future (at least 1 hour from now to be safe)
                        if end_dt <= now:
                            continue  # Skip expired markets
                        
                        # Optional: Skip markets ending too soon
                        time_until_end = (end_dt - now).total_seconds() / 3600
                        if time_until_end < Config.MIN_HOURS_UNTIL_END:
                            continue  # Skip markets ending too soon
                            
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid end date format: {end_iso} - {e}")
                        continue
                    
                    # VALIDATION 4: Outcomes & Tokens - Must be binary (2 outcomes)
                    outcomes_raw = m.get("outcomes")
                    outcomes = eval(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                    
                    prices_raw = m.get("outcomePrices")
                    prices = eval(prices_raw) if isinstance(prices_raw, str) else prices_raw

                    clob_ids = m.get("clobTokenIds")
                    clob_ids = eval(clob_ids) if isinstance(clob_ids, str) else clob_ids

                    if not outcomes or len(outcomes) != 2: 
                        continue  # Only binary markets
                    if not prices or len(prices) != 2: 
                        continue  # Must have prices for both outcomes
                    if not clob_ids or len(clob_ids) != 2: 
                        continue  # Must have token IDs for both outcomes
                    
                    # Skip markets we've already seen (if skip_token_ids is provided)
                    if skip_token_ids and (str(clob_ids[0]) in skip_token_ids or str(clob_ids[1]) in skip_token_ids):
                        continue
                    
                    # VALIDATION 5: Price Sanity Check - Prices should be reasonable
                    price_a = float(prices[0])
                    price_b = float(prices[1])
                    total_price = price_a + price_b
                    
                    # Total should be close to 1.0 (within reasonable range)
                    # Too far from 1.0 indicates market inefficiency or data issues
                    if total_price < 0.90 or total_price > 1.10:
                        continue  # Skip markets with extreme pricing
                    
                    # VALIDATION 6: Volume Check - Should have some trading activity
                    volume = float(m.get("volume", 0))
                    if volume < Config.MIN_VOLUME_USDC:
                        continue  # Skip markets with no trading activity

                    # Metadata formatting
                    start_iso = m.get("startDate", "")
                    start_date = datetime.fromisoformat(start_iso.replace("Z", "")).strftime("%Y-%m-%d") if start_iso else "-"
                    end_date = end_dt.strftime("%Y-%m-%d %H:%M") if end_dt else "-"
                    
                    # Calculate hours until end for scoring
                    hours_until_end = time_until_end
                    
                    market_obj = {
                        "title": m.get("question"),
                        "token_a": clob_ids[0],
                        "token_b": clob_ids[1],
                        "label_a": outcomes[0],
                        "label_b": outcomes[1],
                        "price_a": float(prices[0]),
                        "price_b": float(prices[1]),
                        "start_date": start_date,
                        "end_date": end_date,
                        "volume": float(m.get("volume", 0)),
                        "liquidity": liquidity,
                        "hours_until_end": hours_until_end  # Store for scoring
                    }
                    
                    valid_markets.append(market_obj)

                    if len(valid_markets) >= scan_limit:
                        break

                except Exception:
                    continue
            
            # Increment offset for next page
            offset += batch_size
            logger.info(f"   ... Scanned {offset} markets, found {len(valid_markets)} valid candidates so far.")

        logger.info(f"✅ Scanned {len(valid_markets)} valid markets. Scoring and selecting top {limit}...")
        
        # 3. Score and rank all valid markets
        scored_markets = []
        for market in valid_markets:
            score = MarketDiscovery._calculate_market_score(market, market.get('hours_until_end', 0))
            market['score'] = score
            scored_markets.append(market)
        
        # 4. Sort by score (descending) and select top N
        scored_markets.sort(key=lambda x: x['score'], reverse=True)
        top_markets = scored_markets[:limit]
        
        # 5. Log selection summary
        if top_markets:
            avg_score = sum(m['score'] for m in top_markets) / len(top_markets)
            avg_liquidity = sum(m['liquidity'] for m in top_markets) / len(top_markets)
            avg_volume = sum(m['volume'] for m in top_markets) / len(top_markets)
            logger.info(f"📊 Selected {len(top_markets)} markets:")
            logger.info(f"   Avg Score: {avg_score:.1f}/100")
            logger.info(f"   Avg Liquidity: ${avg_liquidity:,.0f}")
            logger.info(f"   Avg Volume: ${avg_volume:,.0f}")
        
        # 6. Print Summary Table (Top 20 only to keep console clean)
        MarketDiscovery._print_table(top_markets[:20], len(top_markets))
        
        return top_markets, scored_markets  # Return both top markets and all scored markets

    @staticmethod
    def _print_table(markets: List[Dict], total_count: int):
        """Prints a ASCII table of the top results"""# Define column widths
        w_name = 40
        w_date = 10
        w_outcome = 16
        w_liq = 12

        print("\n" + "="*145)
        print(f" DISPLAYING TOP 20 of {total_count} TRACKED MARKETS")
        print("="*145)
        header = (
            f"| {'MARKET NAME':<{w_name}} | "
            f"{'START':<{w_date}} | "
            f"{'END':<{w_date}} | "
            f"{'OUTCOME A (Available units)':<{w_outcome}} | "
            f"{'OUTCOME B (Available units)':<{w_outcome}} | "
            f"{'OUTCOME Total':<{w_outcome}} | "
            f"{'LIQUIDITY':<{w_liq}} |"
        )
        print(header)
        print("-" * 145)
        
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