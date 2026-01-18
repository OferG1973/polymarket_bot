from dataclasses import dataclass, field
from typing import List, Dict
from decimal import Decimal

@dataclass
class OrderLevel:
    price: float
    size: float

class LocalOrderBook:
    """
    Maintains a local copy of the order book.
    Updates via WebSocket deltas to avoid polling latency.
    """
    def __init__(self, token_id: str):
        self.token_id = token_id
        self.bids: Dict[float, float] = {} # Price -> Size
        self.asks: Dict[float, float] = {} # Price -> Size
        self.best_bid: float = 0.0
        self.best_ask: float = 0.0

    def update(self, side: str, price: float, size: float):
        """
        Updates the book based on delta. 
        If size is "0", remove the level.
        """
        # Polymarket sends prices as strings in WS, cast to float for math
        price = float(price)
        size = float(size)
        
        target = self.bids if side == "buy" else self.asks
        
        if size == 0:
            if price in target:
                del target[price]
        else:
            target[price] = size

        self._recalculate_top_of_book()

    def _recalculate_top_of_book(self):
        # Bids: Highest price is best
        if self.bids:
            self.best_bid = max(self.bids.keys())
        else:
            self.best_bid = 0.0

        # Asks: Lowest price is best
        if self.asks:
            self.best_ask = min(self.asks.keys())
        else:
            self.best_ask = 0.0 # Or infinity/None depending on logic

    def get_best_ask(self) -> tuple[float, float]:
        """Returns (Price, Size)"""
        if not self.asks: return (None, 0)
        return (self.best_ask, self.asks[self.best_ask])

    def get_best_bid(self) -> tuple[float, float]:
        """Returns (Price, Size)"""
        if not self.bids: return (None, 0)
        return (self.best_bid, self.bids[self.best_bid])