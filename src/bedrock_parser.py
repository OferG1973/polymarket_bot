import boto3
import json
import re
import csv
import os
from datetime import datetime

class MarketParser:
    def __init__(self, region_name="us-east-1"):
        self.bedrock = boto3.client(service_name='bedrock-runtime', region_name=region_name)
        self.model_id = "anthropic.claude-3-haiku-20240307-v1:0"
        self.log_file = "llm_calls.csv"
        self._init_log()

    def _init_log(self):
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(["Timestamp", "Question", "AI_Response", "Status"])

    def _log_call(self, question, response, status):
        try:
            with open(self.log_file, 'a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    question, json.dumps(response), status
                ])
        except: pass

    def _parse_val(self, val_str, suffix=''):
        try:
            clean = val_str.replace(',', '').replace('$', '')
            val = float(clean)
            if suffix.lower() == 'k': val *= 1000
            return val
        except: return None

    def _parse_val(self, val_str, suffix=None):
        """
        Helper to convert '95,000' or '95' + 'k' into float 95000.0.
        Handles None suffix safely.
        """
        try:
            if not val_str: return None
            
            # 1. Clean the number string
            clean = val_str.replace(',', '').replace('$', '')
            val = float(clean)
            
            # 2. Handle Suffix (ensure it's not None before checking lower)
            if suffix and suffix.lower() == 'k': 
                val *= 1000
                
            return val
        except:
            return None

    def extract_via_regex(self, question):
        q = question.lower()

        # --- 1. Identify Asset ---
        asset = None
        if "bitcoin" in q or "btc" in q: asset = "BTC"
        elif "ethereum" in q or "eth" in q: asset = "ETH"
        elif "solana" in q or "sol" in q: asset = "SOL"
        
        if not asset: return None

        if "all time high" in q: # All time high and low are not valid questions for us to parse
            return None
        
        if "all time low" in q: # All time high and low are not valid questions for us to parse
            return None

        # --- 2. Pattern: "Up or Down" (Direction 1) ---
        if "down" in q:
            return {"asset": asset, "target_price": "CURRENT_PRICE", "direction": 1, "source": "REGEX_UP_DOWN"}

        if "up" in q:
            return {"asset": asset, "target_price": "CURRENT_PRICE", "direction": 1, "source": "REGEX_UP"}
        
        # --- 3. Pattern: "Between X and Y" (Range) ---
        # Note: We pass (group or '') to ensure we don't pass None to _parse_val
        between_pattern = r'between\s+\$?([\d,.]+)(k)?\s+and\s+\$?([\d,.]+)(k)?'
        range_match = re.search(between_pattern, q)
        if range_match:
            val1 = self._parse_val(range_match.group(1), range_match.group(2))
            val2 = self._parse_val(range_match.group(3), range_match.group(4))
            if val1 and val2:
                return {"asset": asset, "target_price": (val1 + val2)/2, "direction": 0, "source": "REGEX_RANGE"}

        # --- 4. STRICT Pattern: Asset + Keyword (Best Accuracy) ---
        # Matches: "Bitcoin above 95k", "BTC below 100,000"
        # We run this BEFORE the general keyword search to be precise.
        
        # 4a. Bullish Strict
        strict_bull = r'(?:btc|bitcoin|eth|ethereum|sol|solana)\s+(?:is\s+)?(?:above|greater|more|exceed|hit|touch)\s+\$?([\d,.]+)(k)?'
        match = re.search(strict_bull, q)
        if match:
            val = self._parse_val(match.group(1), match.group(2))
            if val: return {"asset": asset, "target_price": val, "direction": 1, "source": "REGEX_STRICT_BULL"}

        # 4b. Bearish Strict
        strict_bear = r'(?:btc|bitcoin|eth|ethereum|sol|solana)\s+(?:is\s+)?(?:below|under|less|smaller)\s+\$?([\d,.]+)(k)?'
        match = re.search(strict_bear, q)
        if match:
            val = self._parse_val(match.group(1), match.group(2))
            if val: return {"asset": asset, "target_price": val, "direction": -1, "source": "REGEX_STRICT_BEAR"}

        # --- 5. LOOSE Pattern: Keywords only ---
        # Matches: "Above $95,000" (Implicitly refers to the asset found in step 1)
        
        bullish_keywords = r'(?:greater|more|above|exceed|hit|touch|reach)'
        bearish_keywords = r'(?:smaller|less|below|under)'

        # Check Bearish
        bear_match = re.search(f'{bearish_keywords}' + r'.*?\$?([\d,.]+)(k)?', q)
        if bear_match:
            val = self._parse_val(bear_match.group(1), bear_match.group(2))
            if val: return {"asset": asset, "target_price": val, "direction": -1, "source": "REGEX_LOOSE_BEAR"}

        # Check Bullish
        bull_match = re.search(f'{bullish_keywords}' + r'.*?\$?([\d,.]+)(k)?', q)
        if bull_match:
            val = self._parse_val(bull_match.group(1), bull_match.group(2))
            if val: return {"asset": asset, "target_price": val, "direction": 1, "source": "REGEX_LOOSE_BULL"}

        # --- 6. Fallback: Generic Number Extraction ---
        # Warning: This picks up dates (e.g., "January 17"). We must filter them.
        price_pattern = r'\$?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+)(k)?'
        matches = re.findall(price_pattern, q)
        
        candidates = []
        for val_str, suffix in matches:
            val = self._parse_val(val_str, suffix)
            if not val: continue
            
            # FILTER: Exclude Years
            if 2020 < val < 2030 and suffix == '': continue
            
            # FILTER: Exclude Calendar Days (1-31) if no 'k' suffix and value is small
            # (BTC/ETH prices are > 31, SOL is usually > 31 but risky. This logic assumes Price > 100)
            if val <= 31 and suffix == '': continue 
            
            candidates.append(val)

        if len(candidates) == 1:
            # Assume Bullish if just a number appears (e.g. "Bitcoin $100k?")
            return {"asset": asset, "target_price": candidates[0], "direction": 1, "source": "REGEX_GENERIC"}

        return None

    def question_contains_numbers(self, question):
        if re.search(r'\d', question):
            return True
        return False

    def parse_question(self, question):
        fast = self.extract_via_regex(question)
        if fast: return fast

        if not self.question_contains_numbers(question):
            return None

        if "all time high" in question.lower(): # All time high and low are not valid questions for us to parse
            return None
        
        if "all time low" in question.lower(): # All time high and low are not valid questions for us to parse
            return None

        # LLM Fallback (Costly)
        print(f"   🤖 [LLM] Analyzing: \"{question}\"")
        prompt = f"""
        if the question {question} not about the price of a cryptocurrency retrun ONLY the text "No data found" DO NOT RETURN ANY OTHER TEXT!
        Otherwise, extract the following data from the question:
        1. Asset (BTC, ETH).
        2. Target Price (float).
        3. Direction: 1 if (Above/Hit/Greater), -1 if (Below/Less), 0 if Range.
        
        If Asset or Target Price were not extracted return ONLY this text 'No data found' DO NOT RETURN ANY OTHER TEXT!
        Otherise return this JSON: {{"asset": <asset>, "target_price": <target_price>, "direction": <direction>}} 
        if direction was not extracted, use 1 for direction.
        """
        body = json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 100, "messages": [{"role": "user", "content": prompt}]})
        try:
            resp = self.bedrock.invoke_model(body=body, modelId=self.model_id)
            txt = json.loads(resp['body'].read())['content'][0]['text']
            if txt == 'No data found':
                try:
                    import csv
                except ImportError:
                    pass  # for runtime environments where csv is always available

                filename = "polymarkets_to_ignore.csv"
                try:
                    # Append question to the CSV file
                    with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow([question])
                except Exception:
                    pass  # Ignore errors to not halt processing
                return None
            j_start, j_end = txt.find('{'), txt.rfind('}') + 1
            # When no data was returned, write the question to polymarkets_to_ignore.csv
            
            if j_start == -1:
                try:
                    import csv
                except ImportError:
                    pass  # for runtime environments where csv is always available

                filename = "polymarkets_to_ignore.csv"
                try:
                    # Append question to the CSV file
                    with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow([question])
                except Exception:
                    pass  # Ignore errors to not halt processing
                return None
            data = json.loads(txt[j_start:j_end])
            
            # Default direction to 1 if missing
            if 'direction' not in data: data['direction'] = 1
            
            self._log_call(question, data, "SUCCESS")
            return data
        except Exception as e:
            self._log_call(question, str(e), "ERROR")
            return None