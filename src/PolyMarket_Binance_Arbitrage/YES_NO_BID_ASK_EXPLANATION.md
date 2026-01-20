# Understanding YES/NO Options and Bid/Ask in Binary Markets

## The Relationship: YES/NO vs Bid/Ask

### YES and NO are Separate Tokens

Each binary market has **two separate tokens**:
- **YES Token**: Pays $1.00 if the event happens, $0.00 if it doesn't
- **NO Token**: Pays $1.00 if the event does NOT happen, $0.00 if it does

**Each token has its own orderbook** with its own bids and asks.

---

## Each Token Has Its Own Bid/Ask

### Example Market: "Will Bitcoin reach $125,000 in January?"

#### YES Token Orderbook:
```
Bids (orders wanting to BUY YES):
- $0.45 (size: 10,000 tokens) ← Total 10,000 tokens wanted at $0.45
- $0.44 (size: 5,000 tokens) ← Total 5,000 tokens wanted at $0.44
- $0.43 (size: 3,000 tokens) ← Total 3,000 tokens wanted at $0.43

Asks (orders wanting to SELL YES):
- $0.46 (size: 8,000 tokens) ← Total 8,000 tokens for sale at $0.46
- $0.47 (size: 6,000 tokens) ← Total 6,000 tokens for sale at $0.47
- $0.48 (size: 4,000 tokens) ← Total 4,000 tokens for sale at $0.48

Best Bid: $0.45 (highest price buyers will pay)
Best Ask: $0.46 (lowest price sellers will accept)
Spread: $0.01
```

#### NO Token Orderbook:
```
Bids (orders wanting to BUY NO):
- $0.54 (size: 12,000 tokens) ← Total 12,000 tokens wanted at $0.54
- $0.53 (size: 7,000 tokens) ← Total 7,000 tokens wanted at $0.53
- $0.52 (size: 4,000 tokens) ← Total 4,000 tokens wanted at $0.52

Asks (orders wanting to SELL NO):
- $0.55 (size: 9,000 tokens) ← Total 9,000 tokens for sale at $0.55
- $0.56 (size: 5,000 tokens) ← Total 5,000 tokens for sale at $0.56
- $0.57 (size: 3,000 tokens) ← Total 3,000 tokens for sale at $0.57

Best Bid: $0.54 (highest price buyers will pay)
Best Ask: $0.55 (lowest price sellers will accept)
Spread: $0.01
```

---

## The Relationship

### 1. YES + NO ≈ $1.00

In a healthy binary market:
- **YES Ask + NO Ask ≈ $1.00**
- **YES Bid + NO Bid ≈ $1.00**

**Example:**
```
YES Ask: $0.46
NO Ask: $0.55
Total: $1.01 (slight spread, normal)
```

**Why?** Because buying both YES and NO guarantees you get $1.00 payout, so their prices should sum to approximately $1.00.

---

### 2. Bid vs Ask for Each Token

**For YES Token:**
- **YES Bid** ($0.45): Highest price buyers are willing to pay for YES
- **YES Ask** ($0.46): Lowest price sellers are asking for YES
- **To buy YES**: You pay the Ask price ($0.46)
- **To sell YES**: You receive the Bid price ($0.45)

**For NO Token:**
- **NO Bid** ($0.54): Highest price buyers are willing to pay for NO
- **NO Ask** ($0.55): Lowest price sellers are asking for NO
- **To buy NO**: You pay the Ask price ($0.55)
- **To sell NO**: You receive the Bid price ($0.54)

---

## Visual Example

```
Market: "Will Bitcoin reach $125,000?"

┌─────────────────────────────────────────┐
│         YES TOKEN                       │
│  ┌─────────────────────────────────┐  │
│  │ Asks (Sellers)                  │  │
│  │ $0.48 ──────────────── 4,000    │  │
│  │ $0.47 ──────────────── 6,000    │  │
│  │ $0.46 ──────────────── 8,000 ← Ask│
│  │ ────────────────────────────────│  │
│  │ $0.45 ──────────────── 10,000 ← Bid│
│  │ $0.44 ──────────────── 5,000    │  │
│  │ $0.43 ──────────────── 3,000    │  │
│  │ Bids (Buyers)                   │  │
│  └─────────────────────────────────┘  │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│         NO TOKEN                        │
│  ┌─────────────────────────────────┐  │
│  │ Asks (Sellers)                  │  │
│  │ $0.57 ──────────────── 3,000    │  │
│  │ $0.56 ──────────────── 5,000    │  │
│  │ $0.55 ──────────────── 9,000 ← Ask│
│  │ ────────────────────────────────│  │
│  │ $0.54 ──────────────── 12,000 ← Bid│
│  │ $0.53 ──────────────── 7,000    │  │
│  │ $0.52 ──────────────── 4,000    │  │
│  │ Bids (Buyers)                   │  │
│  └─────────────────────────────────┘  │
└─────────────────────────────────────────┘

Total: YES Ask ($0.46) + NO Ask ($0.55) = $1.01 ✓
```

