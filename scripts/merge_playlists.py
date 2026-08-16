#!/usr/bin/env python3

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict


# ============================================================
# CONFIG
# ============================================================

OWNER = "BuddyChewChew"
OUTPUT_FILE = "fast-all-regions.m3u"

GITHUB_API = "https://api.github.com"

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; FAST-All-Regions-Builder/1.0)"
)

PLAYLIST_EXTENSIONS = (
    ".m3u",
    ".m3u8",
)


# ============================================================
# SPECIAL CATEGORY SOURCES
#
# These repositories are forced into ONE category.
#
# Their original group-title is NEVER used.
# ============================================================

SPECIAL_GROUPS = {
    "app-m3u-generator": "App M3U",

    "buddylive": "Buddy Live",
    "buddylive-combined": "Buddy Live",
    "buddylive_v2": "Buddy Live",

    "My-Streams": "My-Streams",
}


# ============================================================
# SOURCE NAME NORMALIZATION
# ============================================================

SOURCE_NAME_MAP = {

    "airy-playlist-generator":
        "Airy",

    "app-m3u-generator":
        "App M3U",

    "buddylive":
        "Buddy Live",

    "buddylive-combined":
        "Buddy Live",

    "buddylive_v2":
        "Buddy Live",

    "distro-playlist-generator":
        "DistroTV",

    "dlxes":
        "dlxes",

    "lg-playlist-generator":
        "LG",

    "lg-playlist-generator2":
        "LG",

    "My-Streams":
        "My-Streams",

    "nz":
        "NZ",

    "oly":
        "oly",

    "plex":
        "Plex",

    "plex-alt-fast-channels":
        "Plex",

    "pluto":
        "Pluto TV",

    "RakutenTV":
        "Rakuten TV",

    "roku-playlist-generator":
        "Roku",

    "samsungtvplus":
        "Samsung TV Plus",

    "sports":
        "Sports",

    "tcl-playlist-generator":
        "TCL",

    "tubi-scraper":
        "Tubi",

    "vod":
        "vod",

    "whiplash-epg":
        "whiplash-epg",

    "xumo-playlist-generator":
        "Xumo",
}


# ============================================================
# LOW-PRIORITY GROUPS
#
# IMPORTANT:
#
# ALL OTHER SOURCES HAVE HIGHER PRIORITY THAN THESE.
#
# Priority from LOWEST to HIGHEST:
#
#   App M3U
#   My-Streams
#   Buddy Live
#   ALL OTHER SOURCES
#
# Therefore:
#
# App M3U + Samsung TV Plus
# -> App M3U duplicate removed
# -> Samsung TV Plus kept
#
# My-Streams + TCL
# -> My-Streams duplicate removed
# -> TCL kept
#
# Buddy Live + Plex
# -> Buddy Live duplicate removed
# -> Plex kept
#
# Plex + Samsung TV Plus
# -> BOTH KEPT
#
# TCL + Plex
# -> BOTH KEPT
# ============================================================

LOW_PRIORITY_GROUPS = {
    "App M3U": 1,
    "My-Streams": 2,
    "Buddy Live": 3,
}


# ============================================================
# HTTP HELPERS
# ============================================================

def http_get(url, timeout=45, retries=3):

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    request = urllib.request.Request(
        url,
        headers=headers
    )

    last_error = None

    for attempt in range(retries):

        try:

            with urllib.request.urlopen(
                request,
                timeout=timeout
            ) as response:

                return response.read()

        except urllib.error.HTTPError as exc:

            last_error = exc

            if exc.code == 404:
                raise

            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue

            raise

        except (
            urllib.error.URLError,
            TimeoutError
        ) as exc:

            last_error = exc

            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue

            raise

    raise last_error


def http_get_text(url, timeout=45, retries=3):

    data = http_get(
        url,
        timeout=timeout,
        retries=retries
    )

    return data.decode(
        "utf-8-sig",
        errors="replace"
    )


