import boto3
import json
import re
import csv
import os
import requests
from datetime import datetime

# --- CONFIG ---
DATA_DIR = os.path.join("src", "Polymarket")
POLYMARKETS_TO_IGNORE_FILE = os.path.join(DATA_DIR, "polymarkets_to_ignore.csv")
LOCAL_LLM_URL = "http://localhost:11434/api/generate"
LOCAL_MODEL_NAME = "qwen2.5:14b"

class MarketParser:
    def __init__(self, region_name="us-east-1"):
        # AWS Setup
        self.bedrock = boto3.client(service_name='bedrock-runtime', region_name=region_name)
        self.bedrock_model_id = "anthropic.claude-3-haiku-20240307-v1:0"
        
        # Logging
        self.log_file = "llm_calls.csv"
        self._init_log()

    def _init_log(self):
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(["Timestamp", "Question", "Source", "Response", "Status"])

    def _log_call(self, question, source, response, status):
        try:
            with open(self.log_file, 'a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    question, source, json.dumps(response), status
                ])
        except: pass

    def has_asset_keyword(self, question):
        """
        Simple Regex: Only checks if the asset exists in the text.
        """
        q = question.lower()
        if "bitcoin" in q or "btc" in q: return "BTC"
        if "ethereum" in q or "eth" in q: return "ETH"
        if "solana" in q or "sol" in q: return "SOL"
        return None

    def check_ignore_list(self, question):
        """Checks if question is in the local ignore CSV."""
        try:
            if os.path.exists(POLYMARKETS_TO_IGNORE_FILE):
                with open(POLYMARKETS_TO_IGNORE_FILE, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if row and row[0].strip() == question.strip():
                            return True
        except: pass
        return False

    def add_to_ignore_list(self, question):
        """Adds bad questions to ignore list."""
        try:
            if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
            with open(POLYMARKETS_TO_IGNORE_FILE, 'a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([question])
        except: pass

    def _construct_prompt(self, question):
        return f"""
        Analyze this prediction market question: "{question}"

        Task: Extract data ONLY if it relates to the price of Bitcoin (BTC), Ethereum (ETH), or Solana (SOL).
        
        Rules:
        1. "asset": Must be BTC, ETH, or SOL.
        2. "target_price": Must be a specific float number (e.g. 95000.0).
           - If question says "Up or Down", return string "CURRENT_PRICE".
        3. "direction": 
           - 1 for Bullish (Above, Greater, High, Up, Hit, Touch)
           - -1 for Bearish (Below, Less, Low, Down)
           - 0 for Range (Between, Inside)
        
        Output format: JSON ONLY. No markdown, no explanations.
        If NO valid crypto price prediction found, return: {{"error": "No data found"}}

        Example JSON:
        {{"asset": "BTC", "target_price": 95000.0, "direction": 1}}
        """

    def _call_local_llm(self, question):
        """
        Calls local Qwen model via Ollama.
        """
        print(f"   💻 [LOCAL Qwen] Analyzing...")
        payload = {
            "model": LOCAL_MODEL_NAME,
            "prompt": self._construct_prompt(question),
            "stream": False,
            "format": "json", # Enforce JSON mode
            "options": {"temperature": 0.1} # Low temp for precision
        }
        
        try:
            resp = requests.post(LOCAL_LLM_URL, json=payload, timeout=10) # 10s timeout
            if resp.status_code == 200:
                response_json = resp.json()
                raw_text = response_json.get("response", "")
                data = json.loads(raw_text)
                
                # Check for explicit error from LLM
                if "error" in data: return "IGNORE"
                
                # Validate Fields
                if "asset" in data and "target_price" in data:
                    self._log_call(question, "Local-Qwen", data, "SUCCESS")
                    return data
            
            return None # Malformed response
            
        except requests.exceptions.ConnectionError:
            print("      ⚠️ Local LLM offline. Switching to Bedrock.")
            return None
        except Exception as e:
            print(f"      ⚠️ Local LLM Error: {e}")
            return None

    def _call_bedrock(self, question):
        """
        Fallback: Calls AWS Bedrock (Claude).
        """
        print(f"   ☁️ [AWS Bedrock] Fallback Analyzing...")
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": self._construct_prompt(question)}]
        })

        try:
            resp = self.bedrock.invoke_model(body=body, modelId=self.bedrock_model_id)
            txt = json.loads(resp['body'].read())['content'][0]['text']
            
            # Find JSON in text
            j_start, j_end = txt.find('{'), txt.rfind('}') + 1
            if j_start == -1: return None
            
            data = json.loads(txt[j_start:j_end])
            
            if "error" in data: return "IGNORE"
            
            self._log_call(question, "AWS-Bedrock", data, "SUCCESS")
            return data
            
        except Exception as e:
            self._log_call(question, "AWS-Bedrock", str(e), "ERROR")
            return None

    def parse_question(self, question):
        # 1. Quick Keyword Filter (Regex)
        # If the word 'Bitcoin' isn't even in the string, don't waste compute.
        if not self.has_asset_keyword(question):
            return None

        # 2. Check Ignore List
        if self.check_ignore_list(question):
            return None

        # 3. Try Local LLM (Qwen)
        result = self._call_local_llm(question)
        
        # 4. Handle Local Result
        if result == "IGNORE":
            self.add_to_ignore_list(question)
            return None
        if result is not None:
            # Default direction if missing
            if 'direction' not in result: result['direction'] = 1
            return result

        # 5. Fallback to AWS Bedrock
        result = self._call_bedrock(question)
        
        if result == "IGNORE":
            self.add_to_ignore_list(question)
            return None
        if result is not None:
            if 'direction' not in result: result['direction'] = 1
            return result

        return None