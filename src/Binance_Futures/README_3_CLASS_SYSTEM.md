# 3-Class Classification System for Binance Futures Trading

## Overview

This system trains and predicts **3 classes** for cryptocurrency price movements **6 hours into the future**:

1. **NEUTRAL (Class 0)**: Price stays relatively flat (uncertainty/consolidation)
2. **LONG (Class 1)**: Price goes **UP** significantly
3. **SHORT (Class 2)**: Price goes **DOWN** significantly

---

## How It Works

### 1. Data Pipeline (`futures_pipeline.py`)

**Label Creation Logic:**
- Looks **6 hours forward** (`LOOKAHEAD_HOURS = 6`)
- Calculates future return: `(future_price - current_price) / current_price`
- **Class 0 (NEUTRAL)**: `-TARGET_PCT <= future_return <= TARGET_PCT`
  - Price moves less than 0.8% (stays flat/uncertain)
- **Class 1 (LONG)**: `future_return > TARGET_PCT`
  - Price increases by more than 0.8%
- **Class 2 (SHORT)**: `future_return < -TARGET_PCT`
  - Price decreases by more than 0.8%

**Target Threshold:** `TARGET_PCT = 0.008` (0.8% price move)

**Features Used:**
- `rsi`: Relative Strength Index (14-period)
- `trend_signal`: Price vs 50-period SMA
- `volatility`: 24-hour rolling standard deviation
- `momentum_24h`: 24-hour price change
- `qqq_mom`: Nasdaq QQQ 24-hour momentum (macro indicator)

---

### 2. Model Training (`futures_training.py`)

**Model Configuration:**
- **Algorithm**: XGBoost Classifier
- **Objective**: `multi:softprob` (multi-class classification)
- **Number of Classes**: `num_class=3`
- **Ensemble**: 5 models with different random seeds (averaged predictions)
- **Output**: Probability distribution over [Neutral, Long, Short]

**Training Output:**
- Saves 5 model files: `futures_ensemble_{ASSET}_0.json` through `futures_ensemble_{ASSET}_4.json`
- Reports accuracy and class-wise performance metrics

---

### 3. Live Trading (`futures_sandbox.py`)

**Prediction Process:**
1. Loads all 5 trained models
2. Gets current market features (RSI, trend, volatility, momentum, QQQ)
3. Gets probability predictions from each model
4. Averages probabilities: `[prob_neutral, prob_long, prob_short]`
5. Makes trading decision based on confidence thresholds

**Trading Logic:**
- **LONG Entry**: `prob_long > ENTRY_CONFIDENCE` (60%) AND `prob_neutral <= 0.50`
- **SHORT Entry**: `prob_short > ENTRY_CONFIDENCE` (60%) AND `prob_neutral <= 0.50`
- **No Trade**: If neutral probability is too high (uncertainty) OR both long/short probabilities are too low

**Uncertainty Filter:**
- If `prob_neutral > 50%`, the model is uncertain about direction
- Bot avoids trading during high uncertainty periods
- This prevents losses from trading when the model predicts "flat/uncertain"

**Logging:**
- Shows all 3 probabilities: `Neutral: X% | Long: Y% | Short: Z%`
- Shows predicted class: `NEUTRAL (flat)`, `LONG (up)`, or `SHORT (down)`
- Explains why trades are or aren't taken

---

## Example Output

### Training Phase:
```
📊 Dataset: 17520 rows
   Neutral (0): 12450
   Longs   (1): 2535
   Shorts  (2): 2535

🏆 Ensemble Accuracy: 45.23%

📊 Classification Report:
              precision    recall  f1-score   support
Neutral (0)       0.52      0.68      0.59      2490
Long (1)          0.38      0.22      0.28       507
Short (2)         0.38      0.22      0.28       507
```

### Live Trading Phase:
```
🔍 SCAN | 43250.50 | Neutral: 45.2% | Long: 35.1% (>60.0%) | Short: 19.7% (>60.0%) | 14:30:15
      📊 Prediction: NEUTRAL (flat) (6-hour forecast)
      ℹ️  Based on 5x leverage, the bot is waiting for >60.0% probability that BTC price will move by 0.80% (increase (Long) to 43596.10 or decrease (Short) to 42904.90) within the next 6 hours
⏸️  NO TRADE: Low confidence (Long: 35.1%, Short: 19.7% both < 60.0%)
```

---

## Key Configuration Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `LOOKAHEAD_HOURS` | 6 | Prediction horizon (6 hours forward) |
| `TARGET_PCT` | 0.008 | Minimum price move threshold (0.8%) |
| `ENTRY_CONFIDENCE` | 0.60 | Minimum probability to enter trade (60%) |
| `MAX_NEUTRAL_PROB` | 0.50 | Maximum neutral probability to allow trading (50%) |
| `LEVERAGE` | 5 | Trading leverage multiplier |
| `NUM_MODELS` | 5 | Number of ensemble models |

---

## Workflow

1. **Data Collection**: Run `futures_pipeline.py --asset BTC`
   - Fetches historical data from Binance
   - Creates labels for 3 classes (6-hour forward)
   - Saves to `futures_data_{ASSET}.csv`

2. **Model Training**: Run `futures_training.py --asset BTC`
   - Trains 5 XGBoost models
   - Saves models to `futures_ensemble_{ASSET}_{0-4}.json`
   - Reports accuracy and class-wise metrics

3. **Live Trading**: Run `futures_sandbox.py --asset BTC`
   - Loads trained models
   - Gets real-time features
   - Makes predictions for all 3 classes
   - Enters trades only when confidence is high AND uncertainty is low

---

## Verification Checklist

✅ **Pipeline**: Creates 3 classes (0=Neutral, 1=Long, 2=Short) based on 6-hour forward returns  
✅ **Training**: Trains XGBoost with `num_class=3` and `objective='multi:softprob'`  
✅ **Prediction**: Extracts all 3 probabilities `[prob_neutral, prob_long, prob_short]`  
✅ **Logging**: Shows all 3 probabilities and predicted class  
✅ **Trading**: Uses uncertainty filter (avoids trading when neutral prob > 50%)  
✅ **Documentation**: Clear comments explaining class meanings

---

## Notes

- The system predicts **6 hours forward**, not instant price movements
- NEUTRAL class represents **uncertainty/consolidation** periods
- High neutral probability = model is uncertain → bot avoids trading
- The 0.8% threshold (`TARGET_PCT`) is designed for 5x leverage (0.8% move × 5x = 4% profit)