def github_api(path, retries=3):

    url = GITHUB_API + path

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }

    request = urllib.request.Request(
        url,
        headers=headers
    )

    # --------------------------------------------------------
    # GitHub Actions GITHUB_TOKEN
    # --------------------------------------------------------

    github_token = None

    try:
        github_token = (
            __import__("os")
            .environ
            .get("GITHUB_TOKEN")
        )
    except Exception:
        pass

    if github_token:

        request.add_header(
            "Authorization",
            f"Bearer {github_token}"
        )

    last_error = None

    for attempt in range(retries):

        try:

            with urllib.request.urlopen(
                request,
                timeout=45
            ) as response:

                remaining = response.headers.get(
                    "X-RateLimit-Remaining"
                )

                if remaining is not None:

                    print(
                        f"  GitHub API remaining: "
                        f"{remaining}"
                    )

                return json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )

        except urllib.error.HTTPError as exc:

            last_error = exc

            if exc.code == 404:
                raise

            if exc.code == 403:

                remaining = exc.headers.get(
                    "X-RateLimit-Remaining"
                )

                if remaining == "0":

                    raise RuntimeError(
                        "GitHub API rate limit exceeded"
                    )

            if attempt < retries - 1:

                time.sleep(
                    min(
                        10,
                        2 ** attempt
                    )
                )

                continue

            raise

        except (
            urllib.error.URLError,
            TimeoutError
        ) as exc:

            last_error = exc

            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue

            raise

    raise last_error


# ============================================================
# GROUP CLEANING
# ============================================================

def clean_group(group):

    if not group:
        return ""

    group = group.strip()

    group = re.sub(
        r"\s+",
        " ",
        group
    )

    return group


def get_first_level_group(group):

    group = clean_group(group)

    if not group:
        return ""

    separators = (
        "|",
        " > ",
        " / ",
        "\\",
    )

    for separator in separators:

        if separator in group:

            group = group.split(
                separator,
                1
            )[0].strip()

            break

    return group


# ============================================================
# FINAL GROUP DETERMINATION
# ============================================================

def get_final_group(
    repo_name,
    original_group
):

    # ========================================================
    # SPECIAL SOURCE OVERRIDE
    #
    # NEVER inspect original group-title.
    # ========================================================

    if repo_name in SPECIAL_GROUPS:

        return SPECIAL_GROUPS[
            repo_name
        ]

    # ========================================================
    # NORMAL SOURCES
    # ========================================================

    source = SOURCE_NAME_MAP.get(
        repo_name,
        repo_name
    )

    first_level = get_first_level_group(
        original_group
    )

    if not first_level:

        return source

    return (
        f"{source} | "
        f"{first_level}"
    )


# ============================================================
# M3U ATTRIBUTE PARSER
# ============================================================

ATTRIBUTE_PATTERN = re.compile(
    r'([\w:-]+)="([^"]*)"'
)


def parse_extinf(line):

    attributes = {}

    comma = line.find(",")

    if comma >= 0:

        metadata = line[:comma]

        channel_name = line[
            comma + 1:
        ].strip()

    else:

        metadata = line
        channel_name = ""

    for match in ATTRIBUTE_PATTERN.finditer(
        metadata
    ):

        key = match.group(1)
        value = match.group(2)

        attributes[key] = value

    return (
        attributes,
        channel_name
    )


# ============================================================
# M3U PARSER
# ============================================================

