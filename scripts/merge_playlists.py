import json
import re
import urllib.request
from urllib.parse import quote
from pathlib import PurePosixPath
from collections import defaultdict

OWNER = "BuddyChewChew"
OUTPUT = "fast-all-regions.m3u"
REQUEST_TIMEOUT = 90

# ============================================================
# GITHUB TOKEN
# ============================================================

import os

GITHUB_TOKEN = os.environ.get("GH_TOKEN", "").strip()

API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "FAST-All-Regions-Builder",
}

if GITHUB_TOKEN:
    API_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 FAST-All-Regions-Builder"
}

PLAYLIST_EXTENSIONS = (
    ".m3u",
    ".m3u8",
)

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
# SERVICE NAMES
# ============================================================

SERVICE_NAMES = {
    "app-m3u-generator": "FAST Apps",
    "plex-alt-fast-channels": "Plex",
    "samsungtvplus": "Samsung TV Plus",
    "roku-playlist-generator": "Roku",
    "tubi-scraper": "Tubi",
    "xumo-playlist-generator": "Xumo",
    "localnow-playlist-generator": "Local Now",
    "lg-playlist-generator": "LG Channels",
    "lg-playlist-generator2": "LG Channels",
    "tcl-playlist-generator": "TCL TV+",
    "distro-playlist-generator": "DistroTV",
    "RakutenTV": "Rakuten TV",
    "airy-playlist-generator": "Airy TV",
    "pluto": "Pluto TV",
    "plex": "Plex",
    "sports": "Sports",
    "My-Streams": "My Streams",
    "buddylive": "BuddyLive",
    "buddylive_v2": "BuddyLive",
    "buddylive-combined": "BuddyLive",
    "nz": "NZ",
}


# ============================================================
# SOURCE PRIORITY
#
# This is ONLY used when the exact same URL occurs more than
# once. No channel-name deduplication is performed.
# ============================================================

SOURCE_PRIORITY = {
    "samsungtvplus": 100,
    "lg-playlist-generator": 100,
    "lg-playlist-generator2": 95,
    "tcl-playlist-generator": 100,
    "xumo-playlist-generator": 100,
    "roku-playlist-generator": 100,
    "tubi-scraper": 100,
    "pluto": 100,
    "plex": 100,
    "plex-alt-fast-channels": 95,
    "RakutenTV": 100,
    "distro-playlist-generator": 100,
    "airy-playlist-generator": 100,
    "localnow-playlist-generator": 100,
    "My-Streams": 90,
    "buddylive": 90,
    "buddylive_v2": 90,
    "buddylive-combined": 85,
    "app-m3u-generator": 50,
    "sports": 100,
    "nz": 100,
}


# ============================================================
# HTTP
# ============================================================

def fetch_bytes(url, headers=None):
    headers = headers or HTTP_HEADERS

    request = urllib.request.Request(
        url,
        headers=headers
    )

    with urllib.request.urlopen(
        request,
        timeout=REQUEST_TIMEOUT
    ) as response:
        return response.read()


def fetch_text(url, headers=None):
    return fetch_bytes(
        url,
        headers
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
# GITHUB
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
            f"&sort=updated"
        )

        try:
            data = github_json(url)

        except Exception as error:
            print(
                f"[ERROR] Cannot read repositories: {error}"
            )
            break

        if not data:
            break

        for repo in data:

            if repo.get("fork"):
                continue

            if repo.get("archived"):
                continue

            repositories.append({
                "name": repo["name"],
                "default_branch": (
                    repo.get("default_branch")
                    or "main"
                ),
            })

        if len(data) < 100:
            break

        page += 1

    return repositories


def get_repository_tree(repo, branch):

    url = (
        f"https://api.github.com/repos/"
        f"{OWNER}/{quote(repo, safe='')}"
        f"/git/trees/"
        f"{quote(branch, safe='/')}"
        f"?recursive=1"
    )

    try:

        data = github_json(url)

        if data.get("truncated"):
            print(
                f"[WARNING] GitHub tree is truncated: {repo}"
            )

        return data.get("tree", [])

    except Exception as error:

        print(
            f"[WARNING] Cannot read tree "
            f"{repo}: {error}"
        )

        return []


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

    return sorted(result)


# ============================================================
# SERVICE
# ============================================================

def clean_service_name(repo):

    if repo in SERVICE_NAMES:
        return SERVICE_NAMES[repo]

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

    if re.search(
        r'group-title="[^"]*"',
        extinf,
        re.IGNORECASE
    ):

        return re.sub(
            r'group-title="[^"]*"',
            f'group-title="{group}"',
            extinf,
            flags=re.IGNORECASE
        )

    comma = extinf.find(",")

    if comma == -1:
        return extinf

    return (
        extinf[:comma]
        + f' group-title="{group}"'
        + extinf[comma:]
    )


