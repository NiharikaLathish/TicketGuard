"""Background worker that periodically runs the Cassandra -> Neo4j sync."""
import logging
import threading

from app import sync

log = logging.getLogger("ticketguard.sync")


def start(interval_seconds: float) -> tuple[threading.Thread, threading.Event]:
    """Start the worker thread. Set the returned event to stop it."""
    stop = threading.Event()

    def loop():
        while not stop.wait(interval_seconds):
            try:
                result = sync.run_sync()
                if result["synced"]:
                    log.info("auto-sync copied %s transaction(s)", result["synced"])
            except Exception:  # keep the worker alive if a database is briefly unavailable
                log.exception("auto-sync failed; will retry")

    thread = threading.Thread(target=loop, name="ticketguard-sync", daemon=True)
    thread.start()
    return thread, stop
