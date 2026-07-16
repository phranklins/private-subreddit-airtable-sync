# Import libraries
import praw  # Manage the Reddit API
from pyairtable import Api  # Manage the Airtable API
import os # from datetime import date to manage dates
import re # from datetime import date to manage regex

import time # for timing
import requests  # Manage key functionality
import pandas as pd  # Easily work with tabular data
import mimetypes # for file uploads
import traceback # for debugging
from urllib.parse import urlparse, quote_plus
from dotenv import load_dotenv

######################################################
######## ENVIRONMENT
######################################################

# Get Variables from .env
load_dotenv()

REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET")
REDDIT_PASSWORD = os.environ.get("REDDIT_PASSWORD")
REDDIT_USERNAME = os.environ.get("REDDIT_USERNAME")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT")

AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
AIRTABLE_REVIEWS_TABLE = os.environ.get("AIRTABLE_REVIEWS_TABLE")

IMGUR_CLIENT_ID = os.environ.get("IMGUR_CLIENT_ID")
IMGUR_CLIENT_SECRET = os.environ.get("IMGUR_CLIENT_SECRET")
IMGUR_USER_AGENT = os.environ.get("IMGUR_USER_AGENT")

LOOKBACK_DAYS = os.environ.get("REVIEW_LOOKBACK_DAYS")
if LOOKBACK_DAYS:
    LOOKBACK_DAYS = int(LOOKBACK_DAYS)

ENABLE_POST_REPLIES = os.environ.get("ENABLE_POST_REPLIES", "true").lower() in (
    "true",
    "1",
    "yes",
)

######################################################
######## IMGUR HTTP SESSION
######################################################

# Create one http session for imgur api requests
imgur_api = requests.Session()
imgur_api.headers.update(
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
        "find": r"(communication.*?(?=\d))(\d+|\d+\W\d+)(\s?/(\s?)10)",
        "extract": r"(?<=communication).*?(?=\d)",
        "score": r"/(\w?)10",
    },
    "Satisfaction": {
        "find": r"(satisfaction.*?(?=\d))(\d+|\d+\W\d+)(\s?/\s?)10)",
        "extract": r"(satisfaction).*?(?=\d)",
        "score": r"/(\w?)10",
    },
    "Quality": {
        "find": r"(quality.*?(?=\d))(\d+|\d+\W\d+)(\s?)(/\s?10)",
        "extract": r"quality.*?(?=\d)",
        "score": r"/(\w?)10",
    },
    "Accuracy": {
        "find": r"(accuracy.*?(?=\d))(\d+|\d+\W\d+)(\s?)(/\s?10)",
        "extract": r"accuracy.*?(?=\d)",
        "score": r"/(\w?)10",
    },
}

# Load Airtable and Get Max UTC
print("\nInitializing Airtable Client... \n")
api = Api(AIRTABLE_API_KEY)
base = api.base(AIRTABLE_BASE_ID)
reviews_table = base.table(AIRTABLE_REVIEWS_TABLE)
brands_table = base.table("BRANDS")
sellers_table = base.table("SELLERS")
factories_table = base.table("FACTORIES")
styles_table = base.table("STYLES")

# Calculate max_utc based on LOOKBACK_DAYS and build existing records for deduplication state
print("Fetching historical records for deduplication and max_utc threshold...\n")

# Single bulk fetch to prevent rate limiting for maximum created_utc and existing ids
reviews_records = reviews_table.all(fields=["created_utc","id"])
df = pd.DataFrame(reviews_records)

if not df.empty and 'fields' in df.columns:
    reviews_df = pd.json_normalize(df.fields)
    utcs = reviews_df["created_utc"].dropna().to_list() if "created_utc" in reviews_df.columns else []
    max_utc_from_records = max(utcs) if utcs else 0
    # Secure existing IDs in an O(1) lookup set
    existing_ids = set(reviews_df["id"].dropna().to_list()) if "id" in reviews_df.columns else set()
else:
    max_utc_from_records = 0
    existing_ids = set()

print(f"Loaded {len(existing_ids)} existing record IDs into memory.")


