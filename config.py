import os
import requests

from dotenv import load_dotenv

# Get Variables from .env
load_dotenv()

REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET")
REDDIT_PASSWORD = os.environ.get("REDDIT_PASSWORD")
REDDIT_USERNAME = os.environ.get("REDDIT_USERNAME")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT")
REDDIT_SUBREDDIT = os.environ.get("REDDIT_SUBREDDIT")

AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
AIRTABLE_REVIEWS_TABLE = os.environ.get("AIRTABLE_REVIEWS_TABLE")

IMGUR_CLIENT_ID = os.environ.get("IMGUR_CLIENT_ID")
IMGUR_CLIENT_SECRET = os.environ.get("IMGUR_CLIENT_SECRET")
IMGUR_USER_AGENT = os.environ.get("IMGUR_USER_AGENT")

_replies_env = os.environ.get("ENABLE_POST_REPLIES", "true")
# If it exists but is blank, force it to "true"
if not _replies_env.strip():
    _replies_env = "true"
ENABLE_POST_REPLIES = _replies_env.lower() in ("true", "1", "yes")

# If set, script runs in Backfill mode. If missing/empty, runs in Daily Cron mode.
LOOKBACK_DAYS = os.environ.get("REVIEW_LOOKBACK_DAYS")

if LOOKBACK_DAYS:
    LOOKBACK_DAYS = int(LOOKBACK_DAYS)

######################################################
######## IMGUR HTTP SESSION
######################################################

# Create one http session for imgur api requests
http = requests.Session()
http.headers.update(
    {
        "Authorization": f"Client-ID {IMGUR_CLIENT_ID}",
        "User-Agent": IMGUR_USER_AGENT,
    }
)

imgur_cdn = requests.Session()
imgur_cdn.headers.update({"User-Agent": IMGUR_USER_AGENT})

######################################################
######## CONSTANTS
######################################################

# If a field in Airtable ever changes, we only need to update this section
FIELD_ATTACHMENT = "attachment"
FIELD_BRAND = "Brand"
FIELD_SELLER = "Seller"
FIELD_FACTORY = "Factory"
FIELD_STYLE = "STYLES"
FIELD_QUALITY = "Quality"
FIELD_ACCURACY = "Accuracy"
FIELD_COMMUNICATION = "Communication"
FIELD_SATISFACTION = "Satisfaction"
FIELD_PRICE = "Price"

MATCH_EXACT = "exact"
MATCH_CONTAINS = "contains"


######################################################
######## AIRTABLE INITIALIZATION & CACHING
######################################################

# Create an object for all things we're regexing
# Note: Extract and Score should be deprecated in the next update. Currently they're used to indicate whether a string needs further extraction
REGEX = {
    "WeChat": {
        "find": r"(wechat\W*)((\w|\d)*)",
        "extract": r"wechat\W*",
    },
    "WhatsApp": {
        "find": r"(whatsapp\W*)((?:\s*\d|\W){13})",
        "extract": r"whatsapp\W*",
    },
    # "email": { "find": r"([a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+\.[a-zA-Z0-9_-]+)" },
    "Yupoo": {
        "find": r"https://\w*\.\w\.yupoo\.com.*?(?=\))",
    },
    "Szwego": {
        "find": r"https://s\.wsxc\.cn/.*?(?=\]|\))|(?=https://).*szwego\.com.*?(?=\s)",
    },
    # "currency": { "find": r"[\$￥¥]|rmb|usd|cny", "compute": "test" },
    # "price-string": { "find": r"(?!=\$)\d+.?\d+|\d+.?\d+(?!=cny|usd)" },
    "Communication": {
        "find": r"communication[^0-9]{0,40}(\d+(?:[.,-]\d+)?)\s*/\s*10",
        "extract": r"communication.*?(?=\d)",
        "score": r"/(\w?)10",
    },
    "Satisfaction": {
        "find": r"satisfaction[^0-9]{0,40}(\d+(?:[.,-]\d+)?)\s*/\s*10",
        "extract": r"satisfaction.*?(?=\d)",
        "score": r"/(\w?)10",
    },
    "Quality": {
        "find": r"quality[^0-9]{0,40}(\d+(?:[.,-]\d+)?)\s*/\s*10",
        "extract": r"quality.*?(?=\d)",
        "score": r"/(\w?)10",
    },
    "Accuracy": {
        "find": r"accuracy[^0-9]{0,40}(\d+(?:[.,-]\d+)?)\s*/\s*10",
        "extract": r"accuracy.*?(?=\d)",
        "score": r"/(\w?)10",
    },
}
