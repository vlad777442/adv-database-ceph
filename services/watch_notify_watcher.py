"""
RADOS Watch/Notify-based watcher service.

Uses Ceph's native watch/notify mechanism instead of polling.
This is a Ceph-native contribution: leverages RADOS watch2
to receive real-time notifications when objects change, eliminating
the need for periodic full-pool scans.

Architecture:
- A sentinel object (_watch_sentinel) is watched via rados.Ioctx.watch()
- When any indexer creates/updates/deletes an object, it notifies
  the sentinel via rados.Ioctx.notify()
- The watcher callback fires immediately, triggering re-indexing
- Fallback to polling if watch/notify is unavailable

Advantages over polling:
1. Near-instant detection (sub-second vs. 60s poll interval)
2. No wasted I/O scanning unchanged pools
3. Scalable: O(1) per change vs. O(N) per poll cycle
4. Uses Ceph-native mechanism (librados watch2 API)

Limitations:
- Requires cooperation from writers (they must notify)
- Watch can break on OSD failover (auto-reconnect implemented)
- Only detects explicit notifications, not external writes
  (fallback polling handles those)
"""

import logging
import time
import threading
import json
from typing import Dict, Optional, Callable, Any
from datetime import datetime

try:
    import rados
    HAS_RADOS = True
except ImportError:
    HAS_RADOS = False

logger = logging.getLogger(__name__)

SENTINEL_OBJECT = "_watch_sentinel"


