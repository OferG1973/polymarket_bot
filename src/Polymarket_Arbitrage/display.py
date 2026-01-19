import os
import sys
import time
import threading
import logging
from typing import Dict, List
from models import LocalOrderBook
from config import Config

logger = logging.getLogger("Display")

class MarketDisplay:
    """Real-time table display for tracked markets"""
    
    def __init__(self, books: Dict[str, LocalOrderBook], market_pairs: List[Dict], replacement_callback=None, log_rotation_callback=None):
        self.books = books
        self.market_pairs = market_pairs
        self.update_count = 0
        self.last_display_time = 0
        self.display_lock = threading.Lock()  # Prevent concurrent displays
        self.replacement_callback = replacement_callback  # Callback to replace markets
        self.log_rotation_callback = log_rotation_callback  # Callback to rotate log file
        # Track consecutive "Expensive" status counts per market (by token pair key)
        self.expensive_counts: Dict[str, int] = {}
        
    def clear_screen(self):
        """Clear terminal screen"""
        os.system('clear' if os.name != 'nt' else 'cls')
    
    def display_table(self, force: bool = False):
        """Display/refresh the market table with current prices"""
        # Throttle updates to prevent flickering (max 1 per 0.3 seconds)
        current_time = time.time()
        if not force and current_time - self.last_display_time < 0.3:
            return
        
        # Use lock to prevent concurrent displays
        if not self.display_lock.acquire(blocking=False):
            return
        
        try:
            # Don't clear screen on first display to preserve startup logs
            if self.update_count > 0:
                self.clear_screen()
            
            self.update_count += 1
            self.last_display_time = current_time
            
            # Rotate log file every 300 table updates
            if self.log_rotation_callback and self.update_count % 300 == 0:
                self.log_rotation_callback()
            
            # Define column widths (adjusted for proper alignment)
            w_row = 5   # Row number column
            w_name = 45
            w_outcome = 30  # Increased to fit "OUTCOME A (Available units)" (28 chars)
            w_total = 12
            w_spread = 12
            w_target = 14  # Target spread column
            w_status = 15
            w_date = 12  # For start/end dates
            
            # Calculate total width: | + space + width + space + | for each column
            # Format: | col1 | col2 | ... | colN |
            total_width = (1 + 1 + w_row + 1 + 1 +      # | # |
                          1 + 1 + w_name + 1 + 1 +       # | MARKET NAME |
                          1 + 1 + w_outcome + 1 + 1 +    # | OUTCOME A |
                          1 + 1 + w_outcome + 1 + 1 +    # | OUTCOME B |
                          1 + 1 + w_total + 1 + 1 +      # | TOTAL COST |
                          1 + 1 + w_spread + 1 + 1 +     # | SPREAD |
                          1 + 1 + w_target + 1 + 1 +     # | TARGET SPREAD |
                          1 + 1 + w_date + 1 + 1 +       # | START DATE |
                          1 + 1 + w_date + 1 + 1 +       # | END DATE |
                          1 + 1 + w_status + 1 + 1)      # | STATUS |
            
            # Header
            print("\n" + "="*total_width)
            print(f" 📊 LIVE MARKET DATA (Update #{self.update_count}) - {len(self.market_pairs)} Markets - Sorted by Spread (Best First)")
            print("="*total_width)
            
            header = (
                f"| {'#':<{w_row}} | "
                f"{'MARKET NAME':<{w_name}} | "
                f"{'OUTCOME A (Available units)':<{w_outcome}} | "
                f"{'OUTCOME B (Available units)':<{w_outcome}} | "
                f"{'TOTAL COST':<{w_total}} | "
                f"{'SPREAD':<{w_spread}} | "
                f"{'TARGET SPREAD':<{w_target}} | "
                f"{'START DATE':<{w_date}} | "
                f"{'END DATE':<{w_date}} | "
                f"{'STATUS':<{w_status}} |"
            )
            print(header)
            print("-" * total_width)
            
            # Collect market data with spreads for sorting
            market_data = []
            for market in self.market_pairs:
                id_a = market['token_a']
                id_b = market['token_b']
                lbl_a = market['label_a']
                lbl_b = market['label_b']
                title = market['title']
                start_date = market.get('start_date', '-')
                end_date = market.get('end_date', '-')
                
                # Get current prices from order books
                book_a = self.books.get(id_a) or self.books.get(str(id_a))
                book_b = self.books.get(id_b) or self.books.get(str(id_b))
                
                spread_value = None  # For sorting
                
                # Get market type for target spread calculation
                market_type = market.get("market_type", Config.MARKET_TYPE)
                # Most markets are fee-free, so lower threshold. US markets have 0.01% taker fee.
                min_profit_spread = 0.011 if market_type == "us" else 0.01  # 1.1% for US (with taker fee), 1% for standard (fee-free)
                target_spread = f"{min_profit_spread:.2%}"
                
                if not book_a or not book_b:
                    # No data yet
                    out_a_str = f"{lbl_a}: --"
                    out_b_str = f"{lbl_b}: --"
                    total_cost = "--"
                    spread = "--"
                    status = "⏳ Waiting..."
                else:
                    # Get best ask prices
                    p_a, s_a = book_a.get_best_ask()
                    p_b, s_b = book_b.get_best_ask()
                    
                    if p_a is None or p_b is None:
                        out_a_str = f"{lbl_a}: --"
                        out_b_str = f"{lbl_b}: --"
                        total_cost = "--"
                        spread = "--"
                        status = "⏳ No Data"
                    else:
                        # Format prices with sizes
                        out_a_str = f"{lbl_a}: {p_a:.4f} ({s_a:.1f})"
                        out_b_str = f"{lbl_b}: {p_b:.4f} ({s_b:.1f})"
                        
                        # Calculate total cost and spread
                        total_cost_val = p_a + p_b
                        spread_value = 1.0 - total_cost_val  # For sorting (positive = good)
                        
                        # Determine status based on target spread from config
                        # Get market type (per-market if available, otherwise use global config)
                        market_type = market.get("market_type", Config.MARKET_TYPE)
                        # Most markets are fee-free, so lower threshold. US markets have 0.01% taker fee.
                        min_profit_spread = 0.011 if market_type == "us" else 0.01  # 1.1% for US (with taker fee), 1% for standard (fee-free)
                        threshold = 1.0 - min_profit_spread
                        
                        if total_cost_val < threshold:  # Spread >= MIN_PROFIT_SPREAD (actual arbitrage opportunity)
                            status = "🚨 ARB!"
                        elif total_cost_val < 0.995:  # Spread between 0.5% and target (good but not enough)
                            status = "✅ Good"
                        elif total_cost_val < 1.002:  # Spread between 0% and 0.5% (fair)
                            status = "⚪ Fair"
                        else:  # Spread negative or very small (expensive)
                            status = "❌ Expensive"
                        
                        # Track consecutive "Expensive" status
                        market_key = f"{id_a}_{id_b}"  # Unique key for this market
                        if status == "❌ Expensive":
                            self.expensive_counts[market_key] = self.expensive_counts.get(market_key, 0) + 1
                        else:
                            # Reset count if not expensive
                            self.expensive_counts[market_key] = 0
                        
                        # Check if market should be replaced (expensive for >10 updates)
                        if self.expensive_counts.get(market_key, 0) > 10:
                            if self.replacement_callback:
                                # Mark for replacement (will be handled after display)
                                market['_needs_replacement'] = True
                        
                        # Format numbers
                        total_cost = f"{total_cost_val:.4f}"
                        spread = f"{spread_value:.2%}"
                
                # Truncate title if too long
                display_title = (title[:w_name-3] + '..') if len(title) > w_name else title
                
                # Truncate outcome strings if too long
                if len(out_a_str) > w_outcome:
                    out_a_str = out_a_str[:w_outcome-3] + '..'
                if len(out_b_str) > w_outcome:
                    out_b_str = out_b_str[:w_outcome-3] + '..'
                
                # Format dates (truncate if needed)
                start_display = start_date[:w_date] if len(start_date) > w_date else start_date
                end_display = end_date[:w_date] if len(end_date) > w_date else end_date
                
                # Store market data for sorting (include market reference for replacement)
                market_data.append({
                    'market': market,  # Store reference for replacement
                    'spread_value': spread_value if spread_value is not None else -999,  # Put invalid spreads at end
                    'display_title': display_title,
                    'out_a_str': out_a_str,
                    'out_b_str': out_b_str,
                    'total_cost': total_cost,
                    'spread': spread,
                    'target_spread': target_spread,
                    'start_display': start_display,
                    'end_display': end_display,
                    'status': status
                })
            
            # Sort by spread descending (best spreads first)
            market_data.sort(key=lambda x: x['spread_value'], reverse=True)
            
            # Check for markets that need replacement
            markets_to_replace = []
            for data in market_data:
                market = data['market']
                if market.get('_needs_replacement', False):
                    markets_to_replace.append(market)
            
            # Display sorted markets with row numbers
            for row_num, data in enumerate(market_data, start=1):
                row = (
                    f"| {row_num:<{w_row}} | "
                    f"{data['display_title']:<{w_name}} | "
                    f"{data['out_a_str']:<{w_outcome}} | "
                    f"{data['out_b_str']:<{w_outcome}} | "
                    f"{data['total_cost']:<{w_total}} | "
                    f"{data['spread']:<{w_spread}} | "
                    f"{data['target_spread']:<{w_target}} | "
                    f"{data['start_display']:<{w_date}} | "
                    f"{data['end_display']:<{w_date}} | "
                    f"{data['status']:<{w_status}} |"
                )
                print(row)
            
            print("="*total_width)
            print(f"💡 Tip: Table updates automatically when WebSocket data arrives")
            print()
            
            # Trigger replacement if needed (after display to avoid flickering)
            if markets_to_replace and self.replacement_callback:
                for market in markets_to_replace:
                    market_key = f"{market['token_a']}_{market['token_b']}"
                    logger.info(f"🔄 Replacing market '{market['title'][:50]}...' (expensive for {self.expensive_counts.get(market_key, 0)} updates)")
                    self.replacement_callback(market)
                    # Clean up tracking
                    if market_key in self.expensive_counts:
                        del self.expensive_counts[market_key]
                    market.pop('_needs_replacement', None)
        finally:
            self.display_lock.release()
