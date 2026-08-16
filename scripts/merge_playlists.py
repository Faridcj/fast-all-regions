import json
import re
import time
import urllib.request
import urllib.error
from urllib.parse import quote, unquote
from pathlib import PurePosixPath
from collections import defaultdict

OWNER = "BuddyChewChew"
OUTPUT = "fast-all-regions.m3u"

REQUEST_TIMEOUT = 90

API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "FAST-All-Regions-Builder/2.0",
}

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 FAST-All-Regions-Builder/2.0",
}

PLAYLIST_EXTENSIONS = (".m3u", ".m3u8")

IGNORE_PARTS = {
    "epg",
    "epg.xml",
    "epg.xml.gz",
    "logos",
    "logo",
    "images",
    "docs",
    "documentation",
    "test",
    "tests",
    "example",
    "examples",
}


# ============================================================
# COUNTRY / REGION MAP
# ============================================================

COUNTRIES = {
    "us": "US",
    "usa": "US",
    "unitedstates": "US",
    "united-states": "US",
    "united_states": "US",
    "america": "US",

    "uk": "UK",
    "gb": "UK",
    "greatbritain": "UK",
    "great-britain": "UK",
    "unitedkingdom": "UK",
    "united-kingdom": "UK",
    "united_kingdom": "UK",
    "england": "UK",

    "ca": "Canada",
    "canada": "Canada",
    "au": "Australia",
    "australia": "Australia",
    "nz": "New Zealand",
    "new-zealand": "New Zealand",
    "new_zealand": "New Zealand",

    "de": "Germany",
    "germany": "Germany",
    "fr": "France",
    "france": "France",
    "es": "Spain",
    "spain": "Spain",
    "it": "Italy",
    "italy": "Italy",

    "br": "Brazil",
    "brazil": "Brazil",
    "mx": "Mexico",
    "mexico": "Mexico",

    "in": "India",
    "india": "India",
    "jp": "Japan",
    "japan": "Japan",
    "kr": "South Korea",
    "korea": "South Korea",
    "south-korea": "South Korea",
    "south_korea": "South Korea",

    "at": "Austria",
    "austria": "Austria",
    "ch": "Switzerland",
    "switzerland": "Switzerland",
    "nl": "Netherlands",
    "netherlands": "Netherlands",
    "se": "Sweden",
    "sweden": "Sweden",
    "no": "Norway",
    "norway": "Norway",
    "dk": "Denmark",
    "denmark": "Denmark",
    "fi": "Finland",
    "finland": "Finland",

    "pl": "Poland",
    "poland": "Poland",
    "tr": "Turkey",
    "turkey": "Turkey",
    "ie": "Ireland",
    "ireland": "Ireland",

    "za": "South Africa",
    "south-africa": "South Africa",
    "south_africa": "South Africa",
    "southafrica": "South Africa",

    "ar": "Argentina",
    "argentina": "Argentina",
    "cl": "Chile",
    "chile": "Chile",
    "co": "Colombia",
    "colombia": "Colombia",
    "pe": "Peru",
    "peru": "Peru",
    "pt": "Portugal",
    "portugal": "Portugal",
    "gr": "Greece",
    "greece": "Greece",
    "il": "Israel",
    "israel": "Israel",

    "ph": "Philippines",
    "philippines": "Philippines",
    "sg": "Singapore",
    "singapore": "Singapore",
    "my": "Malaysia",
    "malaysia": "Malaysia",
    "th": "Thailand",
    "thailand": "Thailand",
    "hk": "Hong Kong",
    "hong-kong": "Hong Kong",
    "hong_kong": "Hong Kong",
    "tw": "Taiwan",
    "taiwan": "Taiwan",
}


# ============================================================
# HTTP
# ============================================================

def fetch_bytes(url, headers=None, retries=3):

    headers = headers or HTTP_HEADERS

    last_error = None

    for attempt in range(retries):

        try:
            request = urllib.request.Request(
                url,
                headers=headers
            )

            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT
            ) as response:

                return response.read()

        except urllib.error.HTTPError as error:

            last_error = error

            if error.code == 404:
                raise

            if error.code in (403, 429, 500, 502, 503, 504):

                wait = min(
                    2 ** attempt,
                    10
                )

                time.sleep(wait)
                continue

            raise

        except Exception as error:

            last_error = error

            time.sleep(
                min(2 ** attempt, 10)
            )

    raise last_error


def fetch_text(url, headers=None, retries=3):

    return fetch_bytes(
        url,
        headers,
        retries
    ).decode(
        "utf-8",
        errors="replace"
    )


def github_json(url):

    return json.loads(
        fetch_text(
            url,
            API_HEADERS
        )
    )


# ============================================================
# GITHUB REPOSITORIES
# ============================================================

def get_all_repositories():

    repositories = []
    page = 1

    while True:

        url = (
            f"https://api.github.com/users/"
            f"{OWNER}/repos"
            f"?per_page=100"
            f"&page={page}"
            f"&type=public"
        )

        try:

            data = github_json(url)

        except urllib.error.HTTPError as error:

            if error.code in (403, 429):

                print(
                    "[WARNING] GitHub API rate limit reached."
                )

                print(
                    "[WARNING] Trying repository discovery "
                    "through GitHub public HTML..."
                )

                return get_repositories_fallback(
                    repositories
                )

            print(
                f"[ERROR] Cannot read repositories: "
                f"{error}"
            )

            break

        except Exception as error:

            print(
                f"[ERROR] Cannot read repositories: "
                f"{error}"
            )

            break

        if not data:
            break

        for repo in data:

            if repo.get("fork"):
                continue

            if repo.get("archived"):
                continue

            repositories.append(
                {
                    "name": repo["name"],
                    "default_branch": (
                        repo.get("default_branch")
                        or "main"
                    ),
                }
            )

        if len(data) < 100:
            break

        page += 1

    return repositories


