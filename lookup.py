import re  # from datetime import date to manage regex
import pandas as pd  # Easily work with tabular data

from config import MATCH_CONTAINS, MATCH_EXACT
from airtable_client import brands_table, sellers_table, factories_table, styles_table


def load_cardinal_objects():
    brands_records = brands_table.all()
    df = pd.DataFrame(brands_records)
    brand_df = pd.json_normalize(df.fields)
    brand_df["Name & Aliases"] = brand_df.get("Name & Aliases", "").fillna("")

    sellers_records = sellers_table.all()
    df = pd.DataFrame(sellers_records)
    seller_df = pd.json_normalize(df.fields)
    seller_df["Name & Aliases"] = seller_df.get("Name & Aliases", "").fillna("")

    factories_records = factories_table.all()
    df = pd.DataFrame(factories_records)
    factory_df = pd.json_normalize(df.fields)
    factory_df["Name & Aliases"] = factory_df.get("Name & Aliases", "").fillna("")

    styles_records = styles_table.all()
    df = pd.DataFrame(styles_records)
    style_df = pd.json_normalize(df.fields)
    style_df["Name & Aliases"] = style_df.get("Name & Aliases", "").fillna("")

    return (
        brand_df,
        seller_df,
        style_df,
        factory_df,
    )


(
    brand_df,
    seller_df,
    style_df,
    factory_df,
) = load_cardinal_objects()


def lookup(text, dataframe, match=MATCH_CONTAINS):

    if not text:
        return None

    text = text.strip().lower()

    for _, row in dataframe.iterrows():

        aliases = row.get("Name & Aliases", "")

        if not aliases:
            continue

        for alias in aliases.split(","):

            alias = alias.strip().lower()

            if not alias:
                continue

            if match == MATCH_EXACT:

                if text == alias:

                    return {
                        "name": row["Name"],
                        "record_id": row["record_id"],
                    }

            else:

                regex = rf"(?:\W|^){re.escape(alias)}(?:\W|$)"

                if re.search(regex, text):
                    print(f"Matched '{alias}' -> {row['Name']}")
                    print(f"Text: {text[:200]}")
                    print(f"Factory alias matched: '{alias}'")

                    return {
                        "name": row["Name"],
                        "record_id": row["record_id"],
                    }

    return None


def apply_lookup(review, key, result):

    if not result:
        return

    review[key] = result["name"]
    review[f"{key}_id"] = [result["record_id"]]


def resolve_review(review):

    if not review["brand_id"]:
        brand = lookup(review["brand"], brand_df, match=MATCH_EXACT)

        if brand:
            apply_lookup(review, "brand", brand)

    if not review["seller_id"]:
        seller = lookup(review["seller"], seller_df, match=MATCH_EXACT)

        if seller:
            apply_lookup(review, "seller", seller)

    if not review["factory_id"]:
        factory = lookup(review["factory"], factory_df, match=MATCH_EXACT)

        if factory:
            apply_lookup(review, "factory", factory)

    if not review["style_id"]:
        style = lookup(review["style"], style_df, match=MATCH_EXACT)

        if style:
            apply_lookup(review, "style", style)

    return review
