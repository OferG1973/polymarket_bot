# Order Type Strategy: LIMIT vs MARKET

## Overview

The system now supports both **LIMIT** and **MARKET** order types, with different behaviors for simulation and real trading.

---

## Configuration

### Config Parameters (`config.py`)

```python
# Order Type Configuration
ORDER_TYPE = "LIMIT"  # Options: "LIMIT" or "MARKET"

# Simulation mode: Set to True to test BOTH strategies simultaneously
SIMULATION_TEST_BOTH_STRATEGIES = True  # If True, simulates both LIMIT and MARKET orders
```

---

## Simulation Mode: Testing Both Strategies

When `SIMULATION_TEST_BOTH_STRATEGIES = True`:

### What Happens:

1. **For each lag opportunity detected:**
   - ✅ **LIMIT Strategy:** Executes limit order using `max_bid` calculation
   - ✅ **MARKET Strategy:** Executes market order using current best ask price
   - Both strategies are simulated **simultaneously** for comparison

2. **Separate CSV Logging:**
   - Main CSV: `sim_trades.csv` (contains both strategies)
   - LIMIT CSV: `sim_trades_LIMIT.csv` (only LIMIT orders)
   - MARKET CSV: `sim_trades_MARKET.csv` (only MARKET orders)

3. **Position Tracking:**
   - Both LIMIT and MARKET positions are tracked separately
   - Each position has its own exit logic
   - Performance can be compared after weeks of running

### Example Simulation Output:

```
🧪 SIMULATION MODE: Testing both LIMIT and MARKET strategies
   Testing LIMIT strategy (max_bid: $0.49517)
   Testing MARKET strategy (current ask: $0.5000)
📊 SIMULATED TRADE (LIMIT): ...
📊 SIMULATED TRADE (MARKET): ...
✅ Position opened (LIMIT): Will Bitcoin reach $125,000? (YES)
✅ Position opened (MARKET): Will Bitcoin reach $125,000? (YES)
```

---

## Real Trading Mode: Single Strategy

When `SIMULATION_MODE = False`:

### What Happens:

1. **Uses `ORDER_TYPE` from config:**
   - If `ORDER_TYPE = "LIMIT"`: Uses max_bid calculation, only executes if price ≤ max_bid
   - If `ORDER_TYPE = "MARKET"`: Executes immediately at current best ask (no max_bid check)

2. **LIMIT Order Behavior:**
   - Calculates `max_bid` based on expected profit
   - Only executes if `entry_price <= max_bid`
   - Provides price protection and profit guarantee

3. **MARKET Order Behavior:**
   - Executes immediately at current best ask price
   - No max_bid check (takes whatever price is available)
   - Faster execution, but less price control

---

## LIMIT Order Details

### Max Bid Calculation:

```python
# Step 1: Estimate expected Polymarket move (10% of Binance move)
expected_poly_move_pct = abs(binance_move_pct) * 0.1

# Step 2: Calculate expected exit price
expected_exit_price = current_poly_price * (1 + expected_poly_move_pct)

# Step 3: Calculate max_bid to ensure MIN_EXIT_PROFIT_PCT profit
max_bid = expected_exit_price / (1 + MIN_EXIT_PROFIT_PCT)
```

### Example:

```
Current Polymarket YES price: $0.5000
Binance moved: +0.25%
Expected Polymarket move: 0.025% (10% of Binance)
Expected exit price: $0.500125
MIN_EXIT_PROFIT_PCT: 1%
max_bid: $0.500125 / 1.01 = $0.49517

Decision:
- If entry_price = $0.5000 > max_bid = $0.49517 → Skip trade
- If entry_price = $0.4950 ≤ max_bid = $0.49517 → Execute trade
```

### Advantages:
- ✅ Price protection (won't overpay)
- ✅ Profit guarantee (ensures minimum profit target)
- ✅ Risk management

### Disadvantages:
- ⚠️ May skip profitable trades if price is slightly above max_bid
- ⚠️ Limit order may not fill if price moves away

---

## MARKET Order Details

### Behavior:

- Executes immediately at current best ask price
- No max_bid check
- Guaranteed execution (if liquidity available)

### Example:

```
Current Polymarket YES price: $0.5000
Binance moved: +0.25%

Decision:
- Execute immediately at $0.5000 (current best ask)
- No price check, guaranteed execution
```

### Advantages:
- ✅ Immediate execution
- ✅ Guaranteed fill (if liquidity available)
- ✅ Faster response to lag opportunities

### Disadvantages:
- ⚠️ No price protection (may overpay)
- ⚠️ No profit guarantee (price might be too high)
- ⚠️ Less risk management

---

## Comparison Strategy

### Simulation Mode Comparison:

After running for a few weeks, compare:

1. **Total Trades:**
   - LIMIT: How many trades executed?
   - MARKET: How many trades executed?

2. **Average Entry Price:**
   - LIMIT: Average entry price (should be lower due to max_bid)
   - MARKET: Average entry price (current ask)

3. **Profit/Loss:**
   - LIMIT: Total P&L
   - MARKET: Total P&L

4. **Win Rate:**
   - LIMIT: Percentage of profitable trades
   - MARKET: Percentage of profitable trades

5. **Average Profit per Trade:**
   - LIMIT: Average profit
   - MARKET: Average profit

### CSV Files for Analysis:

- `sim_trades_LIMIT.csv`: All LIMIT order trades
- `sim_trades_MARKET.csv`: All MARKET order trades
- Compare columns: `Price`, `Status`, `Pump_Pct` to analyze performance

---

## Recommended Workflow

1. **Phase 1: Simulation (Weeks 1-2)**
   - Set `SIMULATION_TEST_BOTH_STRATEGIES = True`
   - Run bot for 1-2 weeks
   - Collect data from both CSV files

2. **Phase 2: Analysis**
   - Compare LIMIT vs MARKET performance
   - Analyze:
     - Which strategy has better win rate?
     - Which strategy has higher average profit?
     - Which strategy executes more trades?

3. **Phase 3: Real Trading**
   - Set `SIMULATION_MODE = False`
   - Set `ORDER_TYPE` to the better performing strategy
   - Start live trading

---

## Configuration Examples

### Example 1: Simulation Testing Both Strategies

```python
SIMULATION_MODE = True
SIMULATION_TEST_BOTH_STRATEGIES = True
ORDER_TYPE = "LIMIT"  # Ignored in simulation when testing both
```

### Example 2: Real Trading with LIMIT Orders

```python
SIMULATION_MODE = False
SIMULATION_TEST_BOTH_STRATEGIES = False
ORDER_TYPE = "LIMIT"
```

### Example 3: Real Trading with MARKET Orders

```python
SIMULATION_MODE = False
SIMULATION_TEST_BOTH_STRATEGIES = False
ORDER_TYPE = "MARKET"
```

---

## Key Takeaways

1. **Simulation Mode:** Tests both strategies simultaneously for comparison
2. **Real Trading:** Uses single strategy based on `ORDER_TYPE` config
3. **LIMIT Orders:** Price protection via max_bid calculation
4. **MARKET Orders:** Immediate execution, no price protection
5. **Comparison:** Use CSV files to analyze which strategy performs better

---

## Files Modified

- `config.py`: Added `ORDER_TYPE` and `SIMULATION_TEST_BOTH_STRATEGIES`
- `execution.py`: Added support for both order types, separate CSV logging
- `delta_lag_strategy.py`: Added logic to test both strategies in simulation
