# Import libraries
import praw  # Mananage the Reddit API
# Handle exceptions from the Reddit API
from prawcore.exceptions import PrawcoreException
from pyairtable import Api  # Manage the Airtable API
from datetime import date  # Manage Dates
import os
import re
import json
import time
import requests  # Manage key functionality

import pprint
import pandas as pd  # Easily work with tabular data
from operator import indexOf
from dotenv import load_dotenv

pp = pprint.PrettyPrinter(indent=4)

# Get Variables from .env
load_dotenv()
REDDIT_CLIENT_ID = os.environ.get('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.environ.get('REDDIT_CLIENT_SECRET')
REDDIT_PASSWORD = os.environ.get('REDDIT_PASSWORD')
REDDIT_USERNAME = os.environ.get('REDDIT_USERNAME')
REDDIT_USER_AGENT = os.environ.get('REDDIT_USER_AGENT')

AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID')
AIRTABLE_REVIEWS_TABLE = os.environ.get('AIRTABLE_REVIEWS_TABLE')

IMGUR_CLIENT_ID = os.environ.get('IMGUR_CLIENT_ID')
IMGUR_CLIENT_SECRET = os.environ.get('IMGUR_CLIENT_SECRET')

# Load Airtable and Get Max UTC
print('\nInitializing Airtable Client... \n')
api = Api(AIRTABLE_API_KEY)
base = api.base(AIRTABLE_BASE_ID)
reviews_table = base.table(AIRTABLE_REVIEWS_TABLE)
brands_table = base.table('BRANDS')
sellers_table = base.table('SELLERS')
factories_table = base.table('FACTORIES')
styles_table = base.table('STYLES')

reviews_records = reviews_table.all(fields=['created_utc'])
df = pd.DataFrame(reviews_records)
reviews_df = pd.json_normalize(df.fields)
utcs = reviews_df['created_utc'].to_list()
max_utc = max(utcs)

# LOAD REDDIT & SUBREDDIT


def load_reddit():
    print('Initializing Reddit Client... \n')
    global reddit
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        password=REDDIT_PASSWORD,
        user_agent=REDDIT_USER_AGENT,
        username=REDDIT_USERNAME,
    )
    global subreddit
    subreddit = reddit.subreddit('luxelife')


load_reddit()

### LOAD CARIDINAL OBJECT DATA ###


def load_cardinal_objects():
    # Load Brand Names
    brands_records = brands_table.all()
    df = pd.DataFrame(brands_records)
    brand_df = pd.json_normalize(df.fields)
    brands_and_aliases = brand_df['Name & Aliases'].to_list()

    # Load Seller Names
    sellers_records = sellers_table.all()
    df = pd.DataFrame(sellers_records)
    seller_df = pd.json_normalize(df.fields)
    sellers_and_aliases = seller_df['Name & Aliases'].to_list()

    # Load Factory Names
    factories_records = factories_table.all()
    df = pd.DataFrame(factories_records)
    factory_df = pd.json_normalize(df.fields)
    factory_and_aliases = factory_df['Name & Aliases'].to_list()

    # Load Style Names
    styles_records = styles_table.all()
    df = pd.DataFrame(styles_records)
    style_df = pd.json_normalize(df.fields)
    styles_and_aliases = style_df['Name & Aliases'].to_list()

    return brands_and_aliases, brand_df, sellers_and_aliases, seller_df, styles_and_aliases, style_df, factory_and_aliases, factory_df

### GET NEW POSTS ###


