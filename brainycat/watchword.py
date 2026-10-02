"""Watch for books by keyword in title. Searches Prowlarr, grabs via qBittorrent."""

import json
import os
import time
import urllib.request

PROWLARR_URL = "http://localhost:9696"
PROWLARR_KEY = "b87b1357d59f4233b8cd1ca7384d315b"
QBIT_URL = "http://localhost:8082"
QBIT_USER = "ecb"
QBIT_PASS = "r3ddr4ke"
CHECK_INTERVAL = 3600 * 6
STATE_FILE = "/data/watchword_seen.json"
CONFIG_FILE = "/data/watchword_config.json"

DEFAULT_KEYWORDS = [
    {"term": "collart", "languages": None},
    {"term": "laravel", "languages": ["en", "fr"]},
]


def load_config():
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f).get("keywords", DEFAULT_KEYWORDS)
    return DEFAULT_KEYWORDS


def search_prowlarr(query):
    url = f"{PROWLARR_URL}/api/v1/search?query={query}&type=book"
    req = urllib.request.Request(url, headers={"X-Api-Key": PROWLARR_KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load_seen():
    if os.path.isfile(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(STATE_FILE, "w") as f:
        json.dump(list(seen), f)


def grab_torrent(download_url):
    login_data = f"username={QBIT_USER}&password={QBIT_PASS}".encode()
    req = urllib.request.Request(f"{QBIT_URL}/api/v2/auth/login", data=login_data)
    with urllib.request.urlopen(req, timeout=10) as r:
        cookie = r.headers.get("Set-Cookie", "").split(";")[0]

    boundary = "----FormBoundary"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"urls\"\r\n\r\n{download_url}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"category\"\r\n\r\nbooks\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        f"{QBIT_URL}/api/v2/torrents/add",
        data=body,
        headers={"Cookie": cookie, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status == 200


def matches_language(result, allowed_langs):
    if not allowed_langs:
        return True
    # Check title for language hints
    title = result.get("title", "").lower()
    # Common patterns: (French), [EN], etc.
    if any(l in title for l in ["french", "français", "fr"]):
        return "fr" in allowed_langs
    if any(l in title for l in ["english", "en"]):
        return "en" in allowed_langs
    # No language info = assume OK
    return True


def run():
    print("Watchword monitor started")
    while True:
        try:
            keywords = load_config()
            seen = load_seen()
            total_new = 0

            for kw in keywords:
                term = kw["term"]
                langs = kw.get("languages")
                results = search_prowlarr(term)

                for r in results:
                    guid = r.get("guid", r.get("downloadUrl", ""))
                    title = r.get("title", "")
                    if guid in seen:
                        continue
                    seen.add(guid)
                    if term.lower() not in title.lower():
                        continue
                    if not matches_language(r, langs):
                        continue
                    dl = r.get("downloadUrl")
                    if dl:
                        print(f"  [{term}] {title[:80]}")
                        try:
                            grab_torrent(dl)
                            total_new += 1
                        except Exception as e:
                            print(f"    grab failed: {e}")

            save_seen(seen)
            if total_new:
                print(f"  Grabbed {total_new} new items")
            else:
                print("  Check done, nothing new")
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
