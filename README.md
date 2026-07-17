# Reddit Review Bot

An automated bot that monitors a private subreddit for flaired review posts, extracts structured review data, and organizes it into an Airtable database.

## Overview

This bot monitors a specified private subreddit for posts with a "Review" flair, extracts structured review metadata from post titles and bodies, and automatically creates organized records in Airtable with:

- **Extracted metadata**: Brands, styles, and other categories identified via regex and fuzzy matching against lookup tables
- **Review scores**: Ratings (quality, accuracy, communication, satisfaction, etc.) parsed from post content
- **Contact information**: Links and identifiers automatically extracted via regex patterns
- **Media attachments**: Images from multiple sources (Reddit native, Imgur albums, ibb.co, Mega.nz)
- **Automated replies**: Posts receive a bot reply with a summary table and prefilled form link for corrections

## Features

### Post Processing
- **Daily cron mode**: Syncs the last 48 hours of new posts to Airtable for incremental updates
- **Backfill mode**: Deep historical scan across configurable time windows with deduplication
- **Deduplication**: O(1) memory-based lookup prevents duplicate records in Airtable

### Data Extraction
- **Title parsing**: Matches post titles against Airtable lookup tables for categories
- **Review metrics**: Extracts numerical scores for various rating fields (out of 10)
- **Contact information**: Finds identifiers, contact handles, and links via regex patterns

### Multi-Source Image Handling
- **Reddit native**: Extracts gallery media and direct image posts
- **Imgur albums**: Parses Imgur album URLs and downloads up to 5 images
- **ibb.co**: Scrapes ibb.co album pages for linked images
- **Mega.nz**: Downloads encrypted Mega files with automatic cleanup
- **Safe uploads**: All images are uploaded directly to Airtable with proper MIME type detection

### Post Replies
- **Smart replies**: Generates markdown tables summarizing extracted data
- **Prefilled forms**: Creates Airtable form links with post data preloaded for user corrections
- **Sticky comments**: Attempts to sticky bot replies for visibility (requires mod privileges)
- **Deduplication**: Skips reply if bot has already commented to avoid spam

## Setup

