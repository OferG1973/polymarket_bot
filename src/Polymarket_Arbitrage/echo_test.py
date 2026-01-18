import asyncio
import aiohttp
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger("EchoTest")

async def run_echo_test():
    # 1. Test a generic public server (Not Polymarket)
    URL = "wss://echo.websocket.org"
    
    logger.info(f"🔌 Testing generic connection to: {URL}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(URL) as ws:
                logger.info("✅ Connected to Public Echo Server.")

                # 2. Send a "Hello" message
                msg = "Hello Norton, let me pass!"
                await ws.send_str(msg)
                logger.info(f"📡 Sent: '{msg}'")

                # 3. Wait for reply
                async for response in ws:
                    if response.type == aiohttp.WSMsgType.TEXT:
                        logger.info(f"🎉 SUCCESS! Received reply: '{response.data}'")
                        logger.info("CONCLUSION: Your computer allows WebSockets. The issue is Polymarket blocking your IP.")
                        return
                    
    except Exception as e:
        logger.error(f"❌ CONNECTION FAILED: {e}")
        logger.error("CONCLUSION: Your Firewall/Norton is blocking Python from using WebSockets completely.")

if __name__ == "__main__":
    asyncio.run(run_echo_test())