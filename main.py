from config import (
    LOOKBACK_DAYS,
)
from reddit_client import load_reddit
from processor import run_backfill, run_daily_sync

reddit, subreddit = load_reddit()

if LOOKBACK_DAYS:
    run_backfill(subreddit)
else:
    run_daily_sync(subreddit)