class WatchNotifyWatcher:
    """
    RADOS watch/notify-based watcher with polling fallback.
    
    Uses Ceph's native watch/notify for near-instant change detection,
    falling back to periodic polling for changes from external writers.
    """
    
    def __init__(
        self,
        rados_client,
        indexer,
        poll_interval: int = 300,    # Fallback poll: 5min (much less frequent)
        watch_timeout: int = 30,
    ):
        """
        Initialize watch/notify watcher.
        
        Args:
            rados_client: Connected RadosClient
            indexer: Indexer service
            poll_interval: Fallback polling interval (seconds)
            watch_timeout: Watch timeout for reconnection (seconds)
        """
        self.rados_client = rados_client
        self.indexer = indexer
        self.poll_interval = poll_interval
        self.watch_timeout = watch_timeout
        
        self.running = False
        self._watch_handle = None
        self._known_objects: Dict[str, datetime] = {}
        self._change_count = 0
        self._notification_count = 0
        self._watch_active = False
        
        # Stats
        self._stats = {
            "notifications_received": 0,
            "poll_cycles": 0,
            "objects_indexed": 0,
            "watch_reconnects": 0,
            "started_at": None,
        }
        
        logger.info(f"Initialized WatchNotifyWatcher (poll_fallback={poll_interval}s)")
    
    def _ensure_sentinel(self):
        """Ensure the sentinel object exists."""
        self.rados_client.ensure_connected()
        if not self.rados_client.object_exists(SENTINEL_OBJECT):
            sentinel_data = json.dumps({
                "type": "watch_sentinel",
                "created_at": datetime.now().isoformat(),
                "purpose": "RADOS watch/notify endpoint for change detection"
            }).encode('utf-8')
            self.rados_client.write_object(SENTINEL_OBJECT, sentinel_data)
            logger.info(f"Created sentinel object: {SENTINEL_OBJECT}")
    
    def _watch_callback(self, notify_id, notifier_id, watch_id, data):
        """
        Callback invoked when a notification arrives.
        
        Args:
            notify_id: Notification ID
            notifier_id: ID of the notifier
            watch_id: Watch handle ID
            data: Notification payload (JSON-encoded change info)
        """
        self._stats["notifications_received"] += 1
        
        try:
            if data:
                change_info = json.loads(data.decode('utf-8'))
                object_name = change_info.get("object_name", "")
                change_type = change_info.get("change_type", "unknown")
                
                logger.info(f"[watch/notify] {change_type}: {object_name}")
                
                if change_type in ("created", "updated"):
                    try:
                        self.indexer.index_object(object_name, force_reindex=True)
                        self._stats["objects_indexed"] += 1
                    except Exception as e:
                        logger.error(f"Failed to index {object_name}: {e}")
                        
                elif change_type == "deleted":
                    try:
                        self.indexer.remove_from_index(object_name)
                    except Exception as e:
                        logger.debug(f"Failed to remove {object_name} from index: {e}")
            else:
                logger.debug(f"[watch/notify] Empty notification (ping)")
                
        except Exception as e:
            logger.error(f"Error in watch callback: {e}")
    
    def _watch_error_callback(self, watch_id, error):
        """Handle watch errors (e.g., OSD failover)."""
        logger.warning(f"Watch error (id={watch_id}): {error}. Will reconnect.")
        self._watch_active = False
        self._stats["watch_reconnects"] += 1
    
    def _setup_watch(self) -> bool:
        """
        Set up RADOS watch on the sentinel object.
        
        Returns:
            True if watch was established
        """
        try:
            self._ensure_sentinel()
            ioctx = self.rados_client.ioctx
            
            if ioctx is None:
                logger.error("No RADOS ioctx available")
                return False
            
            # Use watch2 API
            self._watch_handle = ioctx.watch(
                SENTINEL_OBJECT,
                self._watch_callback,
                self._watch_error_callback,
                timeout=self.watch_timeout
            )
            
            self._watch_active = True
            logger.info(f"RADOS watch established on '{SENTINEL_OBJECT}'")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to set up RADOS watch: {e}. Using polling only.")
            self._watch_active = False
            return False
    
    def _teardown_watch(self):
        """Remove the RADOS watch."""
        if self._watch_handle is not None:
            try:
                ioctx = self.rados_client.ioctx
                if ioctx:
                    ioctx.unwatch(self._watch_handle)
                logger.info("RADOS watch removed")
            except Exception as e:
                logger.debug(f"Error removing watch: {e}")
            self._watch_handle = None
            self._watch_active = False
    
    @staticmethod
    def send_notification(rados_client, object_name: str, change_type: str):
        """
        Send a notification about an object change.
        
        Call this from indexer/writer code to notify watchers.
        
        Args:
            rados_client: Connected RadosClient
            object_name: Name of changed object
            change_type: 'created', 'updated', or 'deleted'
        """
        try:
            rados_client.ensure_connected()
            ioctx = rados_client.ioctx
            
            if not rados_client.object_exists(SENTINEL_OBJECT):
                return  # No watcher set up
            
            payload = json.dumps({
                "object_name": object_name,
                "change_type": change_type,
                "timestamp": datetime.now().isoformat(),
            }).encode('utf-8')
            
            ioctx.notify(SENTINEL_OBJECT, payload, timeout_ms=5000)
            logger.debug(f"Sent notification: {change_type} {object_name}")
            
        except Exception as e:
            # Notification failure is not critical
            logger.debug(f"Failed to send notification: {e}")
    
    def _poll_fallback(self) -> int:
        """
        Fallback polling for changes not caught by watch/notify.
        
        Returns:
            Number of changes detected
        """
        self._stats["poll_cycles"] += 1
        changes = 0
        
        try:
            current_objects = {}
            for obj_name in self.rados_client.list_objects():
                if obj_name.startswith("_"):  # Skip internal objects
                    continue
                try:
                    _, mtime = self.rados_client.get_object_stat(obj_name)
                    current_objects[obj_name] = mtime
                except Exception:
                    pass
            
            # Detect new/modified
            for obj_name, mtime in current_objects.items():
                if obj_name not in self._known_objects:
                    logger.info(f"[poll] New object: {obj_name}")
                    try:
                        self.indexer.index_object(obj_name, force_reindex=False)
                        changes += 1
                        self._stats["objects_indexed"] += 1
                    except Exception as e:
                        logger.error(f"Poll index error for {obj_name}: {e}")
                elif mtime > self._known_objects[obj_name]:
                    logger.info(f"[poll] Modified object: {obj_name}")
                    try:
                        self.indexer.index_object(obj_name, force_reindex=True)
                        changes += 1
                        self._stats["objects_indexed"] += 1
                    except Exception as e:
                        logger.error(f"Poll index error for {obj_name}: {e}")
            
            self._known_objects = current_objects
            
        except Exception as e:
            logger.error(f"Poll fallback error: {e}")
        
        return changes
    
    def watch(self, duration: Optional[int] = None):
        """
        Start watching for changes using watch/notify + polling fallback.
        
        Args:
            duration: Run for N seconds (None = indefinite)
        """
        import signal
        
        self.running = True
        self._stats["started_at"] = datetime.now().isoformat()
        
        def handle_signal(sig, frame):
            logger.info("Received stop signal")
            self.running = False
        
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
        
        # Initialize known objects
        self._known_objects = {}
        for obj_name in self.rados_client.list_objects():
            if not obj_name.startswith("_"):
                try:
                    _, mtime = self.rados_client.get_object_stat(obj_name)
                    self._known_objects[obj_name] = mtime
                except Exception:
                    pass
        
        logger.info(f"Tracking {len(self._known_objects)} objects")
        
        # Try to set up watch
        watch_ok = self._setup_watch()
        mode = "watch/notify + poll" if watch_ok else "poll only"
        logger.info(f"Watcher started in '{mode}' mode")
        
        start_time = time.time()
        
        try:
            while self.running:
                # Reconnect watch if needed
                if not self._watch_active and watch_ok:
                    logger.info("Reconnecting RADOS watch...")
                    self._setup_watch()
                
                # Periodic poll fallback
                changes = self._poll_fallback()
                if changes > 0:
                    logger.info(f"Poll cycle detected {changes} changes")
                
                # Check duration
                if duration and (time.time() - start_time) >= duration:
                    break
                
                # Sleep (shorter if watch active, since watch handles most)
                sleep_time = self.poll_interval if self._watch_active else 60
                
                # Interruptible sleep
                for _ in range(int(sleep_time)):
                    if not self.running:
                        break
                    time.sleep(1)
                    
        finally:
            self._teardown_watch()
            logger.info(f"Watcher stopped. Stats: {json.dumps(self._stats)}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get watcher statistics."""
        return {
            **self._stats,
            "watch_active": self._watch_active,
            "tracked_objects": len(self._known_objects),
            "pool_name": self.rados_client.pool_name,
            "mode": "watch/notify + poll" if self._watch_active else "poll only",
        }
