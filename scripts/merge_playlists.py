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
# SPECIAL SOURCES
#
# EVERYTHING belonging to these sources is forced into
# exactly ONE final category.
#
# Original group-title is NEVER used.
# Playlist filename is NEVER used.
# Multiple playlist files are merged.
# ============================================================

SPECIAL_REPO_GROUPS = {
    "app-m3u-generator": "App M3U",

    "buddylive": "Buddy Live",
    "buddylive-combined": "Buddy Live",
    "buddylive_v2": "Buddy Live",

    "my-streams": "My-Streams",
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

    "my-streams":
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

    "rakutentv":
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
# SPECIAL SOURCE DETECTION
# ============================================================

def normalize_repo_name(repo_name):

    return (
        repo_name
        .strip()
        .lower()
    )


def get_special_group(repo_name):

    repo_key = normalize_repo_name(
        repo_name
    )

    return SPECIAL_REPO_GROUPS.get(
        repo_key
    )


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

    last_error = None

    for attempt in range(retries):

        try:

            with urllib.request.urlopen(
                request,
                timeout=45
            ) as response:

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
    original_group=""
):
    """
    SPECIAL SOURCES ALWAYS OVERRIDE EVERYTHING.

    App M3U    -> App M3U
    Buddy Live -> Buddy Live
    My-Streams -> My-Streams

    Original group-title is ignored for special sources.

    All other repositories use:

        SOURCE | FIRST LEVEL ORIGINAL GROUP
    """

    # ========================================================
    # SPECIAL SOURCE OVERRIDE
    # ========================================================

    special_group = get_special_group(
        repo_name
    )

    if special_group:

        return special_group

    # ========================================================
    # NORMAL SOURCES
    # ========================================================

    repo_key = normalize_repo_name(
        repo_name
    )

    source = SOURCE_NAME_MAP.get(
        repo_key,
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
    """
    Rebuild EXTINF while preserving ALL
    original attributes.

    Only group-title is replaced.
    """

    attributes = dict(
        entry["attrs"]
    )

    # ========================================================
    # FORCE FINAL GROUP
    # ========================================================

    attributes["group-title"] = (
        final_group
    )

    # ========================================================
    # PREFERRED ATTRIBUTE ORDER
    # ========================================================

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

    # ========================================================
    # PRESERVE ALL OTHER ATTRIBUTES
    # ========================================================

    for key in attributes:

        if key not in ordered_keys:

            ordered_keys.append(
                key
            )

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
# FINAL SPECIAL SOURCE ENFORCEMENT
# ============================================================

def enforce_special_categories(
    entries
):
    """
    FINAL SAFETY NET.

    Regardless of what happened earlier,
    every entry from a special repository
    is forced into its single category.

    This runs immediately before writing.
    """

    for entry in entries:

        repo_name = entry.get(
            "repo",
            ""
        )

        special_group = get_special_group(
            repo_name
        )

        if special_group:

            entry["final_group"] = (
                special_group
            )

    return entries


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
        "Special source grouping: "
        "FORCED / MERGED"
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
        "STREAM URL"
    )

    print()

    print(
        "GitHub API authentication: "
        "DISABLED"
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
                    # SPECIAL SOURCES
                    #
                    # NEVER inspect original group-title.
                    # ------------------------------------------------

                    special_group = (
                        get_special_group(
                            repo_name
                        )
                    )

                    if special_group:

                        final_group = (
                            special_group
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
    # DUPLICATE STREAM URL REMOVAL
    # ========================================================

    print(
        "Removing duplicate stream URLs..."
    )

    print()

    unique_entries = []

    seen_urls = set()

    duplicate_count = 0

    for entry in all_entries:

        stream_url = (
            entry["url"].strip()
        )

        if not stream_url:
            continue

        if stream_url in seen_urls:

            duplicate_count += 1

            continue

        seen_urls.add(
            stream_url
        )

        unique_entries.append(
            entry
        )

    # ========================================================
    # FINAL SPECIAL SOURCE ENFORCEMENT
    # ========================================================

    unique_entries = (
        enforce_special_categories(
            unique_entries
        )
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
    # Special sources MUST have exactly one category each.
    # ========================================================

    special_expected = {
        "App M3U",
        "Buddy Live",
        "My-Streams",
    }

    bad_special_categories = []

    for category in category_counter:

        if (
            category.startswith("App M3U |")
            or
            category.startswith("Buddy Live |")
            or
            category.startswith("My-Streams |")
        ):

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

        output.write(
            "#EXTM3U\n"
        )

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
        f"Unique stream URLs: "
        f"{len(unique_entries)}"
    )

    print(
        f"Duplicate URLs removed: "
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
    # SPECIAL SOURCE SUMMARY
    # ========================================================

    print()
    print(
        "SPECIAL SOURCE SUMMARY"
    )

    print(
        "-" * 70
    )

    for category in (
        "App M3U",
        "Buddy Live",
        "My-Streams",
    ):

        print(
            f"{category}: "
            f"{category_counter.get(category, 0)}"
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
