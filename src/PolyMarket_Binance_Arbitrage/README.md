# Binance-Polymarket Cross-Exchange Arbitrage Bot

This bot exploits the lag between Binance (crypto exchange) and Polymarket (prediction market) to profit from rapid price movements.

## Strategy

When Bitcoin (or other crypto) pumps more than **4.5% in 1 minute** on Binance, related Polymarket markets (e.g., "Bitcoin > 100k") lag by 10-30 seconds. The bot buys on Polymarket before the crowd reacts.

## How It Works

1. **Binance Monitoring**: Continuously monitors Binance price using `ccxt` library
2. **Pump Detection**: Detects when price increases >4.5% in 60 seconds
3. **Market Discovery**: Finds Bitcoin-related markets on Polymarket
4. **Trade Execution**: Immediately buys the bullish outcome on Polymarket markets

## Setup

### Prerequisites

```bash
pip install ccxt py-clob-client requests python-dotenv
```

### Configuration

Edit `config.py`:

```python
# Binance symbol to monitor
BINANCE_SYMBOL = "BTC/USDT"

# Pump threshold
PUMP_THRESHOLD_PERCENT = 4.5  # 4.5% pump in 1 minute

# Polymarket API credentials (from .env)
POLY_API_KEY = os.getenv("POLY_API_KEY")
POLY_API_SECRET = os.getenv("POLY_API_SECRET")
POLY_PASSPHRASE = os.getenv("POLY_PASSPHRASE")

# Trading parameters
MAX_TRADE_SIZE_USDC = 100.0
SIMULATION_MODE = True  # Set to False for live trading
```

### Environment Variables

Create a `.env` file:

```
POLY_API_KEY=your_api_key
POLY_API_SECRET=your_api_secret
POLY_PASSPHRASE=your_passphrase
POLY_PRIVATE_KEY=your_private_key
```

## Usage

### Simulation Mode (Default)

```bash
cd src/PolyMarket_Binance_Arbitrage
python main.py
```

### Live Trading Mode

1. Set `SIMULATION_MODE = False` in `config.py`
2. Ensure you have sufficient USDC balance
3. Run: `python main.py`

## Files

- `config.py` - Configuration settings
- `binance_feed.py` - Binance price monitoring and pump detection
- `polymarket_discovery.py` - Finds Bitcoin-related markets on Polymarket
- `strategy.py` - Main strategy logic
- `execution.py` - Trade execution on Polymarket
- `main.py` - Main orchestration

## Strategy Details

### Pump Detection
- Monitors Binance price every 1 second
- Calculates price change over 60-second window
- Triggers when change >= 4.5%

### Market Selection
- Searches Polymarket for markets containing Bitcoin keywords
- Filters by:
  - Active markets only
  - Minimum liquidity ($1000)
  - Binary outcomes (2 outcomes)
  - Future end dates

### Trade Execution
- Buys the "YES" outcome (bullish) when pump detected
- Respects cooldown periods (5 minutes between trades on same market)
- Limits position size per market
- Logs all trades to CSV

## Risk Management

- **Cooldown**: 5 minutes between trades on same market
- **Max Trade Size**: $100 per opportunity
- **Position Limits**: 1 position per market
- **Simulation Mode**: Test strategy without real money

## Logging

Logs are saved to:
```
src/PolyMarket_Binance_Arbitrage/logs/binance_polymarket_YYYYMMDD_HHMMSS.log
```

Trade logs (simulation mode) are saved to:
```
binance_polymarket_trades.csv
```

## Notes

- This strategy exploits market inefficiencies and lag
- Works best during high volatility periods
- Requires fast execution (10-30 second window)
- Test thoroughly in simulation mode before live trading
