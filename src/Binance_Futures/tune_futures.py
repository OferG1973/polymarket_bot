import pandas as pd
import xgboost as xgb
import argparse
import os
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV

parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

# --- PATH CONFIG ---
DATA_DIR = os.path.join("src", "Binance_Futures")
INPUT_FILE = os.path.join(DATA_DIR, f"futures_data_{args.asset}.csv")

def tune():
    print(f"🔧 Tuning Futures Model for {args.asset}...")
    if not os.path.exists(INPUT_FILE):
        print(f"❌ File not found: {INPUT_FILE}")
        return

    df = pd.read_csv(INPUT_FILE)
    
    features = ['rsi', 'trend_signal', 'volatility', 'momentum_24h', 'qqq_mom']
    X = df[features]
    y = df['target']
    
    param_grid = {
        'max_depth': [3, 5],
        'learning_rate': [0.01, 0.05],
        'n_estimators': [200, 300]
    }
    
    xgb_model = xgb.XGBClassifier(
        objective='multi:softprob',
        num_class=3,
        eval_metric='mlogloss'
    )
    
    grid = GridSearchCV(xgb_model, param_grid, cv=TimeSeriesSplit(n_splits=3), scoring='accuracy', n_jobs=1)
    grid.fit(X, y)
    
    print(f"🏆 Best Accuracy: {grid.best_score_:.4f}")
    print(f"✅ Params: {grid.best_params_}")

if __name__ == "__main__":
    tune()