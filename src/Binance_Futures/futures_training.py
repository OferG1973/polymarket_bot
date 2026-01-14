import pandas as pd
import xgboost as xgb
import argparse
import numpy as np
import os
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

INPUT_FILE = f"futures_data_{args.asset}.csv"
MODEL_PREFIX = f"futures_ensemble_{args.asset}_" # Saves as futures_ensemble_BTC_0.json
NUM_MODELS = 5

def train():
    print(f"🧠 Training 6H Ensemble for {args.asset}...")
    if not os.path.exists(INPUT_FILE):
        print("❌ CSV not found. Run pipeline first.")
        return

    df = pd.read_csv(INPUT_FILE)
    
    # Ensure Time Order
    # (Assuming pipeline saved chronological, but strictly enforcing here won't hurt)
    # df = df.sort_index() 

    features = ['rsi', 'trend_signal', 'volatility', 'momentum_24h', 'qqq_mom']
    target = 'target'
    
    X = df[features]
    y = df[target]
    
    # Class Weight
    pos = (y == 1).sum()
    neg = (y == 0).sum()
    scale = neg / pos if pos > 0 else 1.0
    print(f"⚖️  Wins: {pos} | Flat/Loss: {neg} | Weight: {scale:.2f}")

    # --- 1. WALK-FORWARD VALIDATION (The "Lab" Test) ---
    print("\n🔬 Running Walk-Forward Validation (Sanity Check)...")
    tscv = TimeSeriesSplit(n_splits=5)
    
    # Temporary model for testing
    test_model = xgb.XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.05, scale_pos_weight=scale)
    
    scores = []
    for train_index, test_index in tscv.split(X):
        X_tr, X_te = X.iloc[train_index], X.iloc[test_index]
        y_tr, y_te = y.iloc[train_index], y.iloc[test_index]
        
        test_model.fit(X_tr, y_tr)
        preds = test_model.predict_proba(X_te)[:, 1]
        try:
            auc = roc_auc_score(y_te, preds)
            scores.append(auc)
            print(f"   Fold AUC: {auc:.4f}")
        except: pass
        
    print(f"🏆 Average WFV AUC: {np.mean(scores):.4f}")

    # --- 2. TRAIN FINAL ENSEMBLE (The "Factory" Build) ---
    print(f"\n🏃 Training {NUM_MODELS} Production Models...")
    
    for i in range(NUM_MODELS):
        seed = 42 + i
        # We vary subsample slightly to ensure diversity among models
        clf = xgb.XGBClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=5,
            subsample=0.75,       # Randomly select 75% of data per tree (Bagging)
            colsample_bytree=0.8,
            scale_pos_weight=scale,
            objective='binary:logistic',
            eval_metric='logloss',
            random_state=seed
        )
        
        clf.fit(X, y)
        filename = f"{MODEL_PREFIX}{i}.json"
        clf.save_model(filename)
        print(f"   ✅ Saved {filename}")

if __name__ == "__main__":
    train()