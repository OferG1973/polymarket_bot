import pandas as pd
import xgboost as xgb
import argparse
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV

parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

INPUT_FILE = f"data_{args.asset}.csv"

def tune():
    print(f"🔧 Tuning Hyperparameters for {args.asset}...")
    df = pd.read_csv(INPUT_FILE)
    df = df.iloc[::-1].reset_index(drop=True)

    features = ['moneyness', 'days_left', 'vol', 'rsi', 'trend', 'btc_mom', 'qqq_mom']
    X = df[features]
    y = df['outcome']

    # Define the "Grid" of possibilities
    param_grid = {
        'max_depth': [3, 4, 5, 6],
        'learning_rate': [0.01, 0.02, 0.05, 0.1],
        'n_estimators': [100, 200, 300],
        'subsample': [0.6, 0.8, 1.0],
        'colsample_bytree': [0.6, 0.8, 1.0]
    }

    # XGBoost Classifier
    xgb_model = xgb.XGBClassifier(
        objective='binary:logistic',
        eval_metric='logloss',
        scale_pos_weight=(y==0).sum()/(y==1).sum()
    )

    # Walk-Forward Validation (3 Splits)
    tscv = TimeSeriesSplit(n_splits=3)

    grid_search = GridSearchCV(
        estimator=xgb_model,
        param_grid=param_grid,
        scoring='roc_auc',
        cv=tscv,
        verbose=1,
        n_jobs=-1 # Use all CPU cores
    )

    print("⏳ Running Grid Search (this may take 5-10 mins)...")
    grid_search.fit(X, y)

    print(f"\n🏆 Best AUC: {grid_search.best_score_:.4f}")
    print("✅ Best Parameters:")
    print(grid_search.best_params_)

if __name__ == "__main__":
    tune()