---

## Summary Table

| Concept | Meaning |
|---------|---------|
| **YES Token** | One outcome token (event happens) |
| **NO Token** | The other outcome token (event doesn't happen) |
| **Bid** | Highest price buyers are willing to pay (you can sell here) |
| **Ask** | Lowest price sellers are asking (you can buy here) |
| **YES Bid** | Price to **sell** YES |
| **YES Ask** | Price to **buy** YES |
| **NO Bid** | Price to **sell** NO |
| **NO Ask** | Price to **buy** NO |
| **Relationship** | YES Ask + NO Ask ≈ $1.00 (should sum to ~$1.00) |

---

## Real-World Example: High Liquidity Market

```
Market: "Will Bitcoin reach $125,000 in January?"

YES Token:
- Bid: $0.4500 (size: 50,000 tokens) ← Many people want to buy YES at $0.45
- Ask: $0.4510 (size: 45,000 tokens) ← Many people want to sell YES at $0.451
- Spread: $0.0010 (0.22%) ← Tight spread = liquid market

NO Token:
- Bid: $0.5490 (size: 48,000 tokens)
- Ask: $0.5500 (size: 52,000 tokens)
- Spread: $0.0010 (0.18%) ← Tight spread = liquid market

Total: $0.4510 + $0.5500 = $1.0010 ✓
```

**Why it's liquid:**
- Tight spread ($0.0010 difference)
- Large sizes (45,000+ tokens)
- Easy to buy/sell without moving price much

---

## Real-World Example: Low Liquidity Market

```
Market: "Will Bitcoin reach $125,000 in January?"

YES Token:
- Bid: $0.0010 (size: 351,464 tokens) ← Someone wants to buy YES at $0.001
- Ask: $0.9990 (size: 1,118,776 tokens) ← Someone wants to sell YES at $0.999
- Spread: $0.9980 (99,800%!) ← HUGE spread = illiquid market

NO Token:
- Bid: $0.0010 (size: 1,200,000 tokens)
- Ask: $0.9990 (size: 350,000 tokens)
- Spread: $0.9980 (99,800%!) ← HUGE spread = illiquid market

Total: $0.9990 + $0.0010 = $1.0000 ✓ (correct total, but terrible spread)
```

**Why it's illiquid:**
- **Very wide spread** ($0.9980 difference)
- Large gap between bid and ask
- Hard to trade at fair value without moving price significantly

---

## Real-World Analogy

### High Liquidity (like a popular stock):
```
Apple Stock:
- Bid: $150.00 (want to buy 10,000 shares)
- Ask: $150.01 (want to sell 9,500 shares)
Spread: $0.01 (0.007%)
→ Easy to buy/sell at fair price
```

### Low Liquidity (like a rare collectible):
```
Rare Baseball Card:
- Bid: $100 (one person wants to buy)
- Ask: $500 (one person wants to sell)
Spread: $400 (400%!)
→ Hard to find fair price, might have to wait or accept bad price
```

---

## Why This Matters for Your Bot

When your bot checks for lag opportunities:

1. **Gets YES Ask price** (cost to buy YES)
2. **Gets NO Ask price** (cost to buy NO)
3. **Checks if YES + NO ≈ $1.00** (validates the market)
4. **Compares YES price changes** vs Binance price movements

The **bid/ask spread** tells you about liquidity:
- **Tight spread** (e.g., $0.45 bid, $0.46 ask): Liquid market, easy to trade
- **Wide spread** (e.g., $0.001 bid, $0.999 ask): Illiquid market, hard to trade profitably

---

## Understanding "Size" in Orderbooks

### What Size Means

**Size = Total number of tokens available at that price level**

**Important:** Size does NOT mean the number of people. It represents the **total quantity of tokens** at that price, which could be from:
- One person with many tokens
- Many people with a few tokens each
- Any combination

### Example:

```
YES Token Bids:
- $0.45 (size: 10,000 tokens)
```

This means:
- **Total of 10,000 YES tokens** are wanted at $0.45
- Could be:
  - 1 person offering 10,000 tokens
  - 10 people each offering 1,000 tokens
  - 100 people each offering 100 tokens
  - Any combination totaling 10,000 tokens

The orderbook **aggregates all orders** at the same price level and shows the total quantity.

### Real Example:

```
YES Token Orderbook:

Bids (Buyers):
- $0.45 (size: 10,000) ← Total 10,000 tokens wanted at $0.45
  Could be:
  - Person A: 5,000 tokens
  - Person B: 3,000 tokens
  - Person C: 2,000 tokens
  Total: 10,000 tokens

- $0.44 (size: 5,600) ← Total 5,600 tokens wanted at $0.44
  Could be:
  - Person D: 3,000 tokens
  - Person E: 2,600 tokens
  Total: 5,600 tokens

Asks (Sellers):
- $0.46 (size: 8,000) ← Total 8,000 tokens for sale at $0.46
  Could be:
  - Person F: 4,500 tokens
  - Person G: 2,000 tokens
  - Person H: 1,500 tokens
  Total: 8,000 tokens
```

### Why This Matters:

- **Size shows liquidity**: Larger sizes = more tokens available at that price
- **Doesn't tell you number of people**: One large order looks the same as many small orders combined
- **Important for trading**: Larger sizes mean you can trade more without moving the price significantly

### Common Misconception:

| ❌ What you might think     | ✅ What it actually means                      |
|-----------------------------|------------------------------------------------|
| "10,000 people want to buy" | "10,000 tokens total are wanted at this price" |
| "5,600 people want to buy"  | "5,600 tokens total are wanted at this price"  |
| Number of people            | Total quantity of tokens                       |
|-----------------------------|------------------------------------------------|
**Remember:** Size = Total tokens, NOT number of people.

---

## How Order Matching Works When Buying/Selling

### Example: Buying 1,000 YES Tokens

**Scenario:** You want to buy 1,000 YES tokens

**Current Orderbook:**
```
YES Token Asks (Sellers):
- $0.46 (size: 8,000 tokens) ← Best Ask (lowest price)
- $0.47 (size: 6,000 tokens)
- $0.48 (size: 4,000 tokens)

YES Token Bids (Buyers):
- $0.45 (size: 10,000 tokens) ← Best Bid (highest price)
- $0.44 (size: 5,000 tokens)
```

### What Happens:

1. **You place a market order** to buy 1,000 YES tokens
2. **System matches your order** with sellers at the **best Ask price** ($0.46)
3. **You pay $460** ($0.46 × 1,000 tokens)
4. **Sellers receive payment** based on their portion

### Possible Outcomes:

#### Scenario A: One Seller Has Enough
```
Seller A has 8,000 tokens for sale at $0.46
Your order: Buy 1,000 tokens

Result:
- You buy 1,000 tokens from Seller A
- You pay: $460 ($0.46 × 1,000)
- Seller A receives: $460
- Seller A still has: 7,000 tokens remaining at $0.46
```

#### Scenario B: Multiple Sellers (Split Order)
```
Seller A has 500 tokens for sale at $0.46
Seller B has 300 tokens for sale at $0.46
Seller C has 200 tokens for sale at $0.46
Total available at $0.46: 1,000 tokens

Your order: Buy 1,000 tokens

Result:
- You buy 500 tokens from Seller A → Seller A receives $230 ($0.46 × 500)
- You buy 300 tokens from Seller B → Seller B receives $138 ($0.46 × 300)
- You buy 200 tokens from Seller C → Seller C receives $92 ($0.46 × 200)
- You pay total: $460 ($0.46 × 1,000)
- All sellers get paid for their portion
```

#### Scenario C: Need to Fill from Multiple Price Levels
```
Seller A has 600 tokens for sale at $0.46
Seller B has 400 tokens for sale at $0.47
(No more sellers at $0.46)

Your order: Buy 1,000 tokens

Result:
- You buy 600 tokens from Seller A at $0.46 → Seller A receives $276
- You buy 400 tokens from Seller B at $0.47 → Seller B receives $188
- You pay total: $464 ($0.46 × 600 + $0.47 × 400)
- Average price: $0.464 per token
```

### Important Points:

1. **You buy at ASK prices** (what sellers are asking), not bid prices
2. **System fills from best price first** ($0.46 before $0.47)
3. **Can be filled by one or multiple sellers** - system automatically splits
4. **Each seller gets paid** for their portion of tokens
5. **If not enough at one price**, system moves to next best price

### Selling Works Similarly:

If you want to **sell** 1,000 YES tokens:
- System matches with **buyers at best Bid price** ($0.45)
- You receive $450 ($0.45 × 1,000)
- Could be one buyer or multiple buyers
- Each buyer pays for their portion

---

## Order Types: Market Order vs Limit Order

When placing an order to buy 1,000 YES tokens, you have **two options**:

### 1. Market Order (No Price Specified)

**What you do:**
- Place order: "Buy 1,000 YES tokens" (no price specified)
- System executes **immediately** at best available Ask price

**What happens:**
```
Current Orderbook:
- Best Ask: $0.46 (8,000 tokens available)

Your order: Market buy 1,000 YES tokens

Result:
- Executes immediately at $0.46
- You pay: $460 ($0.46 × 1,000)
- No waiting, guaranteed execution
```

**Advantages:**
- ✅ Executes immediately
- ✅ Guaranteed to fill (if enough liquidity)
- ✅ No price specified needed

**Disadvantages:**
- ❌ You pay whatever sellers are asking (could be higher than you want)
- ❌ No control over price

---

### 2. Limit Order (Price Specified)

**What you do:**
- Place order: "Buy 1,000 YES tokens at $0.45" (price specified)
- System **only executes** if there are sellers willing to sell at $0.45 or better

**What happens:**

**Scenario A: Sellers available at your price**
```
Current Orderbook:
- Best Ask: $0.46 (8,000 tokens)
- Your limit order: Buy 1,000 YES at $0.45

Result:
- Order goes into orderbook as a BID
- Waits for sellers to match
- Only executes if:
  - Sellers lower their Ask to $0.45, OR
  - New sellers come in at $0.45, OR
  - Existing sellers accept your $0.45 bid
- You pay: $450 ($0.45 × 1,000) if matched
```

**Scenario B: No sellers at your price**
```
Current Orderbook:
- Best Ask: $0.46 (8,000 tokens)
- Your limit order: Buy 1,000 YES at $0.45

Result:
- Order sits in orderbook waiting
- Does NOT execute immediately
- You wait until sellers match your price
- If price never drops to $0.45, order never fills
```

**Advantages:**
- ✅ Control over price (won't pay more than you want)
- ✅ Can get better price if you're patient
- ✅ Order stays in book until filled or cancelled

**Disadvantages:**
- ❌ May not execute immediately (or at all)
- ❌ Price might move away from your limit
- ❌ Need to wait for sellers to match

---

### Summary Table

| Order Type       | Price Specified? | Execution   | When It Executes                 |
|------------------|------------------|-------------|----------------------------------|
| **Market Order** | ❌ No            | Immediate   | Right away at best Ask price     |
| **Limit Order**  | ✅ Yes           | Conditional | Only if sellers match your price |

### Example Comparison:

**Current Orderbook:**
```
Asks (Sellers):
- $0.46 (8,000 tokens)
- $0.47 (6,000 tokens)

Bids (Buyers):
- $0.45 (10,000 tokens)
- $0.44 (5,000 tokens)
```

**You want to buy 1,000 YES tokens:**

| Order Type               | What You Say             | What Happens                                 | Cost              |
|--------------------------|--------------------------|----------------------------------------------|-------------------|
| **Market Order**         | "Buy 1,000 YES"          | Executes immediately at $0.46                | $460              |
| **Limit Order at $0.45** | "Buy 1,000 YES at $0.45" | Waits, only executes if sellers match $0.45  | $450 (if matched) |
| **Limit Order at $0.47** | "Buy 1,000 YES at $0.47" | Executes immediately (your limit ≥ best Ask) | $470              |

### Key Point:

**Limit orders only execute if:**
- Your buy limit ≥ current Ask price (executes immediately)
- OR sellers lower their Ask to match your limit (executes when matched)

**Market orders:**
- Always execute immediately at best available Ask price
- No price control, but guaranteed execution

**To answer your question directly:**

> "when I place an order to buy the 1000 Yes token, do i also provide the price I want to buy it?"

**Answer:** It depends on the order type:
- **Market Order**: No price needed - executes immediately at best Ask
- **Limit Order**: Yes, you specify price - only executes if sellers match your price

> "Hence only if there are sellers (i.e. in the order book there are ASK orders for at least 1000 tokens) that wants to sell at the price I want to buy?"

**Answer:** 
- **Market Order**: No - executes immediately even if you don't specify price
- **Limit Order**: Yes - only executes if there are sellers at your specified price (or better)

---

## Key Takeaways

1. **YES and NO are separate tokens** - each has its own orderbook
2. **Each token has bid/ask prices** - bid = sell price, ask = buy price
3. **YES + NO should sum to ~$1.00** - this validates the market
4. **Spread = Ask - Bid** - smaller is better (more liquid)
5. **Size = total tokens available** - larger sizes = more liquidity (NOT number of people)

---

## For Trading

- **To buy YES**: Pay the YES Ask price
- **To sell YES**: Receive the YES Bid price
- **To buy NO**: Pay the NO Ask price
- **To sell NO**: Receive the NO Bid price

**The spread is your cost** - wider spreads mean higher trading costs and less profit potential.
