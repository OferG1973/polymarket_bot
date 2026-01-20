# YES/NO Price Availability in Polymarket WebSocket

## What is the Long Number? (Token ID)

When you see logs like:
```
Token: Yes (1653721522673471...)
```

The long number (`1653721522673471...`) is the **Token ID** (also called `asset_id`). This is:
- A unique identifier for each token in Polymarket
- Used to subscribe to WebSocket updates for that specific token
- Used to place orders (buy/sell) for that token
- Truncated to first 16 characters in logs for readability

**Example:**
- YES token ID: `1653721522673471234567890` (full ID)
- NO token ID: `99625432243305851234567890` (full ID)
- In logs: `1653721522673471...` (truncated)

Each binary market has two tokens with different IDs - one for YES and one for NO.

When the log level is set to INFO, the log will only show the first YES wesocket message and first No websocket message coming form polymarket. When setting the log level to DETAILED we will see all websockets messages
---

## Why Sometimes YES or NO Shows "N/A"

### The Issue

When you see logs like:
```
📥 First Polymarket WebSocket data received for market: Will Bitcoin reach $125,000 in January?
Token: Yes (5683856116877116...) | Message type: book
Yes: $0.9990 | No: N/A (waiting for NO token data)
```

This is **normal behavior** and here's why:

Each WebSocket message is for one token (YES or NO). When YES arrives, NO isn't in that message. When NO arrives, YES isn't in that message.

---

## How Polymarket WebSocket Works

### 1. **Each Token Has Its Own Orderbook**

Every binary market has **two separate tokens**:
- **YES Token**: Has its own orderbook with bids/asks
- **NO Token**: Has its own orderbook with bids/asks

### 2. **WebSocket Messages Arrive Per Token**

When Polymarket sends WebSocket updates:
- Each message is for **ONE token** at a time (identified by `asset_id`)
- Messages arrive **asynchronously** (not simultaneously)
- You might receive YES token data before NO token data (or vice versa)

### 3. **Example Timeline**

```
Time 0.0s: Subscribe to market tokens (YES + NO)
Time 0.1s: Receive "book" message for YES token → Update YES orderbook
Time 0.2s: Log "First data received" → YES: $0.50, NO: N/A (not received yet)
Time 0.5s: Receive "book" message for NO token → Update NO orderbook
Time 0.6s: Log "Market fully initialized" → YES: $0.50, NO: $0.50 ✅
```

---

## What the Logs Mean

### Log 1: First Token Data Received

```
📥 First Polymarket WebSocket data received for market: Will Bitcoin reach $125,000?
Token: Yes (5683856116877116...) | Message type: book
⏳ Waiting for NO token data | Yes: $0.9990 | No: N/A (waiting for NO token data)
```

**Meaning:**
- We received first data for the **YES token**
- YES token orderbook is populated
- NO token hasn't received data yet → Shows "N/A"
- This is **normal** - messages arrive asynchronously

### Log 2: Both Tokens Initialized

```
✅ Market fully initialized (both tokens): Will Bitcoin reach $125,000?
Yes: $0.9990 | No: $0.0010 | Total: $1.0000 (spread: 0.00%)
```

**Meaning:**
- Both YES and NO tokens now have prices
- Market is fully initialized and ready for trading
- Total should be ~$1.00 (validates the binary market)

---

## Should We Always Have Both Prices?

### Short Answer: **Eventually, Yes**

### Long Answer:

1. **Initially:** You may see N/A for one token
   - WebSocket messages arrive asynchronously
   - One token's data arrives before the other
   - This is **normal** and **expected**

2. **Within Seconds:** Both tokens should have prices
   - Polymarket sends orderbook updates for both tokens
   - Usually within 1-2 seconds of subscription
   - System logs "Market fully initialized" when both are ready

3. **For Trading:** System checks for both prices
   - Before executing trades, system verifies both tokens have prices
   - If one is missing, trade is skipped with appropriate log message
   - This ensures we don't trade with incomplete data

---

## What Changed in the Code

### Before:
- Logged "First data received" when receiving data for one token
- Tried to show both YES and NO prices
- If one was missing, showed "N/A" without explanation

### After:
- Logs "First data received" when receiving data for one token
- **Clarifies** which token is missing: "⏳ Waiting for NO token data"
- Logs "Market fully initialized" when **both** tokens have prices
- Makes it clear this is normal asynchronous behavior

---

## Key Takeaways

1. ✅ **N/A is Normal:** It's expected to see N/A initially when one token's data hasn't arrived yet

2. ✅ **Both Prices Required:** For trading, we need prices for both YES and NO tokens

3. ✅ **Asynchronous Messages:** WebSocket messages arrive one at a time, not simultaneously

4. ✅ **System Handles It:** The system waits for both tokens before trading

5. ✅ **Logging Improved:** Logs now clarify when we're waiting for the other token

---

## Example Scenarios

### Scenario 1: YES Token Arrives First

```
Time 0.1s: 📥 First data received | Token: Yes | Yes: $0.50 | No: N/A (waiting for NO token data)
Time 0.5s: 📥 First data received | Token: No | Yes: $0.50 | No: $0.50
Time 0.6s: ✅ Market fully initialized | Yes: $0.50 | No: $0.50 | Total: $1.00
```

### Scenario 2: NO Token Arrives First

```
Time 0.1s: 📥 First data received | Token: No | Yes: N/A (waiting for YES token data) | No: $0.50
Time 0.5s: 📥 First data received | Token: Yes | Yes: $0.50 | No: $0.50
Time 0.6s: ✅ Market fully initialized | Yes: $0.50 | No: $0.50 | Total: $1.00
```

### Scenario 3: Both Arrive Simultaneously (Rare)

```
Time 0.1s: 📥 First data received | Token: Yes | ✅ Both tokens have prices | Yes: $0.50 | No: $0.50
Time 0.1s: ✅ Market fully initialized | Yes: $0.50 | No: $0.50 | Total: $1.00
```

---

## Conclusion

**Seeing "N/A" for one token initially is normal and expected.** The system:
- ✅ Logs clearly which token is missing
- ✅ Waits for both tokens before trading
- ✅ Logs when market is fully initialized
- ✅ Handles asynchronous WebSocket messages correctly

If you see "N/A" for **extended periods** (more than a few seconds), that might indicate:
- Network issues
- Token not subscribed properly
- Market has low/no liquidity for that token

But initial "N/A" is **completely normal** and part of how WebSocket streaming works.
