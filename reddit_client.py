import praw

from config import (
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_PASSWORD,
    REDDIT_SUBREDDIT,
    REDDIT_USER_AGENT,
    REDDIT_USERNAME,
)


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

    subreddit = reddit.subreddit(REDDIT_SUBREDDIT)

    print("Subreddit loaded.")

    return reddit, subreddit
