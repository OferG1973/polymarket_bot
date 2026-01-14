Here is a concrete example using the actual price of Bitcoin to show how the **Edge** logic works.

### The Setup
*   **Current Bitcoin Price:** **$97,000**
*   **The Polymarket Question:** "Will Bitcoin be above **$98,000** by Midnight?"

---

### Step 1: The Market's Opinion (The Price)
Traders on Polymarket look at the chart. They see Bitcoin needs to jump $1,000 in a few hours. They think it's possible but risky.
*   They are selling the "Yes" share for **60 cents** ($0.60).
*   **Translation:** The market says there is a **60%** chance this happens.

### Step 2: Your AI's Opinion (The Math)
Your bot analyzes the data:
*   **RSI:** 45 (Not overbought, plenty of room to grow).
*   **Nasdaq:** Tech stocks just rallied 2% (Bitcoin usually follows).
*   **Trend:** The 50-hour moving average is pointing straight up.

The AI calculates its own probability based on 2 years of history:
*   **AI Confidence:** **0.75** (75%).
*   **Translation:** "Mathematically, setups like this hit the target 75% of the time."

### Step 3: Calculating the Edge
Now the bot compares the two numbers.

$$ \text{AI (0.75)} - \text{Market (0.60)} = \mathbf{0.15} \text{ (15\% Edge)} $$

### Step 4: The Decision
The bot checks your rule: **"Is the Edge > 10%?"**
*   **15% > 10%** $\rightarrow$ **YES.**

The bot prints:
`🔥 BUY: Will Bitcoin be above $98,000... (AI: 0.75 vs Mkt: 0.60 | Edge: 15.0%)`

---

### Comparison: When the Bot says NO
Imagine the exact same scenario, but the **Market Price is higher**.

*   **Current Bitcoin Price:** $97,000
*   **Target:** $98,000
*   **Market Price:** **68 cents** ($0.68). (Everyone is super bullish).
*   **AI Prediction:** **0.75** (75%).

**The Math:**
$$ 0.75 - 0.68 = \mathbf{0.07} \text{ (7\% Edge)} $$

**The Decision:**
*   **7% < 10%** $\rightarrow$ **NO.**
*   **Reason:** Even though the AI thinks "Yes" will likely win, the price is too expensive. There isn't enough "profit margin" to justify the risk. The bot skips the trade.

### Summary
*   **Bitcoin Price:** Used to calculate the features (RSI, Trend).
*   **Share Price:** Used to calculate the cost.
*   **Edge:** The discount you get buying the share compared to its "True Value" calculated by the AI.