def parse_m3u(text):

    entries = []

    current_attributes = None
    current_name = None
    waiting_for_url = False

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        # ----------------------------------------------------
        # EXTINF
        # ----------------------------------------------------

        if line.startswith("#EXTINF"):

            attributes, name = parse_extinf(
                line
            )

            current_attributes = attributes
            current_name = name

            waiting_for_url = True

            continue

        # ----------------------------------------------------
        # Other M3U directives
        # ----------------------------------------------------

        if line.startswith("#"):

            continue

        # ----------------------------------------------------
        # STREAM URL
        # ----------------------------------------------------

        if waiting_for_url:

            stream_url = line

            if stream_url:

                entries.append(
                    {
                        "name":
                            current_name or "",

                        "attrs":
                            dict(
                                current_attributes
                                or {}
                            ),

                        "url":
                            stream_url,
                    }
                )

            current_attributes = None
            current_name = None
            waiting_for_url = False

    return entries


# ============================================================
# GITHUB REPOSITORY DISCOVERY
# ============================================================

def discover_repositories():

    repositories = []

    page = 1

    while True:

        path = (
            f"/users/"
            f"{urllib.parse.quote(OWNER)}"
            f"/repos"
            f"?per_page=100"
            f"&page={page}"
        )

        data = github_api(path)

        if not data:
            break

        for repo in data:

            if repo.get("fork"):
                continue

            name = repo.get("name")

            if name:

                repositories.append(
                    name
                )

        if len(data) < 100:
            break

        page += 1

    return sorted(
        repositories,
        key=str.lower
    )


# ============================================================
# PLAYLIST FILE DISCOVERY
# ============================================================

def discover_playlist_files(repo_name):

    repo_path = (
        f"/repos/"
        f"{urllib.parse.quote(OWNER)}"
        f"/{urllib.parse.quote(repo_name)}"
    )

    repo_data = github_api(
        repo_path
    )

    default_branch = repo_data.get(
        "default_branch",
        "main"
    )

    tree_path = (
        f"/repos/"
        f"{urllib.parse.quote(OWNER)}"
        f"/{urllib.parse.quote(repo_name)}"
        f"/git/trees/"
        f"{urllib.parse.quote(default_branch)}"
        f"?recursive=1"
    )

    tree_data = github_api(
        tree_path
    )

    files = []

    for item in tree_data.get(
        "tree",
        []
    ):

        if item.get("type") != "blob":
            continue

        path = item.get(
            "path",
            ""
        )

        if path.lower().endswith(
            PLAYLIST_EXTENSIONS
        ):

            files.append(path)

    return sorted(
        files,
        key=str.lower
    )


# ============================================================
# RAW GITHUB URL
# ============================================================

def raw_url(
    repo_name,
    file_path
):

    encoded_parts = []

    for part in file_path.split("/"):

        encoded_parts.append(
            urllib.parse.quote(
                part,
                safe=""
            )
        )

    encoded_path = "/".join(
        encoded_parts
    )

    return (
        "https://raw.githubusercontent.com/"
        f"{OWNER}/"
        f"{urllib.parse.quote(repo_name)}/"
        f"HEAD/"
        f"{encoded_path}"
    )


# ============================================================
# EXTINF OUTPUT
# ============================================================

def rebuild_extinf(
    entry,
    final_group
):

    attributes = dict(
        entry["attrs"]
    )

    # --------------------------------------------------------
    # Replace ONLY group-title
    # --------------------------------------------------------

    attributes["group-title"] = (
        final_group
    )

    # --------------------------------------------------------
    # Preferred ordering
    # --------------------------------------------------------

    preferred_order = [

        "tvg-id",
        "tvg-name",
        "tvg-logo",

        "group-title",

        "tvg-language",
        "tvg-country",

        "tvg-url",
        "x-tvg-url",

        "catchup",
        "catchup-days",
        "catchup-source",
    ]

    ordered_keys = []

    for key in preferred_order:

        if key in attributes:

            ordered_keys.append(
                key
            )

    # --------------------------------------------------------
    # Preserve every other attribute
    # --------------------------------------------------------

    for key in attributes:

        if key not in ordered_keys:

            ordered_keys.append(
                key
            )

    # --------------------------------------------------------
    # Build attributes
    # --------------------------------------------------------

    attribute_string = " ".join(
        f'{key}="{attributes[key]}"'
        for key in ordered_keys
    )

    channel_name = (
        entry["name"]
    )

    return (
        "#EXTINF:-1 "
        f"{attribute_string},"
        f"{channel_name}"
    )


