Market selection logic
Process:
Scan up to 1000 markets that meet minimum requirements
Score each market (0-100)
Sort by score (descending)
Select the top 50 markets
Scoring system (0-100 points)
1. Liquidity score (40 points) — 40% weight
Higher liquidity = more capacity to execute trades
Formula: min(40, (liquidity / $50,000) * 40)
Examples:
$500 liquidity = 0.4 points
$5,000 liquidity = 4 points
$50,000+ liquidity = 40 points
2. Volume score (30 points) — 30% weight
Higher volume = more active trading, more opportunities
Formula: min(30, (volume / $10,000) * 30)
Examples:
$100 volume = 0.3 points
$1,000 volume = 3 points
$10,000+ volume = 30 points
3. Price efficiency score (20 points) — 20% weight
Markets with total price (Yes + No) close to $1.00 are more likely to have arbitrage
Scoring:
0.99-1.01 = 20 points (very efficient)
0.95-1.05 = 15 points (good)
0.90-1.10 = 10 points (acceptable)
Outside range = 0 points
4. Time until end score (10 points) — 10% weight
Sweet spot: 1-7 days (24-168 hours) = 10 points
7-30 days = 7 points
12-24 hours = 5 points
>30 days = 3 points
<12 hours = 1 point
Why this logic?
Liquidity (40%): Enables larger trades and reduces slippage
Volume (30%): Indicates active markets with more opportunities
Price efficiency (20%): Markets near $1.00 are more likely to show arbitrage
Time window (10%): 1-7 days balances opportunity with urgency
Result: The top 50 markets are those with the best combination of liquidity, activity, price efficiency, and timing for arbitrage opportunities.
The system now scans 1000 markets and automatically selects the best 50 to monitor.
Once the 50 markets are selected:
Fetches initial order book snapshots for all tokens
Validates actual order book data → removes markets without asks
Only monitors markets with real order book data
Result:
Markets showing "No Data" are filtered out before monitoring starts
Only markets with actual tradeable orders are tracked
The bot focuses on markets where arbitrage is possible
This ensures you only monitor markets with real order book liquidity, not just historical liquidity metrics.