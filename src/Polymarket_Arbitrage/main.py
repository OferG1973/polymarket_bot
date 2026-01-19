import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Dict
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds  # <--- NEW IMPORT REQUIRED
from config import Config
from models import LocalOrderBook
from market_stream import MarketStream
from execution import ExecutionEngine
from strategy import ArbStrategy
from discovery import MarketDiscovery
from display import MarketDisplay

# --- LOGGING SETUP ---
LOG_DIR = os.path.join("/Volumes/SanDisk_Extreme_SSD", "workingFolder", "polymarket_arbitrage", "log")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Create timestamped log file
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(LOG_DIR, f"arbitrage_bot_{timestamp_str}.log")

# Custom handler to capture print statements and filter httpx logs with manual rotation
class FilteredRotatingFileHandler(logging.FileHandler):
    """File handler that filters out httpx HTTP request logs and supports manual rotation"""
    def __init__(self, filename):
        self.base_filename = filename
        self.current_log_file = filename
        super().__init__(filename, mode='a', encoding='utf-8')
    
    def rotate_log(self):
        """Rotate log file by closing current and creating new one with timestamp"""
        try:
            # Get root logger for rotation messages (before we close the file)
            root_logger = logging.getLogger()
            
            # Get current file size for logging
            old_size_mb = 0
            if os.path.exists(self.current_log_file):
                old_size_mb = os.path.getsize(self.current_log_file) / (1024 * 1024)
            
            # Log rotation message to console (file will be closed)
            print(f"🔄 Rotating log file (after {old_size_mb:.2f}MB): {os.path.basename(self.current_log_file)}")
            
            # Close current file
            self.close()
            
            # Create new log file with new timestamp
            new_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_log_file = os.path.join(LOG_DIR, f"arbitrage_bot_{new_timestamp}.log")
            
            # Reopen with new file
            self.baseFilename = self.current_log_file
            self.stream = self._open()
            
            # Log to console and new file
            print(f"📝 New log file created: {os.path.basename(self.current_log_file)}")
            root_logger.info(f"📝 New log file created: {os.path.basename(self.current_log_file)}")
            
            # Update LoggedStdout to use new log file
            if hasattr(sys.stdout, 'log_file_path'):
                sys.stdout.log_file_path = self.current_log_file
                
        except Exception as e:
            # Use print since logger might not be available
            print(f"❌ Error rotating log file: {e}")
            import traceback
            traceback.print_exc()
    
    def emit(self, record):
        # Filter out httpx HTTP request logs
        if record.name == 'httpx' and 'HTTP Request:' in record.getMessage():
            return
        super().emit(record)

# Create file handler with filter (rotation is triggered by table updates)
file_handler = FilteredRotatingFileHandler(log_file)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))

# Console handler (no filter, show everything)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Suppress httpx logger for file (but allow console)
httpx_logger = logging.getLogger('httpx')
httpx_logger.setLevel(logging.WARNING)  # Only warnings/errors to file

logger = logging.getLogger("Main")
logger.info(f"📝 Logging to file: {log_file}")

# Custom stdout wrapper to capture print statements to log file
class LoggedStdout:
    """Wrapper for stdout that logs print statements to file"""
    def __init__(self, original_stdout, log_file_path):
        self.original_stdout = original_stdout
        self.log_file_path = log_file_path
        self.buffer = ""
    
    def write(self, text):
        """Write to both original stdout and log file"""
        # Write to console
        self.original_stdout.write(text)
        self.original_stdout.flush()
        
        # Buffer for log file
        self.buffer += text
        if '\n' in self.buffer:
            lines = self.buffer.split('\n')
            self.buffer = lines[-1]  # Keep incomplete line in buffer
            try:
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    for line in lines[:-1]:  # Write complete lines
                        if line.strip():  # Only log non-empty lines
                            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [Display] INFO: {line}\n")
            except Exception:
                pass
    
    def flush(self):
        """Flush both outputs"""
        self.original_stdout.flush()
        if self.buffer.strip():
            try:
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [Display] INFO: {self.buffer}\n")
                self.buffer = ""
            except Exception:
                pass