# ============================================================
# M3U PARSER
# ============================================================

def parse_m3u(text):

    lines = (
        text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )

    entries = []

    current_extinf = None

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if line.startswith("#EXTINF:"):

            current_extinf = line
            continue

        if line.startswith("#"):
            continue

        if (
            current_extinf
            and line.startswith(
                (
                    "http://",
                    "https://"
                )
            )
        ):

            entries.append(
                (
                    current_extinf,
                    line
                )
            )

            current_extinf = None

    return entries


def get_channel_name(extinf):

    if "," not in extinf:
        return ""

    return (
        extinf
        .split(",", 1)[1]
        .strip()
    )


# ============================================================
# ORIGINAL GROUP
# ============================================================

def get_original_group(extinf):

    group = get_attribute(
        extinf,
        "group-title"
    )

    return group.strip()


# ============================================================
# REGION HANDLING
#
# IMPORTANT:
# NO GUESSING FROM:
#   - filename
#   - URL
#   - tvg-id
#   - channel name
#
# Region is accepted ONLY when the ORIGINAL GROUP itself
# explicitly contains a region structure.
#
# ============================================================

REGION_NAMES = {
    "US",
    "USA",
    "UK",
    "GB",
    "CA",
    "AU",
    "NZ",
    "DE",
    "FR",
    "ES",
    "IT",
    "BR",
    "MX",
    "IN",
    "JP",
    "KR",
    "AT",
    "CH",
    "NL",
    "SE",
    "NO",
    "DK",
    "FI",
    "PL",
    "TR",
    "IE",
    "ZA",
    "AR",
    "CL",
    "CO",
    "PE",
    "PT",
    "GR",
    "IL",
    "PH",
    "SG",
    "MY",
    "TH",
    "HK",
    "TW",
}


def normalize_region_token(value):

    value = value.strip()

    if not value:
        return ""

    upper = value.upper()

    if upper in REGION_NAMES:
        return upper

    return ""


def extract_explicit_region_from_group(group):

    if not group:
        return ""

    # Only inspect explicit group separators.
    #
    # Examples:
    #   Pluto TV | US
    #   Pluto TV / US
    #   Pluto TV - US
    #   US
    #
    # We DO NOT inspect URLs or channel names.

    pieces = re.split(
        r"\s*[|>/;:]\s*|\s+-\s+",
        group
    )

    for piece in pieces:

        region = normalize_region_token(
            piece
        )

        if region:
            return region

    # If the entire group is simply a region,
    # preserve it.

    region = normalize_region_token(
        group
    )

    if region:
        return region

    return ""


# ============================================================
# CATEGORY
# ============================================================

def build_category(
    service,
    original_group
):

    region = extract_explicit_region_from_group(
        original_group
    )

    if region:
        return f"{service} | {region}"

    return service


# ============================================================
# DEDUPLICATION
#
# ONLY EXACT URL DUPLICATES ARE REMOVED.
# ============================================================

def deduplicate(entries):

    best_by_url = {}

    for entry in entries:

        url = entry["url"].strip()

        if not url:
            continue

        key = url.lower()

        existing = best_by_url.get(key)

        if existing is None:

            best_by_url[key] = entry
            continue

        old_priority = existing["priority"]
        new_priority = entry["priority"]

        if new_priority > old_priority:
            best_by_url[key] = entry

    return list(
        best_by_url.values()
    )


# ============================================================
# SORT
# ============================================================

