# Import libraries
import praw  # Manage the Reddit API
from pyairtable import Api  # Manage the Airtable API
import os # from datetime import date to manage dates
import re # from datetime import date to manage regex

import time # for timing
import requests  # Manage key functionality
import pandas as pd  # Easily work with tabular data
import html # for grabbing Reddit images
import mimetypes # for file uploads
import traceback # for debugging
import tempfile # for mega downloads
import shutil # for mega cleanup
from urllib.parse import urlparse, quote_plus
from dotenv import load_dotenv

# NEW DEPENDENCIES: pip install beautifulsoup4 mega.py
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
    print("Warning: beautifulsoup4 not installed. ibb.co albums won't be fully parsed.")

try:
    from mega import Mega
except ImportError:
    Mega = None
    print("Warning: mega.py not installed. mega.nz links won't be downloaded.")

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

ENABLE_POST_REPLIES = os.environ.get("ENABLE_POST_REPLIES", "true").lower() in (
    "true",
    "1",
    "yes",
)

# If set, script runs in Backfill mode. If missing/empty, runs in Daily Cron mode.
LOOKBACK_DAYS = os.environ.get("REVIEW_LOOKBACK_DAYS")
if LOOKBACK_DAYS:
    LOOKBACK_DAYS = int(LOOKBACK_DAYS)

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
        "extract": r"communication.*?(?=\d)",
        "score": r"/(\w?)10",
    },
    "Satisfaction": {
        "find": r"(satisfaction.*?(?=\d))(\d+|\d+\W\d+)(\s?)(/\s?10)",
        "extract": r"satisfaction.*?(?=\d)",
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

print("\nInitializing Airtable Client... \n")
api = Api(AIRTABLE_API_KEY)
base = api.base(AIRTABLE_BASE_ID)
reviews_table = base.table(AIRTABLE_REVIEWS_TABLE)
brands_table = base.table("BRANDS")
sellers_table = base.table("SELLERS")
factories_table = base.table("FACTORIES")
styles_table = base.table("STYLES")

if LOOKBACK_DAYS:
    print(f"BACKFILL MODE: Fetching all historical records for deep deduplication...\n")
    reviews_records = reviews_table.all(fields=["id"])
    most_recent_utc = 0 
else:
    print("CRON MODE: Fetching recent records for daily sync deduplication...\n")
    two_days_ago_utc = int(time.time()) - (2 * 24 * 60 * 60)
    # Target only records from the last 48 hours based on their created_utc number field
    formula = f"{{created_utc}} >= {two_days_ago_utc}"
    reviews_records = reviews_table.all(fields=["id", "created_utc"], formula=formula)
    
    df_recent = pd.DataFrame(reviews_records)
    if not df_recent.empty and 'fields' in df_recent.columns:
        recent_df = pd.json_normalize(df_recent.fields)
        utcs = recent_df["created_utc"].dropna().to_list() if "created_utc" in recent_df.columns else []
        most_recent_utc = max(utcs) if utcs else 0
    else:
        most_recent_utc = 0

# Extract existing IDs for O(1) lookup
df = pd.DataFrame(reviews_records)
if not df.empty and 'fields' in df.columns:
    reviews_df = pd.json_normalize(df.fields)
    existing_ids = set(reviews_df["id"].dropna().to_list()) if "id" in reviews_df.columns else set()
else:
    existing_ids = set()

print(f"Loaded {len(existing_ids)} existing record IDs into memory.\n")
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

######################################################
######## HELPER FUNCTIONS
######################################################

### LOAD REFERENCE LISTS ###

def load_cardinal_objects():
    brands_records = brands_table.all()
    df = pd.DataFrame(brands_records)
    brand_df = pd.json_normalize(df.fields)
    brand_df["Name & Aliases"] = brand_df.get("Name & Aliases", "").fillna("")
    brands_and_aliases = brand_df["Name & Aliases"].to_list()

    sellers_records = sellers_table.all()
    df = pd.DataFrame(sellers_records)
    seller_df = pd.json_normalize(df.fields)
    seller_df["Name & Aliases"] = seller_df.get("Name & Aliases", "").fillna("")
    sellers_and_aliases = seller_df["Name & Aliases"].to_list()

    factories_records = factories_table.all()
    df = pd.DataFrame(factories_records)
    factory_df = pd.json_normalize(df.fields)
    factory_df["Name & Aliases"] = factory_df.get("Name & Aliases", "").fillna("")
    factory_and_aliases = factory_df["Name & Aliases"].to_list()

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

def match_cardinal_objects(cardinal_object_array, cardinal_object_type, df, title_lower, title_data):
    for name_alias_string in cardinal_object_array:
        if not name_alias_string or str(name_alias_string).strip() == "":
            continue
            
        for name in name_alias_string.split(", "):
            name = name.strip() 
            if not name:
                continue
                
            regex = rf"(?:\W|^){re.escape(name.lower())}(?:\W|$)"
            
            if re.search(regex, title_lower):
                row = df.loc[df["Name & Aliases"].str.contains(regex, case=False, regex=True)]
                title_data[cardinal_object_type] = {
                    "id": row["record_id"].to_list(),
                    "name": name,
                }

def parse_review_body(post_body):
    post_body = post_body or "" 
    lower_body = post_body.lower() 
    regex_data = {}

    for field, config in REGEX.items():
        match = re.search(config["find"], lower_body)
        if not match:
            continue

        if "extract" in config:
            raw_value = match.group(2) if match.groups() and len(match.groups()) >= 2 else match.group(1)
            if "score" in config:
                try:
                    normalized = str(raw_value).replace(",", ".").strip()
                    num = float(normalized)
                    if num > 10:
                        num = 10.0
                    regex_data[field] = num
                except (ValueError, TypeError):
                    regex_data[field] = raw_value
            else:
                regex_data[field] = raw_value
        else:
            regex_data[field] = match.group(0)

    return regex_data

### PARSE MEGA.NZ IMAGES ###

def parse_mega_images(post_body, submission_id=None):
    mega_images = []
    if not post_body or not Mega:
        return mega_images
        
    mega_links = re.findall(r"https://mega\.nz/(?:file|folder)/[a-zA-Z0-9_-]+#[a-zA-Z0-9_-]+", post_body)
    if not mega_links:
        return mega_images

    mega_api = Mega()
    try:
        m = mega_api.login()
    except Exception as e:
        print(f"Failed to login to Mega: {e}")
        return mega_images

    # Create temporary directory to safely store and stream the decrypted file to Airtable
    temp_dir = tempfile.mkdtemp()

    try:
        for link in mega_links[:3]: # Limit to prevent overwhelming downloads
            try:
                downloaded_path = m.download_url(link, dest_path=temp_dir)
                if downloaded_path:
                    # Convert pathlib object to a standard string for compatibility
                    downloaded_path = str(downloaded_path)
                    
                    if os.path.exists(downloaded_path):
                        if os.path.isfile(downloaded_path): # Individual File
                            if downloaded_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                filename = os.path.basename(downloaded_path)
                                with open(downloaded_path, 'rb') as f:
                                    mega_images.append({"id": f"mega_{filename}", "content": f.read(), "filename": filename})
                                    
                        elif os.path.isdir(downloaded_path): # Full Folder
                            for root, _, files in os.walk(downloaded_path):
                                for file in files:
                                    if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                        full_path = os.path.join(root, file)
                                        with open(full_path, 'rb') as f:
                                            mega_images.append({"id": f"mega_{file}", "content": f.read(), "filename": file})
                                            if len(mega_images) >= 10: 
                                                break
                                if len(mega_images) >= 10:
                                    break
            except Exception as e:
                print(f"Failed to process Mega link {link} for submission {submission_id}: {e}")
    finally:
        # Wipe the decrypted temp storage after saving bytes to memory
        shutil.rmtree(temp_dir, ignore_errors=True)

    return mega_images

### PARSE IBB.CO IMAGES ###

def parse_ibb_images(post_body, submission_id=None):
    ibb_images = []
    if not post_body or not BeautifulSoup:
        return ibb_images

    album_links = re.findall(r"https://ibb\.co/album/[a-zA-Z0-9]+", post_body)
    single_links = re.findall(r"https://ibb\.co/(?!album/)[a-zA-Z0-9]+", post_body)

    for album_url in album_links:
        try:
            res = requests.get(album_url, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                # Grab all images linked in the album
                for a in soup.find_all('a', href=re.compile(r"https://ibb\.co/(?!album/)[a-zA-Z0-9]+")):
                    single_links.append(a['href'])
        except Exception as e:
            print(f"Failed to fetch IBB album {album_url}: {e}")

    # Remove duplicates
    single_links = list(set(single_links))

    for link in single_links[:10]:
        try:
            res = requests.get(link, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                meta = soup.find('meta', property='og:image') or soup.find('link', rel='image_src')
                if meta:
                    raw_url = meta.get('content') or meta.get('href')
                    img_id = link.split('/')[-1]
                    ibb_images.append({"id": f"ibb_{img_id}", "link": raw_url})
        except Exception as e:
            print(f"Failed to fetch IBB image {link}: {e}")

    return ibb_images

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

    print(f"Imgur API returned an error for submission {submission_id}: {payload}")
    return []

### PARSE REDDIT GALLERY OR IMAGE ###

def parse_reddit_images(submission):
    images = []
    if hasattr(submission, "is_gallery") and submission.is_gallery:
        if hasattr(submission, "media_metadata"):
            for media_id, media_info in submission.media_metadata.items():
                if media_info.get("status") == "valid":
                    if "s" in media_info and "u" in media_info["s"]:
                        raw_url = html.unescape(media_info["s"]["u"])
                        images.append({"id": media_id, "link": raw_url})
                    elif "s" in media_info and "gif" in media_info["s"]:
                        raw_url = html.unescape(media_info["s"]["gif"])
                        images.append({"id": media_id, "link": raw_url})
                        
    elif hasattr(submission, "post_hint") and submission.post_hint == "image":
        media_id = f"{submission.id}_single"
        images.append({"id": media_id, "link": submission.url})

    return images

### PREPARE ATTACHMENT UPLOAD ###

def upload_attachments(record_id, images, submission_id=None):
    if not images:
        return
    
    print(f"[{submission_id}] Processing {len(images)} images to push directly to Airtable...")

    if hasattr(reviews_table, "upload_attachment"):
        for image in images:
            try:
                # If image content is already downloaded (e.g. Mega)
                if image.get("content"):
                    filename = image.get("filename", f"{image.get('id')}.jpg")
                    content_type = mimetypes.guess_type(filename)[0] or "image/jpeg"
                    
                    reviews_table.upload_attachment(
                        record_id,
                        FIELD_ATTACHMENT,
                        filename,
                        content=image.get("content"),
                        content_type=content_type,
                    )
                    print(f"✓ Uploaded {filename} to record {record_id} via content bytes")

                # If image is a remote URL to be downloaded
                else:
                    link = image.get("link")
                    if not link:
                        continue
                        
                    print(f"Uploading {link} for submission {submission_id}")

                    image_response = imgur_cdn.get(link, timeout=30)
                    if image_response.status_code == 200:
                        content_type = image_response.headers.get("Content-Type", "image/jpeg")
                        extension = mimetypes.guess_extension(content_type) or ".jpg"
                        filename = f"{image.get('id')}{extension}"

                        reviews_table.upload_attachment(
                            record_id,
                            FIELD_ATTACHMENT,
                            filename,
                            content=image_response.content,
                            content_type=content_type,
                        )
                        print(f"✓ Uploaded {filename} to record {record_id}")
                    else:
                        print(f"Failed to download image for submission {submission_id}: HTTP {image_response.status_code}")
                    
            except Exception as e:
                print(f"Failed to upload attachment for record {record_id}, submission {submission_id}: {repr(e)}")
    else: 
        # Fallback: attach remote URLs via an update (Will not work for Mega images passed via local content bytes)
        try:
            attachments = []
            for image in images:
                link = image.get("link")
                if link:
                    attachments.append({"url": link})
            if attachments:
                reviews_table.update(record_id, {FIELD_ATTACHMENT: attachments})
                print(f"✓ Attached {len(attachments)} URLs to record {record_id} (fallback)")
        except Exception as e:
            print(f"Failed to attach URLs for record {record_id}, submission {submission_id}: {repr(e)}")


### CREATE AIRTABLE RECORD ###

def build_airtable_record(submission, regex_data, title_data, imgur_images):
    record = {
        "title": submission.title,
        "url": submission.url,
        "author": submission.author.name if submission.author else None,
        "id": submission.id,
        "created_utc": submission.created_utc,
    }

    record.update(regex_data)
    for field, value in title_data.items():
        record[field] = value["id"]

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

### CREATE POST REPLY OBJECTS ###
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

######################################################
######## CORE PROCESSING LOGIC
######################################################

### GET NEW POSTS ###

def get_reddit_post(submission):

    if submission.link_flair_text != "Review":
        return

    if record_exists(submission.id):
        print(f"Post {submission.id} already exists. Skipping...\n")
        return

    print(submission.title)
    title_lower = submission.title.lower()
    title_data = {}

    for aliases, field, dataframe in LOOKUPS:
        match_cardinal_objects(aliases, field, dataframe, title_lower, title_data)

    print(title_data)

    # PARSE POST BODY WITH REGEX
    regex_data = parse_review_body(submission.selftext)
    
    # We pass an empty list for imgur_images initially to the record builder
    # since we upload them via the dedicated pyairtable attachment method below
    new_record = build_airtable_record(submission, regex_data, title_data, [])

    # Push new record text to Airtable
    record = reviews_table.create(new_record, typecast=True)
    record_id = record["id"]
    
    # Immediately add to local state to prevent future duplicates on this run
    existing_ids.add(submission.id)
    print(f"[{submission.id}] Base text record created in Airtable.")

    # Extract images from all supported sources
    reddit_images = parse_reddit_images(submission)
    imgur_images = parse_imgur_album(submission.selftext, submission.id)
    ibb_images = parse_ibb_images(submission.selftext, submission.id)
    mega_images = parse_mega_images(submission.selftext, submission.id)
    
    all_images = (reddit_images + imgur_images + ibb_images + mega_images)[:10]
    
    if all_images:
        upload_attachments(record_id, all_images, submission.id)

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
                # ROLLBACK: If reply fails (e.g., rate limit), delete Airtable record so cron retries it
                print(f"Failed to post Reddit reply for {submission.id}: {reply_err}")
                print(f"Rolling back Airtable record {record_id} to ensure retry on next run...\n")
                reviews_table.delete(record_id)
                existing_ids.remove(submission.id)
                return 
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
    print(f"Starting chunked backfill for the last {LOOKBACK_DAYS} days...")
    backfill_cutoff_utc = time.time() - (LOOKBACK_DAYS * 24 * 60 * 60)

    characters = list("zqxjkvbpygfwmuclrhsnioate0123456789")
    queries = [f'flair:"Review" AND title:{char}' for char in characters]
    queries.append('flair:"Review"') 

    for query in queries:
        print(f"Executing backfill query: {query}")
        for submission in subreddit.search(query, sort='new', limit=1000):
            if submission.created_utc < backfill_cutoff_utc:
                continue 
            process_submission(submission)

else:
    print("Starting daily cron sync...")
    for submission in subreddit.new(limit=200):
        if submission.created_utc <= most_recent_utc:
            print("Reached already-processed posts. Daily sync complete.")
            break 
            
        process_submission(submission)