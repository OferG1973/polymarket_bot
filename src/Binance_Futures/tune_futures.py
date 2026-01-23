import pandas as pd
import xgboost as xgb
import argparse
import os
import numpy as np
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.metrics import classification_report, accuracy_score

parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

# --- PATH CONFIG ---
DATA_DIR = os.path.join("src", "Binance_Futures")
INPUT_FILE = os.path.join(DATA_DIR, f"futures_data_{args.asset}.csv")

def tune():
    print(f"🔧 Tuning Futures Model for {args.asset} (3-Class: Neutral, Long, Short)...")
    if not os.path.exists(INPUT_FILE):
        print(f"❌ File not found: {INPUT_FILE}")
        return

    df = pd.read_csv(INPUT_FILE)
    
    features = ['rsi', 'trend_signal', 'volatility', 'momentum_24h', 'qqq_mom']
    X = df[features]
    y = df['target']
    
    # Verify 3-class setup
    unique_classes = np.unique(y)
    print(f"✅ Dataset: {len(df)} samples")
    print(f"✅ Classes found: {unique_classes} (0=Neutral, 1=Long, 2=Short)")
    for cls in [0, 1, 2]:
        count = (y == cls).sum()
        pct = count / len(y) * 100
        class_name = ['Neutral', 'Long', 'Short'][cls]
        print(f"   {class_name} (class {cls}): {count} samples ({pct:.1f}%)")
    
    param_grid = {
        'max_depth': [3, 5],
        'learning_rate': [0.01, 0.05],
        'n_estimators': [200, 300]
    }
    
    xgb_model = xgb.XGBClassifier(
        objective='multi:softprob',
        num_class=3,  # 3-class classification: Neutral, Long, Short
        eval_metric='mlogloss',
        subsample=1.0,
        colsample_bytree=0.8
    )
    
    print(f"\n🔍 Running GridSearchCV with TimeSeriesSplit (3 folds)...")
    grid = GridSearchCV(
        xgb_model, 
        param_grid, 
        cv=TimeSeriesSplit(n_splits=3), 
        scoring='accuracy', 
        n_jobs=1,
        verbose=1
    )
    grid.fit(X, y)
    
    print(f"\n🏆 Best Cross-Validation Accuracy: {grid.best_score_:.4f} ({grid.best_score_*100:.2f}%)")
    print(f"✅ Best Parameters: {grid.best_params_}")
    
    # Evaluate best model on full dataset with classification report
    print(f"\n📊 Classification Report (using best model on full dataset):")
    best_model = grid.best_estimator_
    y_pred = best_model.predict(X)
    print(classification_report(y, y_pred, 
                                target_names=['Neutral (0)', 'Long (1)', 'Short (2)']))
    
    # Show feature importance
    print(f"\n📈 Top Feature Importances:")
    feature_importance = pd.DataFrame({
        'feature': features,
        'importance': best_model.feature_importances_
    }).sort_values('importance', ascending=False)
    for idx, row in feature_importance.iterrows():
        print(f"   {row['feature']}: {row['importance']:.4f}")

if __name__ == "__main__":
    tune()