def sort_entries(entries):

    return sorted(
        entries,
        key=lambda item: (
            item["service"].lower(),
            item["category"].lower(),
            item["name"].lower(),
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("FAST ALL REGIONS - CLEAN BUILDER")
    print("=" * 70)

    if GITHUB_TOKEN:
        print(
            "GitHub API authentication: ENABLED"
        )
    else:
        print(
            "GitHub API authentication: DISABLED"
        )

    repositories = get_all_repositories()

    print(
        f"Repositories discovered: "
        f"{len(repositories)}"
    )

    all_entries = []
    failed_files = []

    repository_stats = {}

    # ========================================================
    # DISCOVER + READ
    # ========================================================

    for repo_info in repositories:

        repo = repo_info["name"]
        branch = repo_info["default_branch"]

        print()
        print(
            f"=== {repo} ==="
        )

        playlist_paths = discover_playlists(
            repo,
            branch
        )

        print(
            f"Found "
            f"{len(playlist_paths)} "
            f"playlist files"
        )

        successful_files = 0
        repo_channels = 0

        service = clean_service_name(
            repo
        )

        for path in playlist_paths:

            raw_url = (
                "https://raw.githubusercontent.com/"
                f"{OWNER}/"
                f"{quote(repo, safe='')}/"
                f"{quote(path, safe='/')}"
            )

            try:

                text = fetch_text(
                    raw_url
                )

                entries = parse_m3u(
                    text
                )

                print(
                    f"  {path}: "
                    f"{len(entries)} channels"
                )

                successful_files += 1
                repo_channels += len(entries)

                # ------------------------------------------------
                # IMPORTANT:
                #
                # We process every entry.
                # We do NOT remove channels because their names
                # are similar.
                # ------------------------------------------------

                for extinf, stream_url in entries:

                    stream_url = stream_url.strip()

                    if not stream_url:
                        continue

                    channel_name = get_channel_name(
                        extinf
                    )

                    if not channel_name:
                        continue

                    original_group = get_original_group(
                        extinf
                    )

                    category = build_category(
                        service,
                        original_group
                    )

                    new_extinf = replace_group_title(
                        extinf,
                        category
                    )

                    all_entries.append({
                        "extinf": new_extinf,
                        "url": stream_url,
                        "service": service,
                        "category": category,
                        "name": channel_name,
                        "repo": repo,
                        "path": path,
                        "priority": SOURCE_PRIORITY.get(
                            repo,
                            50
                        ),
                    })

            except Exception as error:

                print(
                    f"  [WARNING] "
                    f"{path} failed: "
                    f"{error}"
                )

                failed_files.append(
                    (
                        repo,
                        path,
                        str(error)
                    )
                )

        repository_stats[repo] = {
            "files": len(playlist_paths),
            "successful": successful_files,
            "channels": repo_channels,
        }

    # ========================================================
    # DEDUPLICATE EXACT URLs ONLY
    # ========================================================

    print()
    print(
        "Removing duplicate URLs..."
    )

    unique_entries = deduplicate(
        all_entries
    )

    duplicate_count = (
        len(all_entries)
        - len(unique_entries)
    )

    # ========================================================
    # SORT
    # ========================================================

    unique_entries = sort_entries(
        unique_entries
    )

    # ========================================================
    # WRITE OUTPUT
    # ========================================================

    with open(
        OUTPUT,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as file:

        file.write(
            "#EXTM3U\n"
        )

        for entry in unique_entries:

            file.write(
                entry["extinf"]
                + "\n"
            )

            file.write(
                entry["url"]
                + "\n"
            )

    # ========================================================
    # CATEGORY SUMMARY
    # ========================================================

    categories = defaultdict(int)

    for entry in unique_entries:

        categories[
            entry["category"]
        ] += 1

    # ========================================================
    # FINAL REPORT
    # ========================================================

    print()
    print("=" * 70)
    print("BUILD COMPLETE")
    print("=" * 70)

    print(
        f"Repositories discovered: "
        f"{len(repositories)}"
    )

    print(
        f"Total discovered entries: "
        f"{len(all_entries)}"
    )

    print(
        f"Unique URLs: "
        f"{len(unique_entries)}"
    )

    print(
        f"Duplicate URLs removed: "
        f"{duplicate_count}"
    )

    print(
        f"Categories: "
        f"{len(categories)}"
    )

    print(
        f"Output: "
        f"{OUTPUT}"
    )

    print()
    print(
        "GROUP FORMAT: SERVICE | REGION"
    )

    print(
        "REGION DETECTION: ORIGINAL GROUP ONLY"
    )

    print(
        "REGION GUESSING: DISABLED"
    )

    print(
        "CHANNEL-NAME DEDUPLICATION: DISABLED"
    )

    print(
        "URL DEDUPLICATION: EXACT URL ONLY"
    )

    print(
        "STREAM HEALTH CHECKS: DISABLED"
    )

    print()
    print(
        "CATEGORY SUMMARY"
    )

    print(
        "-" * 70
    )

    for category, count in sorted(
        categories.items(),
        key=lambda x: x[0].lower()
    ):

        print(
            f"{category}: {count}"
        )

    # ========================================================
    # SOURCE SUMMARY
    # ========================================================

    print()
    print(
        "SOURCE SUMMARY"
    )

    print(
        "-" * 70
    )

    for repo, stats in repository_stats.items():

        if stats["files"] == 0:
            continue

        print(
            f"{repo}: "
            f"{stats['channels']} channels "
            f"from "
            f"{stats['successful']}/"
            f"{stats['files']} files"
        )

    # ========================================================
    # FAILED FILES
    # ========================================================

    if failed_files:

        print()
        print(
            f"FAILED FILES: "
            f"{len(failed_files)}"
        )

        for repo, path, error in failed_files:

            print(
                f"  {repo}/{path}"
            )

            print(
                f"    {error}"
            )


if __name__ == "__main__":
    main()
