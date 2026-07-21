import pandas as pd
import time

from pyairtable import Api  # Manage the Airtable API

from config import (
    AIRTABLE_API_KEY,
    AIRTABLE_BASE_ID,
    AIRTABLE_REVIEWS_TABLE,
    LOOKBACK_DAYS,
    ENABLE_POST_REPLIES,
)

api = Api(AIRTABLE_API_KEY)
base = api.base(AIRTABLE_BASE_ID)
reviews_table = base.table(AIRTABLE_REVIEWS_TABLE)
brands_table = base.table("BRANDS")
sellers_table = base.table("SELLERS")
factories_table = base.table("FACTORIES")
styles_table = base.table("STYLES")

print("\nInitializing Airtable Client...\n")

if LOOKBACK_DAYS:
    print("BACKFILL MODE: Fetching all historical records for deep deduplication...\n")

    existing_review_records = reviews_table.all(fields=["id"])
    most_recent_utc = 0
else:
    print("CRON MODE: Fetching recent records for daily sync deduplication...\n")

    two_days_ago_utc = int(time.time()) - (2 * 24 * 60 * 60)
    # Target only records from the last 48 hours based on their created_utc number field
    formula = f"{{created_utc}} >= {two_days_ago_utc}"
    existing_review_records = reviews_table.all(
        fields=["id", "created_utc"], formula=formula
    )

    df_recent = pd.DataFrame(existing_review_records)

    if not df_recent.empty and "fields" in df_recent.columns:
        recent_df = pd.json_normalize(df_recent.fields)
        utcs = (
            recent_df["created_utc"].dropna().to_list()
            if "created_utc" in recent_df.columns
            else []
        )
        most_recent_utc = max(utcs) if utcs else 0
    else:
        most_recent_utc = 0

# Extract existing IDs for O(1) lookup
df = pd.DataFrame(existing_review_records)

if not df.empty and "fields" in df.columns:
    reviews_df = pd.json_normalize(df.fields)
    existing_ids = (
        set(reviews_df["id"].dropna().to_list())
        if "id" in reviews_df.columns
        else set()
    )
else:
    existing_ids = set()

print(f"Loaded {len(existing_ids)} existing record IDs into memory.\n")

print(
    "Post replies enabled\n"
    if ENABLE_POST_REPLIES
    else "Post replies disabled (Airtable writes will still run)\n"
)