def get_reddit_post(submission):

    if submission.created_utc > max_utc and submission.link_flair_text:

        if "Review" in submission.link_flair_text:  # Filter only Review Posts

            print(submission.title)

            # Check Cardinal Objects (Seller, Brand, Factory, Style)
            def name_checker(cardinal_object_array, cardinal_object_type, df):

                for name_alias_string in cardinal_object_array:

                    name_array = name_alias_string.split(', ')

                    for name in name_array:

                        regex = '(\W|^)' + re.escape(name.lower()) + '(\W|$)'
                        # Search the title for name/alias
                        hasName = re.search(regex, title_lower)

                        if hasName:

                            row = df.loc[df['Name & Aliases'].str.contains(
                                regex, case=False, regex=True)]
                            title_data[cardinal_object_type] = {
                                'id': row['record_id'].to_list(), 'name': name}

            # Check for Cardinal Objects in the Post Title
            title = submission.title
            title_lower = title.lower()
            title_data = {}  # Create an empty object to add Cardinal Object information
            brands_and_aliases, brand_df, sellers_and_aliases, seller_df, styles_and_aliases, style_df, factory_and_aliases, factory_df = load_cardinal_objects()
            name_checker(brands_and_aliases, "Brand", brand_df)
            name_checker(sellers_and_aliases, "Seller", seller_df)
            name_checker(styles_and_aliases, "STYLES", style_df)
            name_checker(factory_and_aliases, 'Factory', factory_df)

            print(title_data)

        # PARSE POST BODY WITH REGEX

            # Convert body to lowercase to make regex matching easier
            text = submission.selftext
            lowerBody = text.lower()

            # Create an object for all things we're regexing
            # Note: Extract and Score should be deprecated in the next update. Currently they're used to indicate whether a string needs further extraction
            regex = {
                "WeChat": {
                    "find": "(wechat\W*)((\w|\d)*)",
                    "extract": "wechat\W*"
                },
                "WhatsApp": {
                    "find": "(whatsapp\W*)((?:\s*\d|\W){13})",
                    "extract": "whatsapp\W*"
                },
                # "email": { "find": "([a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+\.[a-zA-Z0-9_-]+)/gi" },
                "Yupoo": {
                    "find": "https:\/\/\w*.\w.yupoo\.com.*?(?=\))"
                },
                "Szwego": {
                    "find":
                    'https:\/\/s.wsxc.cn\/.*?(?=\]|\))|(?=https:\/\/).*szwego.com.*?(?=\s)'
                },
                # "currency": { "find": "[\$￥¥]|rmb|usd|cny","compute": "test"},
                # "price-string": {"find": "(?!=\$)\d+.?\d+|\d+.?\d+(?!=cny|usd)"},
                "Communication": {
                    "find": "(communication.*?(?=\d))(\d+|\d+\W\d+)(\s?\/(\s?)10)",
                    "extract": "(?<=communication).*?(?=\d)",
                    "score": "\/(\w?)10"
                },
                "Satisfaction": {
                    "find": "(satisfaction.*?(?=\d))(\d+|\d+\W\d+)(\s?\/\s?)10",
                    "extract": "(satisfaction).*?(?=\d)",
                    "score": "\/(\w?)10"
                },
                "Quality": {
                    "find": "(quality.*?(?=\d))(\d+|\d+\W\d+)(\s?)(\/\s?10)",
                    "extract": "quality.*?(?=\d)",
                    "score": "\/(\w?)10"
                },
                "Accuracy": {
                    "find": "(accuracy.*?(?=\d))(\d+|\d+\W\d+)(\s?)(\/\s?10)",
                    "extract": "accuracy.*?(?=\d)",
                    "score": "\/(\w?)10"
                }
            }

            # Create an empty object to add parsed data

            my_obj = {}

            # For each item in the regex dictionary
            for item in regex.items():

                find = item[1]['find']  # Substring
                # Check to see if there's a match
                match = re.search(find, lowerBody)

                # Check to see if there are any substrings based off the find parameters
                if match:

                    # If extract exists, get the second group from the regex
                    if "extract" in item[1].keys():

                        my_obj[item[0]] = match.group(2)

                        # If an item is a "Score" get the numerical value. Calibrate for values > 10
                        if "score" in item[1].keys():

                            try:
                                my_str = my_obj[item[0]].replace(",", ".")
                                my_obj[item[0]] = 10 if float(
                                    my_str) > 10 else float(my_str)
                            except ValueError:
                                break

                    # Else, pull the find sbustring
                    else:
                        my_obj[item[0]] = match.group(0)

        # CREATE NEW RECORD OBJECT TO UPLOAD
            # Create New Record Object:
            new_record = {
                'title': submission.title,
                'url': submission.url,
                'author': submission.author.name if submission.author else None,
                'id': submission.id,
                'created_utc': submission.created_utc,
                # 'created time': str(date.today()),
            }

            # Add Regex Items to new_record obj
            for item in my_obj.items():
                new_record[item[0]] = item[1]

            # Add Cardinal Objects to new_record obj
            for item in title_data.items():
                new_record[item[0]] = item[1]['id']

            # Get All Imgur Links in Post
            albumRegex = "https:\/\/imgur.com\/\w\/(\w+|\d+)"
            albumMatch = re.search(albumRegex, submission.selftext)

            if albumMatch:
                imgur_url = albumMatch.group(0)
                match_type = "Gallery" if "gallery" in imgur_url else "Album"
                album_hash = re.search("(?<=https://imgur.com/a/).*", imgur_url).group(
                    0) if re.search("(?<=https://imgur.com/a/).*", imgur_url) else None

                if album_hash:
                    api_url = f'https://api.imgur.com/3/album/{album_hash}/images'
                    headers = {
                        'Authorization': f'Client-ID {IMGUR_CLIENT_ID}',
                        'User-Agent': REDDIT_USER_AGENT,
                    }
                    request = requests.get(api_url, headers=headers)
                    if request:
                        response = request.json()
                        data = response['data']
                        attachments = []
                        for x in data:
                            my_obj = {'url': x['link']}
                            attachments.append(my_obj)
                        new_record['attachment'] = attachments[0:5]

            # Create New Records in Airtable
            record = reviews_table.create(new_record, typecast=True)
            record_id = record['id']

            # Create Reply Text and Table
            reply_table = {
                "Brand": title_data['Brand']['name'] if "Brand" in title_data.keys() else None,
                "Seller": title_data['Seller']['name'] if "Seller" in title_data.keys() else None,
                "Factory": title_data['Factory']['name'] if "Factory" in title_data.keys() else None,
                "Style": title_data['STYLES']['name'] if "STYLES" in title_data.keys() else None,
                'Quality': new_record['Quality'] if "Quality" in new_record.keys() else None,
                'Accuracy': new_record['Accuracy'] if "Accuracy" in new_record.keys() else None,
                'Communication': new_record['Communication'] if "Communication" in new_record.keys() else None,
                'Satisfaction': new_record['Satisfaction'] if "Satisfaction" in new_record.keys() else None,
                'Price': None
            }

            # Create Share Link to Update Posts
            reply_sharelink = {
                "Brand": title_data['Brand']['id'] if "Brand" in title_data.keys() else None,
                "Seller": title_data['Seller']['id'] if "Seller" in title_data.keys() else None,
                "Factory": title_data['Factory']['id'] if "Factory" in title_data.keys() else None,
                "Style": title_data['STYLES']['id'] if "STYLES" in title_data.keys() else None,
                'Quality': new_record['Quality'] if "Quality" in new_record.keys() else None,
                'Accuracy': new_record['Accuracy'] if "Accuracy" in new_record.keys() else None,
                'Communication': new_record['Communication'] if "Communication" in new_record.keys() else None,
                'Satisfaction': new_record['Satisfaction'] if "Satisfaction" in new_record.keys() else None,
                'Price': None
            }

            # Create Prefill Link
            # URL ENCODE!
            prefill = 'https://airtable.com/shrgaB9P7ktxOgdJJ'
            for item, value in reply_sharelink.items():

                keys = list(reply_sharelink.keys())

                if keys.index(item) == 0 and item[1] is not None:

                    my_string = f"?prefill_{item}={','.join(value) if isinstance(value, list) else value}"
                else:
                    try:
                        my_string = f"&prefill_{item}={','.join(value) if isinstance(value, list) else value}"
                    except TypeError:
                        break

                prefill = prefill+my_string

            # Add Record ID to prefill
            prefill = prefill+f"&prefill_Review={record_id}"
            reply_table_headers = "|".join(reply_table.keys())
            reply_table_divider = "".join(
                ["|:-" for x in list(reply_table.keys())])
            reply_table_values = [str(x) if x is not None in list(
                reply_table.values()) else " - " for x in list(reply_table.values())]
            reply_table_values = "|".join(reply_table_values)
            reply_table = "\n".join(
                [reply_table_headers, reply_table_divider, reply_table_values])
            print(reply_table)

            text_reply = f"👋🏾 Hello, LuxeLife Bot here! These are the results of your post. If these results do not look correct, please [update your submission via this form]({prefill}). \n\n *Please contact u/JeenyusJane if you encounter problems with this bot.* \n\n \n"+reply_table

            # Reply to Submission
            pp.pprint(submission.url)
            pp.pprint(text_reply)
            comment = submission.reply(body=text_reply)
            comment.mod.distinguish(sticky=True)


### GET POST DETAILS ####
for submission in subreddit.stream.submissions():

    try:
        get_reddit_post(submission)

    except ConnectionError:
        load_reddit()
        get_reddit_post(submission)
