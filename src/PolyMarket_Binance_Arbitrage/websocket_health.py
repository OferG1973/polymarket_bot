"""
WebSocket health monitoring module
Tracks last update timestamps for Binance and Polymarket WebSockets
"""
import time
import threading
import logging
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger("WebSocketHealth")

class WebSocketHealthMonitor:
    """Monitors WebSocket connection health by tracking last update timestamps"""
    
    def __init__(self):
        # Timestamps in milliseconds
        self.binance_last_update_ms: Optional[int] = None
        self.polymarket_last_update_ms: Optional[int] = None
        
        # Timestamps as datetime objects for logging
        self.binance_last_update_time: Optional[datetime] = None
        self.polymarket_last_update_time: Optional[datetime] = None
        
        # Lock for thread-safe access
        self.lock = threading.Lock()
        
        # Monitoring thread
        self.monitoring_thread: Optional[threading.Thread] = None
        self.monitoring_active = False
        
        # Threshold in seconds (50 seconds)
        self.health_check_threshold_seconds = 50
    
    def update_binance_timestamp(self):
        """Update Binance WebSocket last update timestamp"""
        with self.lock:
            now = datetime.now()
            self.binance_last_update_ms = int(time.time() * 1000)
            self.binance_last_update_time = now
    
    def update_polymarket_timestamp(self):
        """Update Polymarket WebSocket last update timestamp"""
        with self.lock:
            now = datetime.now()
            self.polymarket_last_update_ms = int(time.time() * 1000)
            self.polymarket_last_update_time = now
    
    def get_binance_status(self) -> Tuple[bool, Optional[float], Optional[datetime]]:
        """
        Check Binance WebSocket health
        Returns: (is_healthy, seconds_since_last_update, last_update_time)
        """
        with self.lock:
            if self.binance_last_update_ms is None:
                return False, None, None
            
            current_ms = int(time.time() * 1000)
            seconds_since_update = (current_ms - self.binance_last_update_ms) / 1000.0
            is_healthy = seconds_since_update <= self.health_check_threshold_seconds
            
            return is_healthy, seconds_since_update, self.binance_last_update_time
    
    def get_polymarket_status(self) -> Tuple[bool, Optional[float], Optional[datetime]]:
        """
        Check Polymarket WebSocket health
        Returns: (is_healthy, seconds_since_last_update, last_update_time)
        """
        with self.lock:
            if self.polymarket_last_update_ms is None:
                return False, None, None
            
            current_ms = int(time.time() * 1000)
            seconds_since_update = (current_ms - self.polymarket_last_update_ms) / 1000.0
            is_healthy = seconds_since_update <= self.health_check_threshold_seconds
            
            return is_healthy, seconds_since_update, self.polymarket_last_update_time
    
    def start_monitoring(self, check_interval_seconds: int = 60):
        """Start background thread to monitor WebSocket health"""
        if self.monitoring_active:
            logger.warning("Monitoring thread already running")
            return
        
        self.monitoring_active = True
        
        def monitor_loop():
            while self.monitoring_active:
                try:
                    # Check Binance
                    binance_healthy, binance_seconds, binance_time = self.get_binance_status()
                    if binance_healthy:
                        time_str = binance_time.strftime("%H:%M:%S") if binance_time else "N/A"
                        logger.info(f"✅ Binance WebSocket: OK (last update {binance_seconds:.1f}s ago at {time_str})")
                    else:
                        if binance_seconds is None:
                            logger.warning("⚠️ Binance WebSocket: NO UPDATES RECEIVED YET")
                        else:
                            time_str = binance_time.strftime("%H:%M:%S") if binance_time else "N/A"
                            logger.error(f"❌ Binance WebSocket: NOT OK (last update {binance_seconds:.1f}s ago at {time_str}, threshold: {self.health_check_threshold_seconds}s)")
                    
                    # Check Polymarket
                    poly_healthy, poly_seconds, poly_time = self.get_polymarket_status()
                    if poly_healthy:
                        time_str = poly_time.strftime("%H:%M:%S") if poly_time else "N/A"
                        logger.info(f"✅ Polymarket WebSocket: OK (last update {poly_seconds:.1f}s ago at {time_str})")
                    else:
                        if poly_seconds is None:
                            logger.warning("⚠️ Polymarket WebSocket: NO UPDATES RECEIVED YET")
                        else:
                            time_str = poly_time.strftime("%H:%M:%S") if poly_time else "N/A"
                            logger.error(f"❌ Polymarket WebSocket: NOT OK (last update {poly_seconds:.1f}s ago at {time_str}, threshold: {self.health_check_threshold_seconds}s)")
                    
                except Exception as e:
                    logger.error(f"Error in WebSocket health check: {e}")
                
                # Wait for next check
                time.sleep(check_interval_seconds)
        
        self.monitoring_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info(f"✅ WebSocket health monitoring started (checking every {check_interval_seconds}s)")
    
    def stop_monitoring(self):
        """Stop background monitoring thread"""
        self.monitoring_active = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)
        logger.info("WebSocket health monitoring stopped")

# Global instance
health_monitor = WebSocketHealthMonitor()
