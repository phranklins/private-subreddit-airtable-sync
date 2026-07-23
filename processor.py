import traceback  # for debugging
import time

from config import REDDIT_USERNAME, ENABLE_POST_REPLIES, LOOKBACK_DAYS, MATCH_EXACT
from airtable_client import reviews_table, existing_ids, most_recent_utc
from parser import (
    parse_labeled_fields,
    parse_review_body,
    parse_title,
    parse_factory,
    parse_seller,
)
from models import new_review
from attachments import (
    parse_imgur_album,
    parse_reddit_images,
    parse_mega_images,
    parse_ibb_images,
    upload_attachments,
)
from replies import (
    build_airtable_record,
    build_prefill_link,
    build_reply_objects,
    build_reply_table,
)
from lookup import (
    lookup,
    apply_lookup,
    seller_df,
    factory_df,
    brand_df,
    style_df,
    resolve_review,
)


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


def build_review(submission):

    review = new_review()

    print(f"Post Title: {submission.title}")

    parse_title(review, submission.title)
    parse_seller(review, submission.selftext)
    parse_factory(review, submission.selftext)
    parse_labeled_fields(review, submission.selftext)
    parse_review_body(review, submission.selftext)

    if not review["brand"]:
        brand = lookup(submission.selftext, brand_df, match=MATCH_EXACT)

        if brand:
            apply_lookup(review, "brand", brand)

    if not review["seller"]:
        seller = lookup(submission.selftext, seller_df, match=MATCH_EXACT)

        if seller:
            apply_lookup(review, "seller", seller)

    if not review["factory"]:
        factory = lookup(submission.selftext, factory_df, match=MATCH_EXACT)

        if factory:
            apply_lookup(review, "factory", factory)

    if not review["style"]:
        style = lookup(submission.selftext, style_df, match=MATCH_EXACT)

        if style:
            apply_lookup(review, "style", style)

    resolve_review(review)
    return review


def upload_images(record_id, submission):

    images = []

    images.extend(parse_reddit_images(submission))
    images.extend(parse_imgur_album(submission.selftext))
    images.extend(parse_ibb_images(submission.selftext))
    images.extend(parse_mega_images(submission.selftext))

    if images:
        upload_attachments(record_id, images[:10])


def rollback_review(record_id, submission):
    reviews_table.delete(record_id)
    existing_ids.discard(submission.id)


def reply_to_post(submission, review, record_id):
    reply_table, reply_sharelink = build_reply_objects(review)
    prefill = build_prefill_link(reply_sharelink, record_id)
    reply_table_str = build_reply_table(reply_table)

    print(reply_table_str)

    text_reply = (
        f"👋🏾 Hello, your Review Bot here! This is a summary of your post. If this info looks incorrect or missing anything, please [update your submission via this form]({prefill}). \n\n *Please send mod mail if you encounter problems with this bot.* \n\n \n"
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
                    print(
                        f"✓ Reply posted, but could not sticky (Missing mod privileges). {mod_err}\n"
                    )
            except Exception as reply_err:
                # ROLLBACK: If reply fails (e.g., rate limit), delete Airtable record so cron retries it
                print(f"Failed to post Reddit reply for {submission.id}: {reply_err}")
                print(
                    f"Rolling back Airtable record {record_id} to ensure retry on next run...\n"
                )
                rollback_review(record_id, submission)
                return
    else:
        print("Skipping Reddit reply (ENABLE_POST_REPLIES=false)\n")


def save_review(review, submission):

    record = build_airtable_record(
        submission,
        review,
    )

    airtable_record = reviews_table.create(
        record,
        typecast=True,
    )

    record_id = airtable_record["id"]

    existing_ids.add(submission.id)

    print(f"[{submission.id}] Base text record created.")

    return record_id


def get_reddit_post(submission):

    if submission.link_flair_text != "Review":
        return

    if record_exists(submission.id):
        print(f"Post {submission.id} already exists. Skipping...")
        return

    review = build_review(submission)

    record_id = save_review(
        review,
        submission,
    )

    upload_images(
        record_id,
        submission,
    )

    reply_to_post(
        submission,
        review,
        record_id,
    )


def process_submission(submission):

    try:
        get_reddit_post(submission)

    except Exception as e:
        print(f"Failed processing {submission.id}: {e}")
        traceback.print_exc()


def run_backfill(subreddit):
    print(f"Starting chunked backfill for the last {LOOKBACK_DAYS} days...")
    backfill_cutoff_utc = time.time() - (LOOKBACK_DAYS * 24 * 60 * 60)

    characters = list("zqxjkvbpygfwmuclrhsnioate0123456789")
    queries = [f'flair:"Review" AND title:{char}' for char in characters]
    queries.append('flair:"Review"')

    for query in queries:
        print(f"Executing backfill query: {query}")
        for submission in subreddit.search(query, sort="new", limit=100):
            if submission.created_utc < backfill_cutoff_utc:
                continue
            process_submission(submission)


def run_daily_sync(subreddit):
    print("Starting daily cron sync...")
    for submission in subreddit.new(limit=100):
        if submission.created_utc <= most_recent_utc:
            print("Reached already-processed posts. Daily sync complete.")
            break

        process_submission(submission)
