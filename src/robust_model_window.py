import pandas as pd
import xgboost as xgb
import numpy as np
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, roc_auc_score

def train_walk_forward_model():
    print("⏳ Loading Data for Time-Series Training...")
    try:
        df = pd.read_csv("advanced_training_data.csv")
    except:
        print("Run the pipeline first!")
        return

    # --- 1. CRITICAL: SORT BY DATE ---
    # We must respect the arrow of time. 
    # Since we didn't save dates in the CSV, we assume the pipeline 
    # scraped them in order. But to be safe, let's just reverse the index
    # if the scraper saved Newest -> Oldest. 
    # (Assuming scraper saved Newest at top, we flip it).
    df = df.iloc[::-1].reset_index(drop=True)

    X = df[['log_distance', 'days_left', 'start_vol']]
    y = df['outcome']

    # --- 2. SETUP TIME-SERIES SPLIT ---
    # We use 5 splits. This creates 5 "windows" moving forward in time.
    tscv = TimeSeriesSplit(n_splits=5)
    
    model = xgb.XGBClassifier(
        n_estimators=200,
        learning_rate=0.03,
        max_depth=4,
        # We calculate imbalance dynamically inside the loop
        objective='binary:logistic',
        eval_metric='logloss'
    )

    print(f"🏃 Starting Walk-Forward Validation (5 Windows)...")
    
    fold_aucs = []
    fold_losses = []

    # --- 3. THE WALK-FORWARD LOOP ---
    for fold, (train_index, test_index) in enumerate(tscv.split(X)):
        # Split data based on time indices
        X_train, X_test = X.iloc[train_index], X.iloc[test_index]
        y_train, y_test = y.iloc[train_index], y.iloc[test_index]

        # Dynamic Class Imbalance Calculation (Per Window)
        # As time passes, the ratio of Yes/No might change!
        num_neg = (y_train == 0).sum()
        num_pos = (y_train == 1).sum()
        if num_pos == 0: scale_weight = 1 # Avoid div/0
        else: scale_weight = num_neg / num_pos
        
        # Update model parameters for this fold
        model.set_params(scale_pos_weight=scale_weight)

        # Train
        model.fit(X_train, y_train)

        # Evaluate
        preds = model.predict_proba(X_test)[:, 1]
        
        # Check if we have both classes in test set (rare edge case)
        if len(np.unique(y_test)) < 2:
            continue 

        score_auc = roc_auc_score(y_test, preds)
        score_loss = log_loss(y_test, preds)
        
        fold_aucs.append(score_auc)
        fold_losses.append(score_loss)
        
        print(f"   🗓️ Window {fold+1}: Train size {len(X_train)} -> Test size {len(X_test)}")
        print(f"      AUC: {score_auc:.4f} | LogLoss: {score_loss:.4f}")

    # --- 4. FINAL RESULTS ---
    print("\n📊 Walk-Forward Results:")
    print(f"   Avg AUC: {np.mean(fold_aucs):.4f}")
    print(f"   Avg LogLoss: {np.mean(fold_losses):.4f}")

    # --- 5. TRAIN FINAL MODEL ---
    # Now we train on ALL available past data to be ready for tomorrow.
    full_neg = (y == 0).sum()
    full_pos = (y == 1).sum()
    final_weight = full_neg / full_pos

    model.set_params(scale_pos_weight=final_weight)
    model.fit(X, y)
    
    model.save_model("polymarket_btc_v2.json")
    print("💾 Final Time-Aware Model Saved.")

if __name__ == "__main__":
    train_walk_forward_model()