# ============================================================
# PRIORITY-BASED DUPLICATE REMOVAL
# ============================================================

def remove_duplicates(entries):

    print(
        "Removing duplicates with source priority..."
    )

    print()

    # ========================================================
    # NORMAL SOURCES
    #
    # Any URL found in ANY normal source defeats the same
    # URL in App M3U / My-Streams / Buddy Live.
    #
    # Normal sources NEVER defeat each other.
    # ========================================================

    normal_source_urls = set()

    for entry in entries:

        stream_url = entry["url"].strip()

        if not stream_url:
            continue

        final_group = entry["final_group"]

        if final_group not in LOW_PRIORITY_GROUPS:

            normal_source_urls.add(
                stream_url
            )

    # ========================================================
    # URLS FROM LOW-PRIORITY GROUPS
    # ========================================================

    low_priority_urls = defaultdict(set)

    for entry in entries:

        stream_url = entry["url"].strip()

        if not stream_url:
            continue

        final_group = entry["final_group"]

        if final_group in LOW_PRIORITY_GROUPS:

            low_priority_urls[
                final_group
            ].add(
                stream_url
            )

    # ========================================================
    # MARK ENTRIES TO REMOVE
    # ========================================================

    urls_to_remove = set()

    # ========================================================
    # NORMAL SOURCES BEAT ALL THREE SPECIAL SOURCES
    # ========================================================

    for group in LOW_PRIORITY_GROUPS:

        for stream_url in low_priority_urls[group]:

            if stream_url in normal_source_urls:

                urls_to_remove.add(
                    (
                        group,
                        stream_url
                    )
                )

    # ========================================================
    # PRIORITY BETWEEN THE THREE SPECIAL SOURCES
    #
    # Higher number = higher priority.
    #
    # Buddy Live > My-Streams > App M3U
    # ========================================================

    for entry in entries:

        stream_url = entry["url"].strip()

        if not stream_url:
            continue

        current_group = entry["final_group"]

        if current_group not in LOW_PRIORITY_GROUPS:
            continue

        current_priority = LOW_PRIORITY_GROUPS[
            current_group
        ]

        for other_group, other_priority in (
            LOW_PRIORITY_GROUPS.items()
        ):

            if other_priority <= current_priority:
                continue

            if stream_url in low_priority_urls.get(
                other_group,
                set()
            ):

                urls_to_remove.add(
                    (
                        current_group,
                        stream_url
                    )
                )

                break

    # ========================================================
    # BUILD FINAL LIST
    # ========================================================

    unique_entries = []

    duplicate_count = 0

    seen_low_priority = set()

    for entry in entries:

        stream_url = entry["url"].strip()

        if not stream_url:
            continue

        current_group = entry["final_group"]

        # ----------------------------------------------------
        # Remove lower-priority duplicate
        # ----------------------------------------------------

        if (
            current_group,
            stream_url
        ) in urls_to_remove:

            duplicate_count += 1

            continue

        # ----------------------------------------------------
        # Exact duplicate INSIDE the same low-priority group
        # ----------------------------------------------------

        if current_group in LOW_PRIORITY_GROUPS:

            key = (
                current_group,
                stream_url
            )

            if key in seen_low_priority:

                duplicate_count += 1

                continue

            seen_low_priority.add(
                key
            )

        # ----------------------------------------------------
        # NORMAL SOURCES
        #
        # ALWAYS KEEP.
        #
        # Even if the same URL exists in another normal
        # source, both entries remain.
        # ----------------------------------------------------

        unique_entries.append(
            entry
        )

    return (
        unique_entries,
        duplicate_count
    )


# ============================================================
# MAIN BUILD
# ============================================================