# Store original stdout
original_stdout = sys.stdout

async def main():
    # Redirect stdout to capture table prints to log file
    sys.stdout = LoggedStdout(original_stdout, log_file)
    
    logger.info("🤖 Polymarket Auto-Bot Initializing...")
    
    # Log settings
    logger.info("="*60)
    logger.info("⚙️  CONFIGURATION SETTINGS")
    logger.info("="*60)
    logger.info(f"MAX_MARKETS_TO_TRACK: {Config.MAX_MARKETS_TO_TRACK}")
    logger.info(f"MARKETS_TO_SCAN: {Config.MARKETS_TO_SCAN}")
    logger.info(f"MIN_LIQUIDITY_USDC: ${Config.MIN_LIQUIDITY_USDC:,.0f}")
    logger.info(f"MIN_VOLUME_USDC: ${Config.MIN_VOLUME_USDC:,.0f}")
    logger.info(f"MIN_HOURS_UNTIL_END: {Config.MIN_HOURS_UNTIL_END}")
    logger.info(f"MAX_TRADE_SIZE_USDC: ${Config.MAX_TRADE_SIZE_USDC:,.0f}")
    logger.info(f"MIN_PROFIT_SPREAD: {Config.MIN_PROFIT_SPREAD}")
    logger.info(f"SIMULATION_MODE: {Config.SIMULATION_MODE}")
    logger.info("="*60)

    # 1. Initialize API Client
    try:
        # Initialize Client (L1 Auth only first)
        client = ClobClient(
            host=Config.HOST,
            key=Config.PRIVATE_KEY,
            chain_id=Config.CHAIN_ID
        )

        # Create Credentials Object (L2 Auth)
        creds = ApiCreds(
            api_key=Config.API_KEY,
            api_secret=Config.API_SECRET,
            api_passphrase=Config.PASSPHRASE
        )

        # Set Credentials on the client
        client.set_api_creds(creds)
        
    except Exception as e:
        logger.error(f"Failed to init Client: {e}")
        return

    # 2. RUN DISCOVERY (The "Auto" part)
    # Fetch MARKETS_TO_SCAN markets, get top ones, and store all scored markets for replacement pool
    logger.info(f"📊 Fetching up to {Config.MARKETS_TO_SCAN} markets, selecting top {Config.MAX_MARKETS_TO_TRACK * 2}...")
    market_pairs, all_scored_markets = MarketDiscovery.get_top_markets(limit=Config.MAX_MARKETS_TO_TRACK * 2)
    
    if not market_pairs:
        logger.error("No markets found to track. Exiting.")
        return
    
    # Store all scored markets as replacement pool (sorted by score)
    # Markets 0-49 are the top 50 being monitored
    # Markets 50+ are available for replacement
    replacement_pool = all_scored_markets.copy()  # All 1000 scored markets
    next_replacement_index = Config.MAX_MARKETS_TO_TRACK  # Start from market #51
    monitored_token_ids = set()  # Track token IDs of currently monitored markets
    replaced_markets = set()  # Track markets that have been replaced (by token pair key)

    # 3. Create Local Orderbooks for ALL found tokens
    books = {}
    token_ids_to_subscribe = []

    for m in market_pairs:
        # Use generic keys token_a / token_b
        books[m['token_a']] = LocalOrderBook(m['token_a'])
        books[m['token_b']] = LocalOrderBook(m['token_b'])
        
        token_ids_to_subscribe.append(m['token_a'])
        token_ids_to_subscribe.append(m['token_b'])

    logger.info(f"📚 Initialized Orderbooks for {len(market_pairs)} markets ({len(token_ids_to_subscribe)} tokens)")

    # 3.5. Fetch initial order book snapshots and validate actual liquidity
    logger.info("📥 Fetching initial order book snapshots and validating actual liquidity...")
    populated_count = 0
    markets_with_data = set()  # Track which markets have actual order book data
    
    for token_id in token_ids_to_subscribe:
        try:
            book = books.get(token_id) or books.get(str(token_id))
            if not book:
                continue
                
            # Fetch current order book via REST API
            ob = client.get_order_book(token_id)
            
            has_asks = False
            has_bids = False
            
            if ob and hasattr(ob, 'asks') and ob.asks:
                # Populate asks
                for ask in ob.asks:
                    price = float(ask.price)
                    size = float(ask.size)
                    if price > 0 and size > 0:
                        book.update("sell", price, size)
                        has_asks = True
            
            if ob and hasattr(ob, 'bids') and ob.bids:
                # Populate bids
                for bid in ob.bids:
                    price = float(bid.price)
                    size = float(bid.size)
                    if price > 0 and size > 0:
                        book.update("buy", price, size)
                        has_bids = True
            
            if has_asks or has_bids:
                populated_count += 1
                
        except Exception as e:
            # Some markets might not have order books yet (illiquid)
            logger.debug(f"Could not fetch order book for token {token_id}: {e}")
            continue
    
    logger.info(f"✅ Populated {populated_count}/{len(token_ids_to_subscribe)} order books with initial data")
    
    # 3.6. Filter out markets without actual order book data
    # A market needs BOTH tokens to have order book data
    valid_markets = []
    removed_count = 0
    seen_token_ids = set()  # Track token IDs we've already processed
    
    for m in market_pairs:
        token_a = m['token_a']
        token_b = m['token_b']
        book_a = books.get(token_a) or books.get(str(token_a))
        book_b = books.get(token_b) or books.get(str(token_b))
        
        # Check if both tokens have actual order book data (at least one side)
        if book_a and book_b:
            p_a, _ = book_a.get_best_ask()
            p_b, _ = book_b.get_best_ask()
            
            if p_a is not None and p_b is not None:
                valid_markets.append(m)
                seen_token_ids.add(str(token_a))
                seen_token_ids.add(str(token_b))
            else:
                removed_count += 1
                logger.debug(f"Removed market '{m['title'][:50]}...' - No order book data")
        else:
            removed_count += 1
            logger.debug(f"Removed market '{m['title'][:50]}...' - Missing order books")
    
    # Update market_pairs and token subscriptions to only include valid markets
    if removed_count > 0:
        logger.warning(f"⚠️ Removed {removed_count} markets with no actual order book data")
        logger.info(f"📊 Valid markets with order book data: {len(valid_markets)}/{len(market_pairs)}")
        logger.info("💡 Note: API 'liquidity' field may represent historical liquidity, not current order book availability")
    
    # Limit to MAX_MARKETS_TO_TRACK to ensure we don't exceed the target
    if len(valid_markets) > Config.MAX_MARKETS_TO_TRACK:
        logger.info(f"📊 Limiting initial valid markets from {len(valid_markets)} to {Config.MAX_MARKETS_TO_TRACK}")
        valid_markets = valid_markets[:Config.MAX_MARKETS_TO_TRACK]
    
    market_pairs = valid_markets
    initial_valid_count = len(valid_markets)  # Track initial count for logging
    
    # 3.7. If we don't have enough markets, fetch more and validate them
    while len(market_pairs) < Config.MAX_MARKETS_TO_TRACK:
        count_before_iteration = len(market_pairs)
        needed = Config.MAX_MARKETS_TO_TRACK - len(market_pairs)
        logger.info(f"📈 Only have {len(market_pairs)}/{Config.MAX_MARKETS_TO_TRACK} valid markets. Fetching {needed * 2} more candidates...")
        
        # Fetch more markets (skip ones we've already seen)
        additional_markets = MarketDiscovery.get_top_markets(limit=needed * 2, skip_token_ids=seen_token_ids)
        
        if not additional_markets:
            logger.warning(f"⚠️ No more markets available. Will monitor {len(market_pairs)} markets instead of {Config.MAX_MARKETS_TO_TRACK}")
            break
        
        # Create order books for new markets
        new_token_ids = []
        for m in additional_markets:
            token_a = m['token_a']
            token_b = m['token_b']
            
            if str(token_a) not in books:
                books[token_a] = LocalOrderBook(token_a)
            if str(token_b) not in books:
                books[token_b] = LocalOrderBook(token_b)
            
            new_token_ids.append(token_a)
            new_token_ids.append(token_b)
        
        # Fetch order book data for new markets
        new_valid_count = 0
        for token_id in new_token_ids:
            try:
                book = books.get(token_id) or books.get(str(token_id))
                if not book:
                    continue
                    
                ob = client.get_order_book(token_id)
                
                has_asks = False
                has_bids = False
                
                if ob and hasattr(ob, 'asks') and ob.asks:
                    for ask in ob.asks:
                        price = float(ask.price)
                        size = float(ask.size)
                        if price > 0 and size > 0:
                            book.update("sell", price, size)
                            has_asks = True
                
                if ob and hasattr(ob, 'bids') and ob.bids:
                    for bid in ob.bids:
                        price = float(bid.price)
                        size = float(bid.size)
                        if price > 0 and size > 0:
                            book.update("buy", price, size)
                            has_bids = True
                
                if has_asks or has_bids:
                    new_valid_count += 1
                    
            except Exception as e:
                logger.debug(f"Could not fetch order book for token {token_id}: {e}")
                continue
        
        # Validate new markets
        for m in additional_markets:
            token_a = m['token_a']
            token_b = m['token_b']
            book_a = books.get(token_a) or books.get(str(token_a))
            book_b = books.get(token_b) or books.get(str(token_b))
            
            if book_a and book_b:
                p_a, _ = book_a.get_best_ask()
                p_b, _ = book_b.get_best_ask()
                
                if p_a is not None and p_b is not None:
                    market_pairs.append(m)
                    seen_token_ids.add(str(token_a))
                    seen_token_ids.add(str(token_b))
                    
                    if len(market_pairs) >= Config.MAX_MARKETS_TO_TRACK:
                        break
        
        added_this_iteration = len(market_pairs) - count_before_iteration
        total_added = len(market_pairs) - initial_valid_count
        logger.info(f"✅ Added {added_this_iteration} markets this iteration ({total_added} total). Current: {len(market_pairs)}/{Config.MAX_MARKETS_TO_TRACK}")
        
        # If we still don't have enough and got no new valid markets, stop trying
        if added_this_iteration == 0:
            logger.warning(f"⚠️ No more valid markets found. Will monitor {len(market_pairs)} markets instead of {Config.MAX_MARKETS_TO_TRACK}")
            break
    
    # Final safety check: ensure we never exceed MAX_MARKETS_TO_TRACK
    if len(market_pairs) > Config.MAX_MARKETS_TO_TRACK:
        logger.warning(f"⚠️ Limiting markets from {len(market_pairs)} to {Config.MAX_MARKETS_TO_TRACK}")
        market_pairs = market_pairs[:Config.MAX_MARKETS_TO_TRACK]
    
    # Rebuild token_ids_to_subscribe to match valid markets only
    token_ids_to_subscribe = []
    for m in market_pairs:
        token_ids_to_subscribe.append(m['token_a'])
        token_ids_to_subscribe.append(m['token_b'])
        monitored_token_ids.add(str(m['token_a']))
        monitored_token_ids.add(str(m['token_b']))
    
    logger.info(f"📊 Final: Monitoring {len(market_pairs)} markets with actual order book data ({len(token_ids_to_subscribe)} tokens)")

    print("\n" + "="*60)
    print(f"📡 SUBSCRIBED TO {len(market_pairs)} MARKETS:")
    print("="*60)
    for i, m in enumerate(market_pairs[:10]): # Show first 10 to save space
        print(f" {i+1}. {m['title'][:50]}")
    if len(market_pairs) > 10:
        print(f" ... and {len(market_pairs)-10} more.")
    print("="*60 + "\n")
    # --------------------------------------------
    
    # 4. Market replacement callback (wrapper to handle async from sync context)
    replacement_queue = asyncio.Queue()  # Queue for market replacements
    
    async def replace_market_async(old_market: Dict):
        """Replace a market that has been expensive for >10 updates"""
        nonlocal next_replacement_index
        
        old_token_a = str(old_market['token_a'])
        old_token_b = str(old_market['token_b'])
        old_market_key = f"{old_token_a}_{old_token_b}"
        
        logger.info(f"🔄 Replacing market: {old_market['title'][:50]}...")
        
        # Mark the old market as replaced (so it can't be used again)
        replaced_markets.add(old_market_key)
        
        # Find next available market from replacement pool (starting from index 51, 52, etc.)
        replacement = None
        max_attempts = len(replacement_pool) - next_replacement_index
        attempts = 0
        
        while next_replacement_index < len(replacement_pool) and attempts < max_attempts:
            candidate = replacement_pool[next_replacement_index]
            next_replacement_index += 1  # Move to next market for future replacements
            attempts += 1
            
            cand_token_a = str(candidate['token_a'])
            cand_token_b = str(candidate['token_b'])
            cand_market_key = f"{cand_token_a}_{cand_token_b}"
            
            # Skip if already monitored
            if cand_token_a in monitored_token_ids or cand_token_b in monitored_token_ids:
                continue
            
            # Skip if this market was already used as a replacement
            if cand_market_key in replaced_markets:
                continue
            
            # Skip if this is the market we're replacing (shouldn't happen, but safety check)
            if cand_market_key == old_market_key:
                continue
            
            # Validate replacement market has order book data
            try:
                book_a = books.get(cand_token_a) or books.get(str(cand_token_a))
                book_b = books.get(cand_token_b) or books.get(str(cand_token_b))
                
                if not book_a:
                    books[cand_token_a] = LocalOrderBook(cand_token_a)
                    book_a = books[cand_token_a]
                if not book_b:
                    books[cand_token_b] = LocalOrderBook(cand_token_b)
                    book_b = books[cand_token_b]
                
                # Fetch order book data
                ob_a = client.get_order_book(cand_token_a)
                ob_b = client.get_order_book(cand_token_b)
                
                has_data = False
                if ob_a and hasattr(ob_a, 'asks') and ob_a.asks:
                    for ask in ob_a.asks:
                        price = float(ask.price)
                        size = float(ask.size)
                        if price > 0 and size > 0:
                            book_a.update("sell", price, size)
                            has_data = True
                
                if ob_b and hasattr(ob_b, 'asks') and ob_b.asks:
                    for ask in ob_b.asks:
                        price = float(ask.price)
                        size = float(ask.size)
                        if price > 0 and size > 0:
                            book_b.update("sell", price, size)
                            has_data = True
                
                # Check if both tokens have valid prices
                p_a, _ = book_a.get_best_ask()
                p_b, _ = book_b.get_best_ask()
                
                if p_a is not None and p_b is not None:
                    replacement = candidate
                    break
            except Exception as e:
                logger.debug(f"Could not validate replacement market: {e}")
                continue
        
        if replacement:
            # Remove old market
            market_pairs.remove(old_market)
            monitored_token_ids.discard(old_token_a)
            monitored_token_ids.discard(old_token_b)
            
            # Add new market
            market_pairs.append(replacement)
            replacement_token_a = str(replacement['token_a'])
            replacement_token_b = str(replacement['token_b'])
            monitored_token_ids.add(replacement_token_a)
            monitored_token_ids.add(replacement_token_b)
            
            # Update token subscriptions
            token_ids_to_subscribe.remove(old_market['token_a'])
            token_ids_to_subscribe.remove(old_market['token_b'])
            token_ids_to_subscribe.append(replacement['token_a'])
            token_ids_to_subscribe.append(replacement['token_b'])
            
            # Update stream subscriptions
            stream.tokens_to_sub = token_ids_to_subscribe
            
            # Update strategy and display
            strategy.market_pairs = market_pairs
            display.market_pairs = market_pairs
            
            logger.info(f"✅ Replaced with: {replacement['title'][:50]}... (Market #{next_replacement_index-1} from pool)")
        else:
            logger.warning(f"⚠️ No suitable replacement found from pool (tried {attempts} markets). Keeping original market.")
            # Don't mark as replaced if we couldn't find a replacement
            replaced_markets.discard(old_market_key)
    
    def replace_market_sync(old_market: Dict):
        """Sync wrapper that queues async replacement"""
        try:
            replacement_queue.put_nowait(old_market)
        except asyncio.QueueFull:
            logger.warning("Replacement queue full, skipping replacement")
    
    # 5. Initialize Display with replacement callback
    # Log rotation callback (triggered every 300 table updates)
    def rotate_log_file():
        """Callback to rotate log file"""
        file_handler.rotate_log()
    
    display = MarketDisplay(books, market_pairs, replacement_callback=replace_market_sync, log_rotation_callback=rotate_log_file)
    
    # 6. Initialize Components
    # Create update callback that refreshes the table
    def on_update():
        display.display_table()
    
    stream = MarketStream(client, books, update_callback=on_update)
    # PATCH: Manually set the tokens list on the stream object
    stream.tokens_to_sub = token_ids_to_subscribe 
    
    executor = ExecutionEngine(client)
    
    # Market removal callback for strategy (called after arbitrage execution)
    def remove_market_after_arbitrage(market: Dict):
        """Remove market from monitoring after arbitrage execution and trigger replacement"""
        # Remove from market_pairs
        if market in market_pairs:
            market_pairs.remove(market)
            logger.info(f"✅ Removed executed market from monitoring: {market['title'][:50]}...")
        
        # Update monitored token IDs
        monitored_token_ids.discard(str(market['token_a']))
        monitored_token_ids.discard(str(market['token_b']))
        
        # Remove from token subscriptions
        if market['token_a'] in token_ids_to_subscribe:
            token_ids_to_subscribe.remove(market['token_a'])
        if market['token_b'] in token_ids_to_subscribe:
            token_ids_to_subscribe.remove(market['token_b'])
        
        # Update stream subscriptions
        stream.tokens_to_sub = token_ids_to_subscribe
        
        # Update display and strategy market lists
        display.market_pairs = market_pairs
        strategy.market_pairs = market_pairs
        
        # Trigger replacement with a new market
        replace_market_sync(market)
    
    strategy = ArbStrategy(books, market_pairs, executor, market_removal_callback=remove_market_after_arbitrage)

    # Display initial table
    display.display_table()

    # 7. Market replacement processor task
    async def process_replacements():
        """Process market replacements from queue"""
        while True:
            try:
                old_market = await asyncio.wait_for(replacement_queue.get(), timeout=1.0)
                await replace_market_async(old_market)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing market replacement: {e}")
    
    # 8. Periodic table refresh task (backup in case updates are missed)
    async def periodic_refresh():
        """Refresh table every 2 seconds as backup"""
        while True:
            await asyncio.sleep(2.0)
            display.display_table()
    
    # 9. Run Tasks
    try:
        await asyncio.gather(
            stream.start(),
            strategy.run_loop(),
            periodic_refresh(),
            process_replacements()
        )
    except KeyboardInterrupt:
        logger.info("Stopping bot...")
    except Exception as e:
        logger.critical(f"Crash: {e}")
    finally:
        # Restore original stdout
        sys.stdout.flush()
        sys.stdout = original_stdout

if __name__ == "__main__":
    asyncio.run(main())