if LOOKBACK_DAYS:
    lookback_utc = time.time() - (LOOKBACK_DAYS * 24 * 60 * 60)
    
    # If max_utc_from_records exists and is more recent than lookback, use it. Otherwise, use lookback_utc
    if max_utc_from_records > 0 and max_utc_from_records > lookback_utc:
        max_utc = max_utc_from_records
        print(f"Using max record UTC ({max_utc}) - more recent than {LOOKBACK_DAYS}-day lookback\n")
    else:
        max_utc = lookback_utc
        print(f"Using {LOOKBACK_DAYS}-day lookback (max_utc={max_utc})\n")
else:
    max_utc = max_utc_from_records
    print(f"Using last Airtable review (max_utc={max_utc})\n")

print(
    "Post replies enabled\n"
    if ENABLE_POST_REPLIES
    else "Post replies disabled (Airtable writes will still run)\n"
)

######################################################
######## LOAD REDDIT & SUBREDDIT
######################################################

def load_reddit():
    print("Initializing Reddit Client...")

    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        username=REDDIT_USERNAME,
        password=REDDIT_PASSWORD,
        user_agent=REDDIT_USER_AGENT,
    )

    print("Testing Reddit connection...")
    try:
        print("Logged in as:", reddit.user.me())
    except Exception as e:
        print("Reddit auth failed:", repr(e))
        raise
    print("Loading subreddit...")
    subreddit = reddit.subreddit("luxelife")
    print("Subreddit loaded.")
    return reddit, subreddit
reddit, subreddit = load_reddit()


################## HELPER FUNCTIONS ##################

### LOAD CARIDINAL OBJECT DATA ###
def load_cardinal_objects():
    # Load Brand Names
    brands_records = brands_table.all()
    df = pd.DataFrame(brands_records)
    brand_df = pd.json_normalize(df.fields)
    brand_df["Name & Aliases"] = brand_df.get("Name & Aliases", "").fillna("")
    brands_and_aliases = brand_df["Name & Aliases"].to_list()

    # Load Seller Names
    sellers_records = sellers_table.all()
    df = pd.DataFrame(sellers_records)
    seller_df = pd.json_normalize(df.fields)
    seller_df["Name & Aliases"] = seller_df.get("Name & Aliases", "").fillna("")
    sellers_and_aliases = seller_df["Name & Aliases"].to_list()

    # Load Factory Names
    factories_records = factories_table.all()
    df = pd.DataFrame(factories_records)
    factory_df = pd.json_normalize(df.fields)
    factory_df["Name & Aliases"] = factory_df.get("Name & Aliases", "").fillna("")
    factory_and_aliases = factory_df["Name & Aliases"].to_list()

    # Load Style Names
    styles_records = styles_table.all()
    df = pd.DataFrame(styles_records)
    style_df = pd.json_normalize(df.fields)
    style_df["Name & Aliases"] = style_df.get("Name & Aliases", "").fillna("")
    styles_and_aliases = style_df["Name & Aliases"].to_list()

    return (
        brands_and_aliases, brand_df,
        sellers_and_aliases, seller_df,
        styles_and_aliases, style_df,
        factory_and_aliases, factory_df,
    )


### Create data object once ###
(
    brands_and_aliases, brand_df,
    sellers_and_aliases, seller_df,
    styles_and_aliases, style_df,
    factory_and_aliases, factory_df,
) = load_cardinal_objects()

LOOKUPS = [
    (brands_and_aliases, FIELD_BRAND, brand_df),
    (sellers_and_aliases, FIELD_SELLER, seller_df),
    (styles_and_aliases, FIELD_STYLE, style_df),
    (factory_and_aliases, FIELD_FACTORY, factory_df),
]

def get_name(data, key):
    return data.get(key, {}).get("name")
def get_id(data, key):
    return data.get(key, {}).get("id")
def get_field(data, key):
    return data.get(key)

### Check Cardinal Objects (Seller, Brand, Factory, Style) ###


def match_cardinal_objects(cardinal_object_array, cardinal_object_type, df, title_lower, title_data):
    for name_alias_string in cardinal_object_array:
        for name in name_alias_string.split(", "):
            regex = rf"(?:\W|^){re.escape(name.lower())}(?:\W|$)"
            if re.search(regex, title_lower): # Search the title for name/alias
                row = df.loc[df["Name & Aliases"].str.contains(regex, case=False, regex=True)]
                title_data[cardinal_object_type] = {
                    "id": row["record_id"].to_list(),
                    "name": name,
                }

