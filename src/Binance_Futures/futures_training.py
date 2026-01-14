import pandas as pd
import xgboost as xgb
import argparse
import numpy as np
import os
import sys
from sklearn.metrics import accuracy_score
from sklearn.model_selection import TimeSeriesSplit

parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

# --- PATH CONFIGURATION ---
DATA_DIR = os.path.join("src", "Binance_Futures")
INPUT_FILE = os.path.join(DATA_DIR, f"futures_data_{args.asset}.csv")
MODEL_PREFIX = os.path.join(DATA_DIR, f"futures_ensemble_{args.asset}_")
NUM_MODELS = 5

def train():
    print(f"🧠 Training Multi-Class Ensemble for {args.asset}...")
    print(f"📂 Reading from: {INPUT_FILE}")
    
    if not os.path.exists(INPUT_FILE):
        print("❌ CSV not found. Run futures_pipeline.py first.")
        return

    df = pd.read_csv(INPUT_FILE)
    
    features = ['rsi', 'trend_signal', 'volatility', 'momentum_24h', 'qqq_mom']
    target = 'target'
    
    X = df[features]
    y = df[target]
    
    # --- TRAIN ENSEMBLE ---
    print(f"\n🏃 Training {NUM_MODELS} Models (0=Neutral, 1=Long, 2=Short)...")
    
    for i in range(NUM_MODELS):
        seed = 42 + i
        
        # Multi-class Configuration
        clf = xgb.XGBClassifier(
            n_estimators=200,       # Tuned
            learning_rate=0.01,     # Tuned
            max_depth=3,            # Tuned
            subsample=1.0,          # Tuned
            colsample_bytree=0.8,
            objective='multi:softprob',
            num_class=3,                
            eval_metric='mlogloss',
            random_state=seed
        )
        
        clf.fit(X, y)
        filename = f"{MODEL_PREFIX}{i}.json"
        clf.save_model(filename)
        print(f"   ✅ Saved {filename}")

    # Validation
    split = int(len(X) * 0.8)
    X_test = X.iloc[split:]
    y_test = y.iloc[split:]
    
    # Average Predictions
    avg_preds = np.zeros((len(X_test), 3))
    for i in range(NUM_MODELS):
        m = xgb.XGBClassifier()
        m.load_model(f"{MODEL_PREFIX}{i}.json")
        avg_preds += m.predict_proba(X_test)
    
    avg_preds /= NUM_MODELS
    final_pred_classes = np.argmax(avg_preds, axis=1)
    
    acc = accuracy_score(y_test, final_pred_classes)
    print(f"\n🏆 Ensemble Accuracy: {acc:.2%}")

if __name__ == "__main__":
    train()