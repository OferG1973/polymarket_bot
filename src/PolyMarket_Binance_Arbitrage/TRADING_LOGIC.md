# Trading Logic Explanation

## Overview

This bot implements a **Delta Lag Strategy** that exploits the time delay between Binance (fast) and Polymarket (slow) price updates. When Binance moves quickly, Polymarket takes 2-10 seconds to catch up, creating arbitrage opportunities.

## Trading Decision Flow

### Step 1: Binance Price Move Detection

**What happens:**
- Bot monitors Binance WebSocket for real-time price updates
- Detects when price moves **> 0.2%** within **10 seconds** (configurable: `DELTA_THRESHOLD_PERCENT = 0.2%`)
- **Only trades on upward moves** (direction = 'up')
- Example: Bitcoin moves from $50,000 → $50,100 (0.2% increase)

**Code location:** `binance_feed.py` → `detect_delta_move()`

---

### Step 2: Market Matching

**What happens:**
When a Binance move is detected, the bot finds related Polymarket markets:

```python
def _find_related_markets(self, crypto_name: str, symbol: str):
    # Searches through all monitored markets
    # Matches by checking if market title contains crypto keywords
    # Example: "Bitcoin" or "BTC" in market title
```

**Market Matching Examples:**
- ✅ "Will Bitcoin reach $100k by January 2025?" → Matches Bitcoin moves
- ✅ "Will Ethereum be above $3000 on January 19?" → Matches Ethereum moves
- ✅ "Will Solana hit $200 by March?" → Matches Solana moves

**Code location:** `delta_lag_strategy.py` → `_find_related_markets()`

---

### Step 3: Lag Detection

**What happens:**
For each related market, the bot checks if Polymarket has lagged behind Binance:

```python
async def _check_lag_opportunity(self, market, move_info):
    # Gets current Polymarket price
    # Compares to last known Polymarket price
    # Calculates: Has Polymarket reacted to Binance move?
```

**Lag Detection Conditions (ALL must be true):**

1. ✅ **Binance moved > 0.2% upward**
2. ✅ **Polymarket price change < expected reaction**
   - Expected reaction = 10% of Binance move
   - Example: If Binance moved 0.3%, Polymarket should move ~0.03%
3. ✅ **Time since last Polymarket update > 2 seconds**
   - This confirms there's a lag window

**Example Scenario:**
- **Binance:** Bitcoin moved +0.3% (from $50,000 → $50,150)
- **Expected Polymarket reaction:** YES price should move ~0.03% (10% of 0.3%)
- **Actual Polymarket:** YES price hasn't moved (still at $0.4500)
- **Result:** ✅ **LAG DETECTED** → Buy signal triggered!

**Code location:** `delta_lag_strategy.py` → `_check_lag_opportunity()`

---

### Step 4: Trade Execution

**What happens when lag is detected:**

#### 1. Which Outcome to Buy?
- **Always buys the "YES" outcome** (token_a)
- Assumes markets are bullish (e.g., "Bitcoin > $100k")
- Logic: If Bitcoin price goes up → probability of "YES" increases → buy YES

#### 2. Trade Size Calculation:
```python
trade_size = min(
    MAX_TRADE_SIZE_USDC / entry_price,  # Max $100 per trade
    market_liquidity / 10                # Or 10% of available liquidity
)
```

#### 3. Execution:
- Places buy order for YES outcome at current Polymarket price
- Records position with entry time and price
- Logs trade details

**Code location:** `delta_lag_strategy.py` → `_execute_lag_trade()`

---

### Step 5: Exit Strategy

**What happens after entering a position:**

#### 1. Hold Time
- Waits **30 seconds** (`EXIT_HOLD_SECONDS = 30`)
- Gives Polymarket time to catch up to Binance price

#### 2. Exit Conditions
- **Time-based:** After 30 seconds, check profit
- **Profit threshold:** Must have ≥ **1% profit** (`MIN_EXIT_PROFIT_PCT = 0.01`)
- If profit threshold met → exit position
- If not met → continue holding

#### 3. Exit Logic:
```python
current_price = get_current_polymarket_price()
profit_pct = ((current_price - entry_price) / entry_price) * 100

if profit_pct >= 1.0%:
    # Exit position (sell YES outcome)
else:
    # Continue holding
```

**Code location:** `delta_lag_strategy.py` → `_exit_position()`

---

## Complete Example Walkthrough

### Scenario:
1. **Binance:** Bitcoin moves from $50,000 → $50,150 (+0.3% in 5 seconds)
2. **Bot finds:** "Will Bitcoin reach $100k by January 2025?" market
3. **Checks lag:**
   - Last Polymarket YES price: $0.4500
   - Current Polymarket YES price: $0.4500 (no change)
   - Expected move: 0.03% (should be ~$0.4501)
   - ✅ **Lag detected!**
4. **Executes trade:**
   - Buys YES outcome at $0.4500
   - Trade size: $100 / $0.45 = 222.22 shares
5. **Waits 30 seconds**
6. **Checks exit:**
   - Polymarket caught up: YES price now $0.4550 (+1.11%)
   - Profit > 1% threshold → exits position
   - **Profit: $11.11** (1.11% of $100)

---

## Key Configuration Parameters

All parameters are in `config.py`:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `DELTA_THRESHOLD_PERCENT` | 0.2% | Minimum Binance move to trigger |
| `DELTA_DETECTION_WINDOW` | 10s | Time window for detecting moves |
| `EXPECTED_LAG_MIN` | 2s | Minimum expected lag between exchanges |
| `EXIT_HOLD_SECONDS` | 30s | How long to hold before checking exit |
| `MIN_EXIT_PROFIT_PCT` | 1.0% | Minimum profit to exit |
| `MAX_TRADE_SIZE_USDC` | $100 | Maximum trade size |

---

## Strategy Concept

The strategy exploits the **2-10 second lag** between:
- **Binance** (fast, instant price updates)
- **Polymarket** (slower, blockchain-based updates)

**The Edge:**
1. Binance price moves instantly
2. Polymarket market makers take 2-10 seconds to adjust prices
3. Bot detects the move on Binance first
4. Buys on Polymarket before prices adjust
5. Sells after Polymarket catches up (30 seconds later)
6. Profits from the price difference

**Frequency:**
- 0.2% moves happen **frequently** (multiple times per hour)
- Much more frequent than waiting for 4.5% "black swan" events
- Enables high-frequency trading opportunities

---

## Risk Management

1. **Position Limits:** Only one position per market at a time
2. **Trade Size Limits:** Maximum $100 per trade
3. **Liquidity Checks:** Only trades markets with sufficient liquidity
4. **Cooldown Periods:** Prevents over-trading on same market
5. **Profit Thresholds:** Only exits when profit meets minimum threshold

---

## Files Involved

- **`delta_lag_strategy.py`**: Core trading logic
- **`binance_feed.py`**: Binance WebSocket monitoring and move detection
- **`polymarket_price_monitor.py`**: Polymarket WebSocket monitoring
- **`execution.py`**: Trade execution (simulation or live)
- **`config.py`**: All configuration parameters

---

## Monitoring

The bot logs all trading decisions:
- ✅ Binance moves detected
- ✅ Markets matched
- ✅ Lag opportunities found
- ✅ Trades executed
- ✅ Positions opened/closed
- ✅ Profits realized

Check logs for detailed trading activity.
