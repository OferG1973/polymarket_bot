import pandas as pd
import xgboost as xgb
import numpy as np
import argparse
import os
import requests
from sklearn.metrics import roc_auc_score

# --- INITIALIZE SYSTEM ---

# AWS credentials should be set via environment variables or AWS credentials file
# Set these in your environment or use: export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
# Or use AWS credentials file at ~/.aws/credentials
if not os.environ.get("AWS_ACCESS_KEY_ID"):
    raise ValueError("AWS_ACCESS_KEY_ID environment variable not set. Please set it before running.")
if not os.environ.get("AWS_SECRET_ACCESS_KEY"):
    raise ValueError("AWS_SECRET_ACCESS_KEY environment variable not set. Please set it before running.")
if not os.environ.get("AWS_DEFAULT_REGION"):
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
#SET Ollama model for local LLM
import subprocess

# Run Ollama Qwen 2.5:14b model for local LLM
def ensure_model_running(model_name="qwen2.5:14b", host="http://localhost:11434"):
    try:
        # 1. Check currently loaded models
        response = requests.get(f"{host}/api/ps")
        response.raise_for_status()
        
        running_models = [m['name'] for m in response.json().get('models', [])]
        
        # Ollama sometimes returns names like 'qwen2.5:14b-instruct', so we check if our string is in there
        if any(model_name in running for running in running_models):
            print(f"✅ Model '{model_name}' is already running.")
            return True
        
        # 2. If not running, trigger a load
        print(f"⏳ Model '{model_name}' not loaded. Initializing...")
        
        # We send an empty prompt with keep_alive to force it into VRAM
        # keep_alive: -1 keeps it running indefinitely, or use "5m" for 5 minutes
        requests.post(f"{host}/api/generate", json={
            "model": model_name, 
            "prompt": "", 
            "keep_alive": "5m" 
        })
        
        print(f"🚀 Model '{model_name}' has been started.")
        return True

    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to Ollama. Is the Ollama app/service running?")
        return False
    except Exception as e:
        print(f"❌ An error occurred: {e}")
        return False

ensure_model_running("qwen2.5:14b")

# --- ARGUMENTS ---
parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC", choices=["BTC", "ETH", "SOL"])
args = parser.parse_args()

ASSET = args.asset
INPUT_FILE = f"data_{ASSET}.csv"
DATA_DIR = os.path.join("src", "Polymarket")
MODEL_PREFIX = os.path.join(DATA_DIR, f"model_{ASSET}_")# e.g. src/Polymarket/model_ETH_
NUM_MODELS = 5

def train_ensemble():
    print(f"🧠 Training Ensemble for: {ASSET}")
    
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Error: {INPUT_FILE} not found. Run strict_pipeline.py --asset {ASSET} first.")
        return

    df = pd.read_csv(INPUT_FILE)
    df = df.iloc[::-1].reset_index(drop=True) # Sort Date

    # Features (Must match pipeline)
    features = ['moneyness', 'days_left', 'vol', 'rsi', 'trend', 'btc_mom', 'qqq_mom']
    target = 'outcome'

    X = df[features]
    y = df[target]
    
    # Class Weight
    pos = (y == 1).sum()
    neg = (y == 0).sum()
    scale_weight = neg / pos if pos > 0 else 1.0
    print(f"⚖️ Class Weight: {scale_weight:.2f}")

    print(f"🏃 Training {NUM_MODELS} Models...")
    
    for i in range(NUM_MODELS):
        seed = 42 + i
        #depth = 3 if i % 2 == 0 else 5 
        depth = 4
        clf = xgb.XGBClassifier(
            n_estimators=300, 
            learning_rate=0.1, 
            max_depth=depth,
            subsample=1.0, 
            colsample_bytree=1.0,
            scale_pos_weight=scale_weight,
            objective='binary:logistic', 
            eval_metric='logloss',
            random_state=seed
        )
        
        clf.fit(X, y)
        filename = f"{MODEL_PREFIX}{i}.json"
        clf.save_model(filename)
        print(f"   ✅ Saved {filename}")

    # Quick Validation
    split = int(len(X) * 0.8)
    X_test = X.iloc[split:]
    y_test = y.iloc[split:]
    
    avg_preds = np.zeros(len(X_test))
    for i in range(NUM_MODELS):
        m = xgb.XGBClassifier()
        m.load_model(f"{MODEL_PREFIX}{i}.json")
        avg_preds += m.predict_proba(X_test)[:, 1]
    
    avg_preds /= NUM_MODELS
    try:
        auc = roc_auc_score(y_test, avg_preds)
        print(f"\n🏆 Ensemble AUC: {auc:.4f}")
    except:
        print("\n⚠️ Not enough test data to calc AUC.")

if __name__ == "__main__":
    train_ensemble()