def build():

    print("=" * 70)
    print("FAST ALL REGIONS BUILDER")
    print("=" * 70)

    print(
        f"Source: {OWNER}"
    )

    print(
        "Playlist discovery: "
        "GitHub repository tree"
    )

    print(
        "Category source: "
        "ORIGINAL M3U group-title"
    )

    print(
        "Group depth: "
        "FIRST LEVEL ONLY"
    )

    print(
        "Special category sources:"
    )

    print(
        "  App M3U     -> App M3U"
    )

    print(
        "  Buddy Live  -> Buddy Live"
    )

    print(
        "  My-Streams  -> My-Streams"
    )

    print(
        "Normal sources have priority over "
        "App M3U / My-Streams / Buddy Live"
    )

    print(
        "Region guessing: DISABLED"
    )

    print(
        "Source guessing: DISABLED"
    )

    print(
        "Channel-name guessing: DISABLED"
    )

    print(
        "Duplicate detection: "
        "PRIORITY-BASED"
    )

    print()

    print(
        "GitHub API authentication: "
        "ENABLED"
    )

    print(
        "GitHub API rate-limit protection: "
        "ENABLED"
    )

    print()

    # ========================================================
    # DISCOVER REPOSITORIES
    # ========================================================

    try:

        repositories = (
            discover_repositories()
        )

    except Exception as exc:

        print()
        print(
            "ERROR: Could not discover "
            "repositories."
        )

        print(
            str(exc)
        )

        sys.exit(1)

    print(
        f"Repositories discovered: "
        f"{len(repositories)}"
    )

    print()

    # ========================================================
    # STORAGE
    # ========================================================

    all_entries = []

    source_stats = defaultdict(
        lambda: {
            "entries": 0,
            "files_ok": 0,
            "files_found": 0,
        }
    )

    empty_playlists = []

    failed_playlists = []

    # ========================================================
    # PROCESS REPOSITORIES
    # ========================================================

    for repo_name in repositories:

        print(
            f"=== {repo_name} ==="
        )

        try:

            playlist_files = (
                discover_playlist_files(
                    repo_name
                )
            )

        except Exception as exc:

            print(
                "  [ERROR] Cannot read "
                "repository tree: "
                f"{exc}"
            )

            print()

            continue

        print(
            f"Found "
            f"{len(playlist_files)} "
            f"playlist files"
        )

        source_stats[
            repo_name
        ]["files_found"] = (
            len(playlist_files)
        )

        # ====================================================
        # PROCESS PLAYLIST FILES
        # ====================================================

        for playlist_path in playlist_files:

            try:

                source_url = raw_url(
                    repo_name,
                    playlist_path
                )

                text = http_get_text(
                    source_url
                )

                entries = parse_m3u(
                    text
                )

                if not entries:

                    print(
                        f"  [EMPTY] "
                        f"{playlist_path}"
                    )

                    empty_playlists.append(
                        f"{repo_name}/"
                        f"{playlist_path}"
                    )

                    continue

                print(
                    f"  [OK] "
                    f"{playlist_path}: "
                    f"{len(entries)} entries"
                )

                source_stats[
                    repo_name
                ]["files_ok"] += 1

                source_stats[
                    repo_name
                ]["entries"] += len(
                    entries
                )

                # =================================================
                # PROCESS CHANNELS
                # =================================================

                for entry in entries:

                    # ------------------------------------------------
                    # SPECIAL SOURCE LOGIC
                    #
                    # DO NOT read original group-title.
                    # ------------------------------------------------

                    if repo_name in SPECIAL_GROUPS:

                        final_group = (
                            SPECIAL_GROUPS[
                                repo_name
                            ]
                        )

                    else:

                        original_group = (
                            entry["attrs"].get(
                                "group-title",
                                ""
                            )
                        )

                        final_group = (
                            get_final_group(
                                repo_name,
                                original_group
                            )
                        )

                    entry["repo"] = (
                        repo_name
                    )

                    entry["playlist_path"] = (
                        playlist_path
                    )

                    entry["final_group"] = (
                        final_group
                    )

                    all_entries.append(
                        entry
                    )

            except Exception as exc:

                print(
                    f"  [SKIP] "
                    f"{playlist_path}: "
                    f"{exc}"
                )

                failed_playlists.append(
                    f"{repo_name}/"
                    f"{playlist_path}"
                )

        print()

    # ========================================================
    # PRIORITY-BASED DUPLICATE REMOVAL
    # ========================================================

    (
        unique_entries,
        duplicate_count
    ) = remove_duplicates(
        all_entries
    )

    # ========================================================
    # FINAL CATEGORY COUNT
    # ========================================================

    category_counter = Counter()

    for entry in unique_entries:

        category_counter[
            entry["final_group"]
        ] += 1

    # ========================================================
    # SAFETY CHECK
    #
    # These three sources MUST NOT generate subcategories.
    # ========================================================

    forbidden_prefixes = (
        "App M3U |",
        "Buddy Live |",
        "My-Streams |",
    )

    bad_special_categories = []

    for category in category_counter:

        for prefix in forbidden_prefixes:

            if category.startswith(prefix):

                bad_special_categories.append(
                    category
                )

    if bad_special_categories:

        print()
        print(
            "ERROR: Special-source "
            "subcategories detected!"
        )

        for category in sorted(
            set(bad_special_categories)
        ):

            print(
                f"  {category}"
            )

        print()

        sys.exit(
            "BUILD STOPPED: "
            "special category validation failed"
        )

    # ========================================================
    # WRITE OUTPUT
    # ========================================================

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as output:

        # ----------------------------------------------------
        # M3U HEADER
        # ----------------------------------------------------

        output.write(
            "#EXTM3U\n"
        )

        # ----------------------------------------------------
        # CHANNELS
        # ----------------------------------------------------

        for entry in unique_entries:

            output.write(
                rebuild_extinf(
                    entry,
                    entry["final_group"]
                )
                + "\n"
            )

            output.write(
                entry["url"].strip()
                + "\n"
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("=" * 70)
    print("BUILD COMPLETE")
    print("=" * 70)

    print(
        f"Repositories discovered: "
        f"{len(repositories)}"
    )

    print(
        f"Playlist entries read: "
        f"{len(all_entries)}"
    )

    print(
        f"Unique playlist entries: "
        f"{len(unique_entries)}"
    )

    print(
        f"Priority duplicates removed: "
        f"{duplicate_count}"
    )

    print(
        f"Categories: "
        f"{len(category_counter)}"
    )

    print(
        f"Output: "
        f"{OUTPUT_FILE}"
    )

    # ========================================================
    # CATEGORY SUMMARY
    # ========================================================

    print()
    print(
        "CATEGORY SUMMARY"
    )

    print(
        "-" * 70
    )

    for category, count in sorted(
        category_counter.items(),
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

    for repo_name in repositories:

        stats = source_stats.get(
            repo_name
        )

        if not stats:
            continue

        if stats["files_found"] == 0:
            continue

        print(
            f"{repo_name}: "
            f"{stats['entries']} entries "
            f"from "
            f"{stats['files_ok']}/"
            f"{stats['files_found']} files"
        )

    # ========================================================
    # EMPTY PLAYLISTS
    # ========================================================

    if empty_playlists:

        print()
        print(
            f"EMPTY PLAYLISTS: "
            f"{len(empty_playlists)}"
        )

        for playlist in empty_playlists:

            print(
                f"  {playlist}"
            )

    # ========================================================
    # FAILED PLAYLISTS
    # ========================================================

    if failed_playlists:

        print()
        print(
            f"FAILED PLAYLISTS: "
            f"{len(failed_playlists)}"
        )

        for playlist in failed_playlists:

            print(
                f"  {playlist}"
            )

    print()
    print("Done.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    build()