### Prerequisites
- Python 3.8+
- Airtable account with a configured base
- Reddit app credentials (via Reddit's app preferences)
- (Optional) Imgur API credentials for album parsing

### Installation

1. Clone the repository:
```bash
git clone https://github.com/phranklins/luxe-life-bot.git
cd luxe-life-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your credentials:
```env
# Reddit API
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USERNAME=your_bot_username
REDDIT_PASSWORD=your_bot_password
REDDIT_USER_AGENT=your_user_agent

# Airtable API
AIRTABLE_API_KEY=your_api_key
AIRTABLE_BASE_ID=your_base_id
AIRTABLE_REVIEWS_TABLE=Reviews

# Imgur API (optional)
IMGUR_CLIENT_ID=your_imgur_client_id
IMGUR_CLIENT_SECRET=your_imgur_client_secret
IMGUR_USER_AGENT=your_user_agent

# Configuration (optional)
ENABLE_POST_REPLIES=true
REVIEW_LOOKBACK_DAYS=  # Leave empty for daily cron, set to number of days for backfill
```

### Airtable Base Setup

Create the following tables in your Airtable base:

- **Reviews**: Main table for review records
  - `id` (Text): Reddit post ID
  - `title` (Text): Post title
  - `url` (Text): Reddit post URL
  - `author` (Text): Post author
  - `created_utc` (Number): Unix timestamp
  - `Brand` (Link to BRANDS table): Reference lookup
  - `STYLES` (Link to STYLES table): Reference lookup
  - Custom rating fields as needed (Quality, Accuracy, Communication, Satisfaction, etc.) — all Number type
  - `attachment` (Attachments): Images

- **BRANDS**: Lookup table with `Name & Aliases` field (comma-separated values)
- **STYLES**: Lookup table with `Name & Aliases` field
- Additional lookup tables for your custom categories (mirror the LOOKUPS array in main.py)

## Running the Bot

### Local Testing
```bash
python main.py
```

### Daily Sync (Cron Mode)
For automatic daily syncs, run the bot on a schedule:
```bash
python main.py
```

With no `REVIEW_LOOKBACK_DAYS` set, the bot increments only new posts from the last 48 hours.

### Backfill Mode
Run a historical scan by setting the environment variable:
```bash
REVIEW_LOOKBACK_DAYS=30 python main.py
```

This scans and deduplicates all posts from the last 30 days, useful for initial population or recovery after downtime.

## How It Works

### Daily Flow
1. Bot loads recent records from Airtable (last 48 hours)
2. Fetches new posts from the subreddit with "Review" flair
3. For each post:
   - Parses title to match against category lookup tables
   - Extracts review scores from post body via regex
   - Collects contact information and links
   - Downloads images from multiple sources
   - Creates Airtable record with all extracted data
   - Posts a reply with summary table and feedback form link
4. Deduplication prevents re-processing of existing records

### Image Processing
- Reddit gallery/image posts are directly captured
- Imgur album URLs are resolved to individual images via API
- ibb.co albums are scraped and images extracted
- Mega.nz files are decrypted and downloaded (images only, max 10)
- All images are uploaded to Airtable with original filenames

### Data Extraction
- **Regex patterns** identify review scores, contact methods, and links
- **Fuzzy matching** against Airtable lookup tables finds categories
- **Cardinal objects** support aliases for flexible matching

## Configuration

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `REDDIT_CLIENT_ID` | Yes | - | Reddit app client ID |
| `REDDIT_CLIENT_SECRET` | Yes | - | Reddit app secret |
| `REDDIT_USERNAME` | Yes | - | Bot Reddit username |
| `REDDIT_PASSWORD` | Yes | - | Bot Reddit password |
| `REDDIT_USER_AGENT` | Yes | - | Bot user agent string |
| `AIRTABLE_API_KEY` | Yes | - | Airtable personal access token |
| `AIRTABLE_BASE_ID` | Yes | - | Airtable base ID |
| `AIRTABLE_REVIEWS_TABLE` | Yes | - | Name of reviews table |
| `IMGUR_CLIENT_ID` | No | - | Imgur API client ID |
| `IMGUR_CLIENT_SECRET` | No | - | Imgur API secret |
| `IMGUR_USER_AGENT` | No | - | Imgur user agent |
| `ENABLE_POST_REPLIES` | No | `true` | Post replies to Reddit |
| `REVIEW_LOOKBACK_DAYS` | No | `` | Empty for cron mode; set days for backfill |

### Customizing Lookups

Edit the `main.py` file to customize which categories are extracted. The `LOOKUPS` array defines the lookup tables and regex patterns:

```python
LOOKUPS = [
    (brands_and_aliases, FIELD_BRAND, brand_df),
    (styles_and_aliases, FIELD_STYLE, style_df),
    # Add more as needed
]
```

Update the `REGEX` dictionary to customize which metrics and contact info are extracted from post bodies.

## Troubleshooting

### Images not uploading
- Verify `beautifulsoup4` and `mega.py-v2` are installed for ibb.co and Mega support
- Check Airtable API key has attachment upload permissions
- Inspect logs for specific service failures (Imgur, ibb.co, Mega)

### Duplicate records appearing
- Run a backfill with `REVIEW_LOOKBACK_DAYS` set to clear stale cache and re-deduplicate
- Check that the `created_utc` formula in Airtable is filtering correctly

### Bot replies not posting
- Verify `ENABLE_POST_REPLIES=true` in `.env`
- Ensure bot account has posting permissions in the subreddit
- Check Reddit API credentials and rate limits

### Rollback on reply failure
- If a Reddit reply fails (e.g., rate limit), the Airtable record is automatically deleted so the post can be retried on the next run
- This prevents orphaned records without corresponding Reddit replies

## Dependencies

- **praw** (8.0.2): Reddit API wrapper
- **pyairtable** (3.4.0): Airtable API client
- **pandas** (3.0.3): Data manipulation and deduplication
- **requests** (2.34.2): HTTP client for APIs
- **beautifulsoup4**: HTML parsing for ibb.co albums
- **mega.py-v2**: Mega.nz file decryption and download
- **python-dotenv** (1.2.2): Environment variable management

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
