import asyncio
import logging
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds  # <--- NEW IMPORT REQUIRED
from config import Config
from models import LocalOrderBook
from market_stream import MarketStream
from execution import ExecutionEngine
from strategy import ArbStrategy
from discovery import MarketDiscovery

logging.basicConfig(
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("Main")

async def main():
    logger.info("🤖 Polymarket Auto-Bot Initializing...")

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
    # This fetches the top X markets automatically
    market_pairs = MarketDiscovery.get_top_markets(limit=Config.MAX_MARKETS_TO_TRACK)
    
    if not market_pairs:
        logger.error("No markets found to track. Exiting.")
        return

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

    # 4. Initialize Components
    stream = MarketStream(client, books)
    # PATCH: Manually set the tokens list on the stream object
    stream.tokens_to_sub = token_ids_to_subscribe 
    
    executor = ExecutionEngine(client)
    strategy = ArbStrategy(books, market_pairs, executor)

    # 5. Run Tasks
    try:
        await asyncio.gather(
            stream.start(),
            strategy.run_loop()
        )
    except KeyboardInterrupt:
        logger.info("Stopping bot...")
    except Exception as e:
        logger.critical(f"Crash: {e}")

if __name__ == "__main__":
    asyncio.run(main())