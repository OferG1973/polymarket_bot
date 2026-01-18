import csv
import requests
import asyncio
from collections import defaultdict
from config import Config

# Polymarket Gamma API (The Data Layer)
API_URL = "https://gamma-api.polymarket.com/markets"

async def fetch_market_details(token_id):
    """
    This is a call to examine each simulated trade to see if it won or lost money.
    The trades are read from a CSV file (sim_trades.csv) that is created by the bot.
    Reverse lookups the Token ID to find the Market Title and Outcome.
    """
    try:
        # We query the API filtering by the token_id
        response = requests.get(f"{API_URL}?token_id={token_id}")
        data = response.json()
        
        if data and isinstance(data, list) and len(data) > 0:
            market = data[0]
            title = market.get("question", "Unknown Market")
            
            # Determine if this ID is YES or NO
            outcomes = list(eval(market.get("outcomes", "['Yes', 'No']"))) # strict parsing
            outcome_index = -1
            
            # This is a heuristic; technically we check the clob_token_ids map
            # But usually index 0 is first token, index 1 is second.
            clob_ids = list(eval(market.get("clobTokenIds", "[]")))
            if token_id in clob_ids:
                outcome_index = clob_ids.index(token_id)
                outcome_label = outcomes[outcome_index] if outcome_index < len(outcomes) else "Unknown"
            else:
                outcome_label = "Unknown"
                
            return f"{title} [{outcome_label}]"
    except Exception as e:
        return f"Lookup Failed: {e}"
    return "Unknown ID"

def analyze_simulation():
    print("🔎 AUDITING SIMULATION RESULTS...\n")
    
    trades = []
    try:
        with open(Config.SIM_CSV_FILE, mode='r') as f:
            reader = csv.DictReader(f)
            trades = list(reader)
    except FileNotFoundError:
        print("❌ No csv file found. Run the bot first!")
        return

    # Group trades by Timestamp (approx) to find paired Arb trades
    # We group trades that happened within the same second
    grouped_trades = defaultdict(list)
    
    for t in trades:
        # Key = Timestamp up to the second
        ts_key = t["Timestamp"].split(".")[0] 
        grouped_trades[ts_key].append(t)

    # Analyze
    total_theoretical_profit = 0.0

    for ts, group in grouped_trades.items():
        if len(group) < 2:
            continue # Skip single legs (orphans)

        print(f"⏱  Time: {ts}")
        
        cost_basis = 0.0
        details = []

        for trade in group:
            t_id = trade["Token_ID"]
            price = float(trade["Price"])
            size = float(trade["Size"])
            side = trade["Side"]
            
            # Get Human Name (Blocking call for script simplicity)
            name = asyncio.run(fetch_market_details(t_id))
            
            print(f"   ├─ {side} {size} shares of '{name}' @ ${price}")
            cost_basis += price

        # THE PROFIT CHECK
        # In a perfect Yes+No arb, you own 1.00 payoff.
        # Profit = Payoff (1.00) - Cost Basis (YesPrice + NoPrice)
        
        # Note: This logic assumes you bought equal sizes of Yes and No
        # and that the market is binary (Yes/No).
        
        implied_profit_per_share = 1.00 - cost_basis
        
        # Color code result
        if implied_profit_per_share > 0:
            status = "✅ PROFITABLE" 
        else:
            status = "❌ LOSS"

        print(f"   └─ Total Cost: ${cost_basis:.4f} | Est. PnL: {implied_profit_per_share*100:.2f}% -> {status}")
        print("-" * 50)

if __name__ == "__main__":
    analyze_simulation()