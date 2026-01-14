import boto3
import json
import requests
import pandas as pd
import yfinance as yf

def test_bedrock():
    print("\n--- TEST 1: AWS Bedrock Connection ---")
    try:
        bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')
        model_id = "anthropic.claude-3-haiku-20240307-v1:0"
        
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 50,
            "messages": [{"role": "user", "content": "Reply with only the word 'Success'."}]
        }
        
        response = bedrock.invoke_model(
            body=json.dumps(payload), 
            modelId=model_id,
            accept='application/json', 
            contentType='application/json'
        )
        result = json.loads(response.get('body').read())
        print(f"✅ Bedrock Response: {result['content'][0]['text']}")
        return True
    except Exception as e:
        print(f"❌ Bedrock Failed: {e}")
        print("   -> Tip: Go to AWS Console > Bedrock > Model access, and request access for Claude 3 Haiku.")
        return False

def test_api_and_data():
    print("\n--- TEST 2: Polymarket API & Data Alignment ---")
    
    # Check Crypto Data Date Range
    df = yf.download("BTC-USD", period="5d", interval="1h", progress=False)
    if not df.empty:
        # handle tz-naive vs aware
        last_date = df.index[-1]
        print(f"✅ Yahoo Finance Data Latest: {last_date}")
    else:
        print("❌ Yahoo Finance Failed to download data.")

    # Check Polymarket Data
    url = "https://gamma-api.polymarket.com/markets"
    # We remove the tag_id to see EVERYTHING, and filter strictly by text
    params = {
        "closed": "true",
        "limit": 10,
        "offset": 0,
        "order": "startDate", 
        "ascending": "false" 
    }
    
    try:
        r = requests.get(url, params=params)
        markets = r.json()
        print(f"✅ Polymarket API returned {len(markets)} markets.")
        
        btc_found = False
        print("\n--- Sample Markets (First 5) ---")
        for i, m in enumerate(markets[:5]):
            print(f"[{i}] {m['question']}")
            if "Bitcoin" in m['question'] or "BTC" in m['question']:
                btc_found = True
                
        if not btc_found:
            print("\n⚠️ WARNING: No Bitcoin markets found in the first 10 results.")
            print("   -> The script filters for 'Bitcoin', so it skipped these.")
        else:
            print("\n✅ found Bitcoin markets in the sample.")
            
    except Exception as e:
        print(f"❌ Polymarket API Failed: {e}")

if __name__ == "__main__":
    if test_bedrock():
        test_api_and_data()