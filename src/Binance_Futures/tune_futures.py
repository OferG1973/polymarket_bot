import pandas as pd
import xgboost as xgb
import argparse
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV

parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

def tune():
    print(f"🔧 Tuning 6H Model for {args.asset}...")
    df = pd.read_csv(f"futures_data_{args.asset}.csv")
    
    features = ['rsi', 'trend_signal', 'volatility', 'momentum_24h', 'qqq_mom']
    X = df[features]
    y = df['target']
    
    param_grid = {
        'max_depth': [3, 5, 7],
        'learning_rate': [0.01, 0.05, 0.1],
        'n_estimators': [200, 400],
        'subsample': [0.7, 1.0]
    }
    
    xgb_model = xgb.XGBClassifier(
        objective='binary:logistic',
        eval_metric='logloss',
        scale_pos_weight=(y==0).sum()/(y==1).sum()
    )
    
    grid = GridSearchCV(xgb_model, param_grid, cv=TimeSeriesSplit(n_splits=3), scoring='roc_auc', n_jobs=1)
    grid.fit(X, y)
    
    print(f"🏆 Best AUC: {grid.best_score_:.4f}")
    print(f"✅ Params: {grid.best_params_}")

if __name__ == "__main__":
    tune()