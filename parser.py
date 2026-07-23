import re

from config import REGEX, MATCH_EXACT
from lookup import lookup, apply_lookup, seller_df, brand_df, factory_df, style_df

FIELD_MAP = {
    "brand": "brand",
    "style": "style",
    "price": "price",
    "wechat": "wechat",
    "whatsapp": "whatsapp",
    "satisfaction": "satisfaction",
    "quality": "quality",
    "accuracy": "accuracy",
    "communication": "communication",
}


def parse_title(review, title):

    brand = lookup(title, brand_df)

    if brand:
        apply_lookup(review, "brand", brand)

    seller = lookup(title, seller_df)

    if seller:
        apply_lookup(review, "seller", seller)

    factory = lookup(title, factory_df)

    if factory:
        apply_lookup(review, "factory", factory)

    style = lookup(title, style_df)

    if style:
        apply_lookup(review, "style", style)


def parse_review_body(review, post_body):
    post_body = post_body or ""
    lower_body = post_body.lower()

    for field, config in REGEX.items():
        match = re.search(config["find"], lower_body)
        if not match:
            continue

        if "extract" in config:
            raw_value = (
                match.group(2)
                if match.groups() and len(match.groups()) >= 2
                else match.group(1)
            )
            if "score" in config:
                try:
                    normalized = str(raw_value).replace(",", ".").strip()
                    num = float(normalized)
                    if num > 10:
                        num = 10.0
                    review[field.lower()] = num
                except (ValueError, TypeError):
                    review[field.lower()] = raw_value
            else:
                review[field.lower()] = raw_value
        else:
            review[field.lower()] = match.group(0)


def parse_factory(review, body):

    match = re.search(
        r"factory\s*[:=\-]\s*(.+)",
        body,
        flags=re.IGNORECASE,
    )

    if not match:
        return

    candidate = match.group(1).strip()

    result = lookup(candidate, factory_df, MATCH_EXACT)

    if result:
        apply_lookup(review, "factory", result)


def parse_seller(review, body):

    match = re.search(
        r"seller\s*[:=\-]\s*(.+)",
        body,
        flags=re.IGNORECASE,
    )

    if not match:
        return

    candidate = match.group(1).strip()

    result = lookup(candidate, seller_df, MATCH_EXACT)

    if result:
        apply_lookup(review, "seller", result)


def parse_labeled_fields(review, post_body):
    if not post_body:
        return

    for label, key in FIELD_MAP.items():
        pattern = rf"{label}\s*[:=\-]\s*(.+)"

        match = re.search(
            pattern,
            post_body,
            flags=re.IGNORECASE,
        )

        if match:
            review[key] = match.group(1).strip()
