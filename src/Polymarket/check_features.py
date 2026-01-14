import xgboost as xgb
import argparse
import pandas as pd
import os

# --- SETUP ---
parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC")
args = parser.parse_args()

def check_importance():
    filename = f"model_{args.asset}_0.json"
    
    print(f"🔍 Looking for model file: {filename}")
    
    # 1. Verify File Exists
    if not os.path.exists(filename):
        print(f"❌ Error: File '{filename}' not found in current directory.")
        print(f"   Current Directory: {os.getcwd()}")
        return

    # 2. Load Model
    model = xgb.XGBClassifier()
    try:
        model.load_model(filename)
        print("✅ Model loaded successfully.")
    except Exception as e:
        print(f"❌ Error loading model JSON: {e}")
        return
    
    # 3. Get Features
    # Note: These MUST match the order in professional_model.py exactly
    features = ['moneyness', 'days_left', 'vol', 'rsi', 'trend', 'btc_mom', 'qqq_mom']
    
    try:
        importance = model.feature_importances_
    except AttributeError:
        print("❌ Model has no feature importances. Was it trained?")
        return

    # 4. Sort and Print
    feat_imp = list(zip(features, importance))
    feat_imp.sort(key=lambda x: x[1], reverse=True)
    
    print(f"\n🧠 Feature Importance for {args.asset}:")
    print("-" * 35)
    print(f"{'FEATURE':<15} | {'IMPORTANCE':<10}")
    print("-" * 35)
    
    for name, score in feat_imp:
        bar = "█" * int(score * 50) # Visual bar
        print(f"{name:<15} | {score:.4f}  {bar}")

if __name__ == "__main__":
    check_importance()