def parse_review_body(post_body):
    post_body = post_body or "" # Guard against None
    lower_body = post_body.lower() # Convert body to lowercase to make regex matching easier
    regex_data = {}

    for field, config in REGEX.items():
        match = re.search(config["find"], lower_body)
        if not match:
            continue

        if "extract" in config:
            raw_value = match.group(2) if match.groups() and len(match.groups()) >= 2 else match.group(1)
            # If this field is a score, normalize to a float and clamp to 10
            if "score" in config:
                try:
                    normalized = str(raw_value).replace(",", ".").strip()
                    num = float(normalized)
                    if num > 10:
                        num = 10.0
                    regex_data[field] = num
                except (ValueError, TypeError):
                    # Fall back to the raw string if conversion fails
                    regex_data[field] = raw_value
            else:
                regex_data[field] = raw_value
        else:
            regex_data[field] = match.group(0)

    return regex_data


### PARSE IMGUR ALBUM INTO INDIVIDUAL IMAGE LINKS ###


def parse_imgur_album(post_body, submission_id=None):
    imgur_images = []
    album_regex = r"https://imgur\.com/(?:a|gallery)/[^\s)\]]+"
    match = re.search(album_regex, post_body or "")

    if not match:
        return imgur_images

    imgur_url = match.group(0).rstrip(")]}>.,")
    path = urlparse(imgur_url).path
    album_hash = path.split("/")[-1].split("-")[-1]
    api_url = f"https://api.imgur.com/3/album/{album_hash}/images"

    try:
        response = imgur_api.get(api_url, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        print(f"Failed to fetch Imgur album for submission {submission_id}: {repr(e)}")
        return []

    if payload.get("success"):
        return payload["data"][:5]

    # API responded but indicated an error
    print(f"Imgur API returned an error for submission {submission_id}: {payload}")
    return []

### CREATE AIRTABLE RECORD ###

def build_airtable_record(submission, regex_data, title_data, imgur_images):

    record = {
        "title": submission.title,
        "url": submission.url,
        "author": submission.author.name if submission.author else None,
        "id": submission.id,
        "created_utc": submission.created_utc,
    }

    # Add parsed regex fields & linked Airtable record IDs
    record.update(regex_data)
    for field, value in title_data.items():
        record[field] = value["id"]

    # Map Imgur URLs directly to Airtable Attachment format
    if imgur_images:
        record[FIELD_ATTACHMENT] = [{"url": img.get("link")} for img in imgur_images if img.get("link")]
    
    return record


### CREATE PRE-FILL LINK ###

def build_prefill_link(reply_sharelink, record_id):
    prefill = "https://airtable.com/shrgaB9P7ktxOgdJJ"
    first = True
    for item, value in reply_sharelink.items():
        if value is None:
            continue
        separator = "?" if first else "&"
        encoded = ",".join(value) if isinstance(value, list) else str(value)
        safe = quote_plus(encoded)
        prefill += f"{separator}prefill_{item}={safe}"
        first = False
    prefill += f"&prefill_Review={quote_plus(str(record_id))}"
    return prefill


### CREATE REPLY OBJECTS ###

def build_reply_objects(title_data, new_record):
    reply_table = {
        FIELD_BRAND: get_name(title_data, FIELD_BRAND),
        FIELD_SELLER: get_name(title_data, FIELD_SELLER),
        FIELD_FACTORY: get_name(title_data, FIELD_FACTORY),
        FIELD_STYLE: get_name(title_data, FIELD_STYLE),
        FIELD_QUALITY: get_field(new_record, FIELD_QUALITY),
        FIELD_ACCURACY: get_field(new_record, FIELD_ACCURACY),
        FIELD_COMMUNICATION: get_field(new_record, FIELD_COMMUNICATION),
        FIELD_SATISFACTION: get_field(new_record, FIELD_SATISFACTION),
        FIELD_PRICE: None,
    }
    reply_sharelink = {
        FIELD_BRAND: get_id(title_data, FIELD_BRAND),
        FIELD_SELLER: get_id(title_data, FIELD_SELLER),
        FIELD_FACTORY: get_id(title_data, FIELD_FACTORY),
        FIELD_STYLE: get_id(title_data, FIELD_STYLE),
        FIELD_QUALITY: get_field(new_record, FIELD_QUALITY),
        FIELD_ACCURACY: get_field(new_record, FIELD_ACCURACY),
        FIELD_COMMUNICATION: get_field(new_record, FIELD_COMMUNICATION),
        FIELD_SATISFACTION: get_field(new_record, FIELD_SATISFACTION),
        FIELD_PRICE: None,
    }
    return reply_table, reply_sharelink


### CREATE REPLY TABLE ###

def build_reply_table(reply_table):
    headers = "|".join(reply_table.keys())
    divider = "".join(["|:-"] * len(reply_table))
    values = "|".join(str(v) if v is not None else " - " for v in reply_table.values())
    return "\n".join([headers, divider, values])

### CHECK IF RECORD ALREADY EXISTS ###


def record_exists(submission_id):
    """O(1) Deduplication Check against memory."""
    return submission_id in existing_ids

def bot_already_replied(submission):
    """Check if the bot has already left a top-level comment on this post."""
    submission.comments.replace_more(limit=0)
    for comment in submission.comments:
        if comment.author and comment.author.name == REDDIT_USERNAME:
            return True
    return False

### GET NEW POSTS ###

def get_reddit_post(submission):

    if submission.created_utc <= max_utc:
        return

    # Check if post already exists in deduplication memory
    if record_exists(submission.id):
        print(f"Post {submission.id} already exists. Skipping...\n")
        return

    if not submission.link_flair_text or "Review" not in submission.link_flair_text:
        return

    print(submission.title)
    title_lower = submission.title.lower()
    title_data = {}

    for aliases, field, dataframe in LOOKUPS:
        match_cardinal_objects(aliases, field, dataframe, title_lower, title_data)

    print(title_data)

    # PARSE POST BODY WITH REGEX
    regex_data = parse_review_body(submission.selftext)
    imgur_images = parse_imgur_album(submission.selftext, submission.id)
    new_record = build_airtable_record(submission, regex_data, title_data, imgur_images)

    # Push new recordto Airtable
    record = reviews_table.create(new_record, typecast=True)
    record_id = record["id"]

    # Immediately add to local state to prevent future duplicates on this run
    existing_ids.add(submission.id)

    reply_table, reply_sharelink = build_reply_objects(title_data, new_record)
    prefill = build_prefill_link(reply_sharelink, record_id)
    reply_table_str = build_reply_table(reply_table)

    print(reply_table_str)

    text_reply = (
      f"👋🏾 Hello, LuxeLife Bot here! This is a summary of your post. If this info looks incorrect or missing anything, please [update your submission via this form]({prefill}). \n\n *Please send mod mail if you encounter problems with this bot.* \n\n \n"
      + reply_table_str
    )

    if ENABLE_POST_REPLIES:
        if bot_already_replied(submission):
            print(f"Bot already replied to {submission.id}. Skipping comment.\n")
        else:
            try:
                comment = submission.reply(body=text_reply)
                try:
                    comment.mod.distinguish(sticky=True)
                    print(f"✓ Reply posted and stickied for {submission.id}\n")
                except Exception as mod_err:
                    print(f"✓ Reply posted, but could not sticky (Missing mod privileges). {mod_err}\n")
            except Exception as reply_err:
                print(f"Failed to post Reddit reply for {submission.id}: {reply_err}\n")
    else:
        print("Skipping Reddit reply (ENABLE_POST_REPLIES=false)\n")


### GET POST DETAILS ####
def process_submission(submission):
    try:
        get_reddit_post(submission)
    except Exception as e:
        print(f"Failed processing {submission.id}: {e}")
        traceback.print_exc()

######################################################
######## RUNTIME
######################################################

if LOOKBACK_DAYS:
    print("Starting backfill...")

    # Backfill recent posts instead of waiting on the live stream
    for submission in subreddit.new(limit=50):
        if submission.created_utc <= max_utc:
            break
        process_submission(submission)
else:
    for submission in subreddit.stream.submissions():
        process_submission(submission)