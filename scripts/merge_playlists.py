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
# SOURCE NORMALIZATION
# ============================================================

SOURCE_NAMES = {

    # --------------------------------------------------------
    # AIRY
    # --------------------------------------------------------

    "airy-playlist-generator":
        "Airy",

    # --------------------------------------------------------
    # APP M3U
    # --------------------------------------------------------

    "app-m3u-generator":
        "App M3U",

    # --------------------------------------------------------
    # BUDDY LIVE
    # --------------------------------------------------------

    "buddylive":
        "Buddy Live",

    "buddylive-combined":
        "Buddy Live",

    "buddylive_v2":
        "Buddy Live",

    # --------------------------------------------------------
    # LG
    # --------------------------------------------------------

    "lg-playlist-generator":
        "LG",

    "lg-playlist-generator2":
        "LG",

    # --------------------------------------------------------
    # MY STREAMS
    # --------------------------------------------------------

    "My-Streams":
        "My-Streams",

    # --------------------------------------------------------
    # NZ
    # --------------------------------------------------------

    "nz":
        "NZ",

    # --------------------------------------------------------
    # PLEX
    # --------------------------------------------------------

    "plex":
        "Plex",

    "plex-alt-fast-channels":
        "Plex",

    # --------------------------------------------------------
    # PLUTO
    # --------------------------------------------------------

    "pluto":
        "Pluto TV",

    # --------------------------------------------------------
    # RAKUTEN
    # --------------------------------------------------------

    "RakutenTV":
        "Rakuten TV",

    # --------------------------------------------------------
    # ROKU
    # --------------------------------------------------------

    "roku-playlist-generator":
        "Roku",

    # --------------------------------------------------------
    # SAMSUNG TV PLUS
    # --------------------------------------------------------

    "samsungtvplus":
        "Samsung TV Plus",

    # --------------------------------------------------------
    # TCL
    # --------------------------------------------------------

    "tcl-playlist-generator":
        "TCL",

    # --------------------------------------------------------
    # TUBI
    # --------------------------------------------------------

    "tubi-scraper":
        "Tubi",

    # --------------------------------------------------------
    # XUMO
    # --------------------------------------------------------

    "xumo-playlist-generator":
        "Xumo",
}


# ============================================================
# HARD-CONSOLIDATED SOURCES
#
# IMPORTANT:
#
# These repositories MUST have exactly ONE group.
#
# Their original group-title is completely ignored.
# ============================================================

