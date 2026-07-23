from urllib.parse import quote_plus

from config import (
    FIELD_ACCURACY,
    FIELD_BRAND,
    FIELD_COMMUNICATION,
    FIELD_FACTORY,
    FIELD_PRICE,
    FIELD_QUALITY,
    FIELD_SATISFACTION,
    FIELD_SELLER,
    FIELD_STYLE,
)

### CREATE AIRTABLE RECORD ###


def build_airtable_record(submission, review):
    record = {
        "title": submission.title,
        "url": f"https://reddit.com{submission.permalink}",
        "author": submission.author.name if submission.author else None,
        "id": submission.id,
        "created_utc": submission.created_utc,
        FIELD_BRAND: review["brand_id"],
        FIELD_SELLER: review["seller_id"],
        FIELD_FACTORY: review["factory_id"],
        FIELD_STYLE: review["style_id"],
        FIELD_QUALITY: review["quality"],
        FIELD_ACCURACY: review["accuracy"],
        FIELD_COMMUNICATION: review["communication"],
        FIELD_SATISFACTION: review["satisfaction"],
        FIELD_PRICE: review["price"],
    }

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
def build_reply_objects(review):
    reply_table = {
        FIELD_BRAND: review["brand"],
        FIELD_SELLER: review["seller"],
        FIELD_FACTORY: review["factory"],
        FIELD_STYLE: review["style"],
        FIELD_QUALITY: review["quality"],
        FIELD_ACCURACY: review["accuracy"],
        FIELD_COMMUNICATION: review["communication"],
        FIELD_SATISFACTION: review["satisfaction"],
        FIELD_PRICE: review["price"],
    }
    reply_sharelink = {
        FIELD_BRAND: review["brand_id"],
        FIELD_SELLER: review["seller_id"],
        FIELD_FACTORY: review["factory_id"],
        FIELD_STYLE: review["style_id"],
        FIELD_QUALITY: review["quality"],
        FIELD_ACCURACY: review["accuracy"],
        FIELD_COMMUNICATION: review["communication"],
        FIELD_SATISFACTION: review["satisfaction"],
        FIELD_PRICE: review["price"],
    }
    return reply_table, reply_sharelink


def build_reply_table(reply_table):
    headers = "|".join(reply_table.keys())
    divider = "".join(["|:-"] * len(reply_table))
    values = "|".join(str(v) if v is not None else " - " for v in reply_table.values())
    return "\n".join([headers, divider, values])