def get_repositories_fallback(existing):

    names = {
        item["name"]
        for item in existing
    }

    url = (
        f"https://github.com/"
        f"{OWNER}?tab=repositories"
    )

    try:

        html = fetch_text(
            url,
            HTTP_HEADERS
        )

        matches = re.findall(
            rf'href="/{re.escape(OWNER)}/([^"/?#]+)"',
            html
        )

        for name in matches:

            if name in names:
                continue

            if name.startswith("."):
                continue

            existing.append(
                {
                    "name": name,
                    "default_branch": "main",
                }
            )

            names.add(name)

    except Exception as error:

        print(
            f"[WARNING] Repository fallback failed: "
            f"{error}"
        )

    return existing


# ============================================================
# TREE
# ============================================================

def get_repository_tree(repo, branch):

    url = (
        f"https://api.github.com/repos/"
        f"{OWNER}/"
        f"{quote(repo, safe='')}"
        f"/git/trees/"
        f"{quote(branch, safe='/')}"
        f"?recursive=1"
    )

    try:

        data = github_json(url)

        if data.get("truncated"):

            print(
                f"[WARNING] GitHub tree truncated: "
                f"{repo}"
            )

        return data.get("tree", [])

    except urllib.error.HTTPError as error:

        if error.code in (403, 429):

            print(
                f"[WARNING] API rate limit for "
                f"{repo}; trying Contents API..."
            )

            return get_tree_from_contents(
                repo,
                branch
            )

        print(
            f"[WARNING] Cannot read tree "
            f"{repo}: {error}"
        )

        return []

    except Exception as error:

        print(
            f"[WARNING] Cannot read tree "
            f"{repo}: {error}"
        )

        return []


def get_tree_from_contents(repo, branch):

    """
    Recursive Contents API fallback.

    This is slower than git/trees but avoids depending
    entirely on the API tree endpoint.
    """

    result = []

    def walk(path=""):

        if path:

            url = (
                f"https://api.github.com/repos/"
                f"{OWNER}/"
                f"{quote(repo, safe='')}/contents/"
                f"{quote(path, safe='/')}"
                f"?ref={quote(branch, safe='/')}"
            )

        else:

            url = (
                f"https://api.github.com/repos/"
                f"{OWNER}/"
                f"{quote(repo, safe='')}/contents/"
                f"?ref={quote(branch, safe='/')}"
            )

        try:

            data = github_json(url)

        except Exception as error:

            print(
                f"[WARNING] Contents fallback failed "
                f"for {repo}/{path}: {error}"
            )

            return

        if not isinstance(data, list):
            return

        for item in data:

            item_type = item.get("type")
            item_path = item.get("path", "")

            if item_type == "file":

                result.append(
                    {
                        "type": "blob",
                        "path": item_path,
                    }
                )

            elif item_type == "dir":

                walk(item_path)

    walk()

    return result


# ============================================================
# PLAYLIST DISCOVERY
# ============================================================

def is_playlist(path):

    lower = path.lower()

    if not lower.endswith(
        PLAYLIST_EXTENSIONS
    ):
        return False

    parts = {
        p.lower()
        for p in PurePosixPath(path).parts
    }

    if parts.intersection(
        IGNORE_PARTS
    ):
        return False

    return True


def discover_playlists(repo, branch):

    tree = get_repository_tree(
        repo,
        branch
    )

    result = []

    for item in tree:

        if item.get("type") != "blob":
            continue

        path = item.get(
            "path",
            ""
        )

        if not is_playlist(path):
            continue

        result.append(path)

    return sorted(
        set(result)
    )


# ============================================================
# SERVICE NAME
# ============================================================

def clean_service_name(repo):

    known = {
        "app-m3u-generator": "FAST Apps",
        "plex-alt-fast-channels": "Plex Alt",
        "samsungtvplus": "Samsung TV Plus",
        "roku-playlist-generator": "Roku",
        "tubi-scraper": "Tubi",
        "xumo-playlist-generator": "Xumo",
        "localnow-playlist-generator": "Local Now",
        "lg-playlist-generator": "LG Channels",
        "lg-playlist-generator2": "LG Channels 2",
        "tcl-playlist-generator": "TCL TV+",
        "distro-playlist-generator": "DistroTV",
        "RakutenTV": "Rakuten TV",
        "airy-playlist-generator": "Airy TV",
        "pluto": "Pluto TV",
        "plex": "Plex",
    }

    if repo in known:
        return known[repo]

    name = re.sub(
        r"[-_]+",
        " ",
        repo
    )

    name = re.sub(
        r"\bplaylist generator\b",
        "",
        name,
        flags=re.IGNORECASE
    )

    name = re.sub(
        r"\bm3u generator\b",
        "",
        name,
        flags=re.IGNORECASE
    )

    name = re.sub(
        r"\s+",
        " ",
        name
    ).strip()

    return name.title()


# ============================================================
# M3U ATTRIBUTES
# ============================================================

def get_attribute(extinf, attribute):

    pattern = (
        rf'{re.escape(attribute)}='
        r'"([^"]*)"'
    )

    match = re.search(
        pattern,
        extinf,
        re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return ""


def replace_group_title(extinf, group):

    escaped_group = (
        group
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )

    if re.search(
        r'group-title="[^"]*"',
        extinf,
        re.IGNORECASE
    ):

        return re.sub(
            r'group-title="[^"]*"',
            f'group-title="{escaped_group}"',
            extinf,
            flags=re.IGNORECASE
        )

    comma = extinf.find(","