CONSOLIDATED_SOURCES = {

    "app-m3u-generator":
        "App M3U",

    "buddylive":
        "Buddy Live",

    "buddylive-combined":
        "Buddy Live",

    "buddylive_v2":
        "Buddy Live",

    "My-Streams":
        "My-Streams",
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

                time.sleep(
                    2 ** attempt
                )

                continue

            raise

        except (
            urllib.error.URLError,
            TimeoutError
        ) as exc:

            last_error = exc

            if attempt < retries - 1:

                time.sleep(
                    2 ** attempt
                )

                continue

            raise

    raise last_error


def http_get_text(
    url,
    timeout=45,
    retries=3
):

    data = http_get(
        url,
        timeout=timeout,
        retries=retries
    )

    return data.decode(
        "utf-8-sig",
        errors="replace"
    )


def github_api(
    path,
    retries=3
):

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

                time.sleep(
                    2 ** attempt
                )

                continue

            raise

    raise last_error


# ============================================================
# SOURCE NAME
# ============================================================

def normalize_source_name(repo_name):

    return SOURCE_NAMES.get(
        repo_name,
        repo_name
    )


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


# ============================================================
# FIRST LEVEL GROUP
# ============================================================

def get_first_level_group(group):

    """
    Used ONLY for sources that are NOT consolidated.

    Example:

        News | US | Local

    becomes:

        News
    """

    group = clean_group(
        group
    )

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
# FINAL GROUP
# ============================================================

def get_final_group(
    repo_name,
    original_group
):

    """
    Determines the ONLY group-title that will be written.

    ----------------------------------------------------------
    CONSOLIDATED SOURCES
    ----------------------------------------------------------

    App M3U
        -> App M3U

    Buddy Live
        -> Buddy Live

    My-Streams
        -> My-Streams

    Their original group-title is NEVER inspected.

    ----------------------------------------------------------
    OTHER SOURCES
    ----------------------------------------------------------

    Source | Original First-Level Group
    """

    # ========================================================
    # HARD CONSOLIDATION
    # ========================================================

    if repo_name in CONSOLIDATED_SOURCES:

        return CONSOLIDATED_SOURCES[
            repo_name
        ]

    # ========================================================
    # NORMAL SOURCE
    # ========================================================

    source = normalize_source_name(
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
    r'([\w-]+)="([^"]*)"'
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

        if line.startswith(
            "#EXTINF"
        ):

            attributes, name = (
                parse_extinf(line)
            )

            current_attributes = (
                attributes
            )

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

                entries.append({

                    "name":
                        current_name or "",

                    "attrs":
                        dict(
                            current_attributes
                            or {}
                        ),

                    "url":
                        stream_url,
                })

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

        data = github_api(
            path
        )

        if not data:
            break

        for repo in data:

            # Ignore forks.
            if repo.get("fork"):
                continue

            name = repo.get(
                "name"
            )

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

def discover_playlist_files(
    repo_name
):

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

            files.append(
                path
            )

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

    # ========================================================
    # CRITICAL OVERRIDE
    #
    # The ORIGINAL group-title is always destroyed.
    #
    # The ONLY group-title written to the final M3U is:
    #
    #     final_group
    #
    # This guarantees that consolidated sources cannot
    # leak their original thousands of group names.
    # ========================================================

    attributes[
        "group-title"
    ] = final_group

    preferred_order = [

        "tvg-id",

        "tvg-name",

        "tvg-logo",

        "group-title",

        "tvg-language",

        "tvg-country",

        "tvg-url",

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

    for key in attributes:

        if key not in ordered_keys:

            ordered_keys.append(
                key
            )

    attribute_string = " ".join(

        f'{key}="{attributes[key]}"'

        for key in ordered_keys
    )

    channel_name = entry[
        "name"
    ]

    return (
        "#EXTINF:-1 "
        f"{attribute_string},"
        f"{channel_name}"
    )


# ============================================================
# MAIN BUILD
# ============================================================

def build():

    print("=" * 70)

    print(
        "FAST ALL REGIONS BUILDER"
    )

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
        ][
            "files_found"
        ] = len(
            playlist_files
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

                # ------------------------------------------------
                # EMPTY
                # ------------------------------------------------

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

                # ------------------------------------------------
                # OK
                # ------------------------------------------------

                print(
                    f"  [OK] "
                    f"{playlist_path}: "
                    f"{len(entries)} entries"
                )

                source_stats[
                    repo_name
                ][
                    "files_ok"
                ] += 1

                source_stats[
                    repo_name
                ][
                    "entries"
                ] += len(
                    entries
                )

                # =================================================
                # PROCESS ENTRIES
                # =================================================

                for entry in entries:

                    original_group = (
                        entry[
                            "attrs"
                        ].get(
                            "group-title",
                            ""
                        )
                    )

                    # ------------------------------------------------
                    # FINAL CATEGORY
                    #
                    # This is the ONLY category decision.
                    # ------------------------------------------------

                    final_group = (
                        get_final_group(
                            repo_name,
                            original_group
                        )
                    )

                    entry[
                        "repo"
                    ] = repo_name

                    entry[
                        "playlist_path"
                    ] = playlist_path

                    entry[
                        "final_group"
                    ] = final_group

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
    # DUPLICATE STREAM REMOVAL
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
            entry[
                "url"
            ].strip()
        )

        if not stream_url:
            continue

        # ----------------------------------------------------
        # EXACT STREAM URL DEDUPLICATION
        # ----------------------------------------------------

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
    # FINAL CATEGORY COUNT
    # ========================================================

    category_counter = Counter()

    for entry in unique_entries:

        category_counter[
            entry[
                "final_group"
            ]
        ] += 1

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
                    entry[
                        "final_group"
                    ]
                )

                + "\n"
            )

            output.write(
                entry[
                    "url"
                ].strip()
                + "\n"
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("=" * 70)

    print(
        "BUILD COMPLETE"
    )

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

        if stats[
            "files_found"
        ] == 0:

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

    print(
        "Done."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    build()
