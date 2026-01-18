# Polymarket Fee Structure & Minimum Spread Requirements

## Fee Overview

### International Markets (Default)
- **Profit Fee**: ~2% on profits (not on trades)
- **Taker Fee**: 0% (no taker fee for international markets)
- **Gas Fees**: ~$0.01-$0.50 per trade on Polygon
  - For arbitrage (2 trades): ~$0.02-$1.00 total
  - Using mid-range estimate: **$0.50 total** (2 × $0.25)

### US Markets
- **Profit Fee**: 0% (no profit fee for US markets)
- **Taker Fee**: 0.01% (1 basis point) on premium
- **Gas Fees**: Same as international (~$0.50 total for 2 trades)

### Additional Costs
- **Slippage**: 0.5-5% depending on liquidity (already accounted for in order book prices)
- **Network congestion**: Can increase gas costs during high-traffic periods

## Minimum Spread Requirements

### For International Markets
To be profitable after all fees, you need:
- **Gross Spread**: ~2.5-3.0% minimum
- **After 2% Profit Fee**: ~0.5-1.0% net
- **After Gas**: ~0.3-0.8% net profit

**Example:**
- Gross spread: 2.5%
- Investment: $50
- Gross profit: $1.25
- Profit fee (2%): -$0.025
- Gas: -$0.50
- **Net profit: $0.725** (1.45% net return)

### For US Markets
To be profitable after all fees, you need:
- **Gross Spread**: ~1.5-2.0% minimum
- **After 0.01% Taker Fee**: ~1.49-1.99% net
- **After Gas**: ~0.99-1.49% net profit

**Example:**
- Gross spread: 1.5%
- Investment: $50
- Gross profit: $0.75
- Taker fee (0.01%): -$0.005
- Gas: -$0.50
- **Net profit: $0.245** (0.49% net return)

## Current Configuration

The bot is configured with:
- `MIN_PROFIT_SPREAD = 0.015` (1.5% gross spread threshold)
- `MIN_NET_PROFIT_SPREAD = 0.005` (0.5% net profit after fees)
- `MARKET_TYPE = "international"` (default)

### For International Markets
- **Current 1.5% gross spread is TOO LOW** for international markets
- Need to increase `MIN_PROFIT_SPREAD` to **0.025-0.030** (2.5-3.0%) for international markets
- Or switch to US markets where 1.5% is more viable

### For US Markets
- **1.5% gross spread is viable** but tight
- Consider increasing to **0.018-0.020** (1.8-2.0%) for better margins

## Fee Calculation in Code

The bot now calculates:
1. **Gross Profit** = `profit_spread × trade_size`
2. **Taker Fee** = `total_investment × TAKER_FEE_RATE` (US markets only)
3. **Gas Cost** = `ESTIMATED_GAS_COST_PER_TRADE × 2` (2 trades)
4. **Profit Fee** = `gross_profit × PROFIT_FEE_RATE` (International markets only)
5. **Net Profit** = `gross_profit - (taker_fee + gas_cost + profit_fee)`

The bot will only execute trades where:
- Gross spread ≥ `MIN_PROFIT_SPREAD` (quick filter)
- Net profit spread ≥ `MIN_NET_PROFIT_SPREAD` (final check)

## Recommendations

1. **For International Markets**: Set `MIN_PROFIT_SPREAD = 0.025` (2.5%) or higher
2. **For US Markets**: Keep `MIN_PROFIT_SPREAD = 0.015` (1.5%) or increase to 0.018-0.020
3. **Monitor Gas Costs**: Adjust `ESTIMATED_GAS_COST_PER_TRADE` based on actual Polygon gas prices
4. **Test Both**: Try both market types to see which provides better opportunities

## Example: Your Recent Trade

From your logs: `Yes:0.0470 + No:0.9370 = 0.9840` (1.60% spread)

**For International Markets:**
- Gross profit: 1.60%
- After 2% profit fee: ~1.57%
- After gas ($0.50 on $50 trade): ~0.57% net
- **Result**: Barely profitable, but meets 0.5% minimum

**For US Markets:**
- Gross profit: 1.60%
- After 0.01% taker fee: ~1.59%
- After gas ($0.50 on $50 trade): ~0.59% net
- **Result**: Similar, but slightly better due to lower fees

**Recommendation**: This trade is at the edge of profitability. Consider increasing `MIN_PROFIT_SPREAD` to filter out marginal opportunities.
