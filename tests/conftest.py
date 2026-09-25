import os

# Tests trigger /sync themselves, so switch the background sync off to keep them deterministic.
os.environ["SYNC_INTERVAL_SECONDS"] = "0"
