import os
import re
import html  # for grabbing Reddit images
import tempfile  # for mega downloads
import shutil  # for mega cleanup
import mimetypes  # for file uploads

from urllib.parse import urlparse

from config import FIELD_ATTACHMENT, imgur_cdn, http
from airtable_client import (
    reviews_table,
)

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
        response = http.get(api_url, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        print(f"Failed to fetch Imgur album for submission {submission_id}: {repr(e)}")
        return []

    if payload.get("success"):
        return payload["data"][:10]

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


### PARSE MEGA.NZ IMAGES ###


def parse_mega_images(post_body, submission_id=None):
    mega_images = []
    if not post_body or not Mega:
        return mega_images

    mega_links = re.findall(
        r"https://mega\.nz/(?:file|folder)/[a-zA-Z0-9_-]+#[a-zA-Z0-9_-]+", post_body
    )
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
        for link in mega_links[:3]:  # Limit to prevent overwhelming downloads
            try:
                downloaded_path = m.download_url(link, dest_path=temp_dir)
                if downloaded_path:
                    # Convert pathlib object to a standard string for compatibility
                    downloaded_path = str(downloaded_path)

                    if os.path.exists(downloaded_path):
                        if os.path.isfile(downloaded_path):  # Individual File
                            if downloaded_path.lower().endswith(
                                (".png", ".jpg", ".jpeg", ".gif")
                            ):
                                filename = os.path.basename(downloaded_path)
                                with open(downloaded_path, "rb") as f:
                                    mega_images.append(
                                        {
                                            "id": f"mega_{filename}",
                                            "content": f.read(),
                                            "filename": filename,
                                        }
                                    )

                        elif os.path.isdir(downloaded_path):  # Full Folder
                            for root, _, files in os.walk(downloaded_path):
                                for file in files:
                                    if file.lower().endswith(
                                        (".png", ".jpg", ".jpeg", ".gif")
                                    ):
                                        full_path = os.path.join(root, file)
                                        with open(full_path, "rb") as f:
                                            mega_images.append(
                                                {
                                                    "id": f"mega_{file}",
                                                    "content": f.read(),
                                                    "filename": file,
                                                }
                                            )
                                            if len(mega_images) >= 10:
                                                break
                                if len(mega_images) >= 10:
                                    break
            except Exception as e:
                print(
                    f"Failed to process Mega link {link} for submission {submission_id}: {e}"
                )
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
            res = http.get(album_url, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                # Grab all images linked in the album
                for a in soup.find_all(
                    "a", href=re.compile(r"https://ibb\.co/(?!album/)[a-zA-Z0-9]+")
                ):
                    single_links.append(a["href"])
        except Exception as e:
            print(f"Failed to fetch IBB album {album_url}: {e}")

    # Remove duplicates
    single_links = list(set(single_links))

    for link in single_links[:10]:
        try:
            res = http.get(link, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                meta = soup.find("meta", property="og:image") or soup.find(
                    "link", rel="image_src"
                )
                if meta:
                    raw_url = meta.get("content") or meta.get("href")
                    img_id = link.split("/")[-1]
                    ibb_images.append({"id": f"ibb_{img_id}", "link": raw_url})
        except Exception as e:
            print(f"Failed to fetch IBB image {link}: {e}")

    return ibb_images


### PREPARE ATTACHMENT UPLOAD ###


def upload_attachments(record_id, images, submission_id=None):
    if not images:
        return

    print(
        f"[{submission_id}] Processing {len(images)} images to push directly to Airtable..."
    )

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
                    print(
                        f"✓ Uploaded {filename} to record {record_id} via content bytes"
                    )

                # If image is a remote URL to be downloaded
                else:
                    link = image.get("link")
                    if not link:
                        continue

                    print(f"Uploading {link} for submission {submission_id}")

                    image_response = imgur_cdn.get(link, timeout=30)
                    if image_response.status_code == 200:
                        content_type = image_response.headers.get(
                            "Content-Type", "image/jpeg"
                        )
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
                        print(
                            f"Failed to download image for submission {submission_id}: HTTP {image_response.status_code}"
                        )

            except Exception as e:
                print(
                    f"Failed to upload attachment for record {record_id}, submission {submission_id}: {repr(e)}"
                )
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
                print(
                    f"✓ Attached {len(attachments)} URLs to record {record_id} (fallback)"
                )
        except Exception as e:
            print(
                f"Failed to attach URLs for record {record_id}, submission {submission_id}: {repr(e)}"
            )
