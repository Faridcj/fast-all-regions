#!/usr/bin/env python3

import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import json
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

# Only these extensions are considered playlist files.
PLAYLIST_EXTENSIONS = (
    ".m3u",
    ".m3u8",
)

# Repositories that should be represented by ONE category only.
SINGLE_CATEGORY_SOURCES = {
    "App M3U",
    "Buddy Live",
    "My-Streams",
}


# ============================================================
# HTTP
# ============================================================

def http_get(url, timeout=30, retries=3):
    """
    Download a URL using urllib only.
    No third-party dependencies.
    """

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    request = urllib.request.Request(url, headers=headers)

    last_error = None

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()

        except urllib.error.HTTPError as exc:
            last_error = exc

            # GitHub rate limit
            if exc.code == 403:
                retry_after = exc.headers.get("Retry-After")

                if retry_after:
                    try:
                        wait = min(int(retry_after), 30)
                    except ValueError:
                        wait = 5
                else:
                    wait = 5

                if attempt < retries - 1:
                    time.sleep(wait)
                    continue

            if exc.code == 404:
                raise

            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue

            raise

        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc

            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue

            raise

    raise last_error


def http_get_text(url, timeout=30, retries=3):
    data = http_get(url, timeout=timeout, retries=retries)

    # UTF-8 is standard for M3U.
    # Replace malformed bytes instead of killing the entire build.
    return data.decode("utf-8-sig", errors="replace")


def github_api(path):
    url = f"{GITHUB_API}{path}"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }

    request = urllib.request.Request(url, headers=headers)

    last_error = None

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            last_error = exc

            if exc.code == 403:
                remaining = exc.headers.get("X-RateLimit-Remaining")

                # If the API rate limit is exhausted, stop using
                # the API rather than hammering it.
                if remaining == "0":
                    raise RuntimeError(
                        "GitHub API rate limit exceeded"
                    )

                if attempt < 2:
                    time.sleep(5)
                    continue

            if attempt < 2:
                time.sleep(2 ** attempt)
                continue

            raise

        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc

            if attempt < 2:
                time.sleep(2 ** attempt)
                continue

            raise

    raise last_error


# ============================================================
# SOURCE NAME NORMALIZATION
# ============================================================

def normalize_source_name(repo_name):
    """
    Convert repository names into clean source names.

    IMPORTANT:
    We do NOT infer the source from channel names,
    URLs, regions, or group titles.

    The source is strictly the repository.
    """

    mapping = {
        "airy-playlist-generator": "Airy",

        "app-m3u-generator": "App M3U",

        "buddylive": "Buddy Live",
        "buddylive-combined": "Buddy Live",
        "buddylive_v2": "Buddy Live",

        "lg-playlist-generator": "LG",
        "lg-playlist-generator2": "LG",

        "My-Streams": "My-Streams",

        "nz": "NZ",

        "plex": "Plex",
        "plex-alt-fast-channels": "Plex",

        "pluto": "Pluto TV",

        "RakutenTV": "Rakuten TV",

        "roku-playlist-generator": "Roku",

        "samsungtvplus": "Samsung TV Plus",

        "tcl-playlist-generator": "TCL",

        "tubi-scraper": "Tubi",

        "xumo-playlist-generator": "Xumo",
    }

    return mapping.get(repo_name, repo_name)


# ============================================================
# GROUP NORMALIZATION
# ============================================================

def clean_group_text(group):
    if not group:
        return ""

    group = group.strip()

    # Collapse excessive whitespace.
    group = re.sub(r"\s+", " ", group)

    return group


def get_first_level_group(group):
    """
    Keep ONLY the first group level.

    Example:

        News | US | National

    becomes:

        News
    """

    group = clean_group_text(group)

    if not group:
        return ""

    # Support common hierarchy separators.
    separators = [
        "|",
        " > ",
        " / ",
        "\\",
    ]

    for separator in separators:
        if separator in group:
            group = group.split(separator, 1)[0].strip()
            break

    return group


def normalize_group(repo_name, original_group):
    """
    Build the final output group-title.

    Rules:

    App M3U
        ALL groups -> App M3U

    Buddy Live
        ALL groups -> Buddy Live

    My-Streams
        ALL groups -> My-Streams

    Everything else:
        Source | First Level Original Group

    No guessing.
    """

    source = normalize_source_name(repo_name)

    # These sources intentionally have ONE category.
    if source in SINGLE_CATEGORY_SOURCES:
        return source

    first_level = get_first_level_group(original_group)

    if not first_level:
        return source

    return f"{source} | {first_level}"


# ============================================================
# M3U PARSER
# ============================================================

ATTR_PATTERN = re.compile(
    r'([\w-]+)="([^"]*)"'
)


def parse_extinf(line):
    """
    Parse #EXTINF attributes.

    Returns:
        attributes, display_name
    """

    attributes = {}

    if not line.startswith("#EXTINF"):
        return attributes, ""

    comma_position = line.find(",")

    if comma_position >= 0:
        metadata = line[:comma_position]
        display_name = line[comma_position + 1:].strip()
    else:
        metadata = line
        display_name = ""

    for match in ATTR_PATTERN.finditer(metadata):
        key = match.group(1)
        value = match.group(2)
        attributes[key] = value

    return attributes, display_name


def parse_m3u(text):
    """
    Parse an M3U/M3U8 playlist.

    We preserve:
      - channel name
      - original EXTINF attributes
      - stream URL

    We do NOT guess metadata.
    """

    lines = text.splitlines()

    entries = []

    current_extinf = None
    current_name = None
    current_attrs = None

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#EXTINF"):
            attrs, name = parse_extinf(line)

            current_extinf = line
            current_name = name
            current_attrs = attrs

            continue

        # Ignore all other # directives.
        if line.startswith("#"):
            continue

        # This is the stream URL.
        if current_extinf is not None:

            url = line.strip()

            if url:
                entries.append({
                    "name": current_name or "",
                    "attrs": dict(current_attrs or {}),
                    "url": url,
                })

            current_extinf = None
            current_name = None
            current_attrs = None

    return entries


# ============================================================
# REPOSITORY DISCOVERY
# ============================================================

def discover_repositories():
    """
    Discover public repositories belonging to OWNER.

    We use GitHub's public API for repository discovery.
    """

    repositories = []

    page = 1

    while True:
        path = (
            f"/users/{urllib.parse.quote(OWNER)}"
            f"/repos?per_page=100&page={page}"
        )

        data = github_api(path)

        if not data:
            break

        for repo in data:
            if repo.get("fork"):
                continue

            name = repo.get("name")

            if name:
                repositories.append(name)

        if len(data) < 100:
            break

        page += 1

    return sorted(
        repositories,
        key=lambda x: x.lower()
    )


# ============================================================
# REPOSITORY TREE
# ============================================================

def discover_playlist_files(repo_name):
    """
    Discover playlist files from the repository tree.

    Uses the Git Git Trees API.

    This avoids guessing filenames.
    """

    # Get repository metadata first.
    repo_path = (
        f"/repos/{urllib.parse.quote(OWNER)}"
        f"/{urllib.parse.quote(repo_name)}"
    )

    repo_data = github_api(repo_path)

    default_branch = repo_data.get(
        "default_branch",
        "main"
    )

    tree_path = (
        f"/repos/{urllib.parse.quote(OWNER)}"
        f"/{urllib.parse.quote(repo_name)}"
        f"/git/trees/{urllib.parse.quote(default_branch)}"
        f"?recursive=1"
    )

    tree_data = github_api(tree_path)

    files = []

    for item in tree_data.get("tree", []):
        if item.get("type") != "blob":
            continue

        path = item.get("path", "")

        lower_path = path.lower()

        if lower_path.endswith(PLAYLIST_EXTENSIONS):
            files.append(path)

    return sorted(
        files,
        key=lambda x: x.lower()
    )


# ============================================================
# RAW FILE URL
# ============================================================

def raw_url(repo_name, path):
    encoded_path = "/".join(
        urllib.parse.quote(part)
        for part in path.split("/")
    )

    return (
        f"https://raw.githubusercontent.com/"
        f"{OWNER}/"
        f"{urllib.parse.quote(repo_name)}/"
        f"HEAD/{encoded_path}"
    )


# ============================================================
# OUTPUT WRITER
# ============================================================

def rebuild_extinf(entry, final_group):
    """
    Rebuild EXTINF while preserving original metadata.

    We change ONLY:
        group-title

    Everything else is retained.
    """

    attrs = dict(entry["attrs"])

    attrs["group-title"] = final_group

    # Keep attribute ordering reasonably stable.
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
        if key in attrs:
            ordered_keys.append(key)

    for key in attrs:
        if key not in ordered_keys:
            ordered_keys.append(key)

    attr_string = " ".join(
        f'{key}="{attrs[key]}"'
        for key in ordered_keys
    )

    name = entry["name"]

    if attr_string:
        return f"#EXTINF:-1 {attr_string},{name}"

    return f"#EXTINF:-1,{name}"


# ============================================================
# BUILD
# ============================================================

def build():
    print("=" * 70)
    print("FAST ALL REGIONS BUILDER")
    print("=" * 70)

    print(f"Source: {OWNER}")
    print("Playlist discovery: GitHub repository tree")
    print("Category source: ORIGINAL M3U group-title")
    print("Group depth: FIRST LEVEL ONLY")
    print("Region guessing: DISABLED")
    print("Source guessing: DISABLED")
    print("Channel-name guessing: DISABLED")
    print("Duplicate detection: STREAM URL")
    print()
    print("GitHub API authentication: DISABLED")
    print()

    try:
        repositories = discover_repositories()

    except Exception as exc:
        print()
        print("ERROR: Could not discover repositories.")
        print(str(exc))
        sys.exit(1)

    print(
        f"Repositories discovered: {len(repositories)}"
    )
    print()

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

    category_counter = Counter()

    for repo_name in repositories:

        print(f"=== {repo_name} ===")

        try:
            playlist_files = discover_playlist_files(
                repo_name
            )

        except Exception as exc:
            print(
                f"  [ERROR] Cannot read repository tree: "
                f"{exc}"
            )
            print()
            continue

        print(
            f"Found {len(playlist_files)} playlist files"
        )

        source_stats[repo_name]["files_found"] = (
            len(playlist_files)
        )

        for playlist_path in playlist_files:

            try:
                url = raw_url(
                    repo_name,
                    playlist_path
                )

                text = http_get_text(
                    url,
                    timeout=45,
                    retries=3
                )

                entries = parse_m3u(text)

                if not entries:
                    print(
                        f"  [EMPTY] {playlist_path}"
                    )

                    empty_playlists.append(
                        f"{repo_name}/{playlist_path}"
                    )

                    continue

                print(
                    f"  [OK] {playlist_path}: "
                    f"{len(entries)} entries"
                )

                source_stats[repo_name]["files_ok"] += 1
                source_stats[repo_name]["entries"] += len(
                    entries
                )

                for entry in entries:

                    original_group = entry["attrs"].get(
                        "group-title",
                        ""
                    )

                    final_group = normalize_group(
                        repo_name,
                        original_group
                    )

                    entry["repo"] = repo_name
                    entry["playlist_path"] = playlist_path
                    entry["final_group"] = final_group

                    all_entries.append(entry)

                    category_counter[final_group] += 1

            except Exception as exc:

                print(
                    f"  [SKIP] {playlist_path}: {exc}"
                )

                failed_playlists.append(
                    f"{repo_name}/{playlist_path}"
                )

        print()

    print("Removing duplicate stream URLs...")
    print()

    # ========================================================
    # DUPLICATE REMOVAL
    # ========================================================

    unique_entries = []
    seen_urls = set()

    duplicate_count = 0

    for entry in all_entries:

        url = entry["url"].strip()

        if not url:
            continue

        # EXACT stream URL comparison.
        if url in seen_urls:
            duplicate_count += 1
            continue

        seen_urls.add(url)

        unique_entries.append(entry)

    # Recalculate categories AFTER duplicate removal.
    final_category_counter = Counter(
        entry["final_group"]
        for entry in unique_entries
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
        f"{len(final_category_counter)}"
    )

    print(
        f"Output: "
        f"{OUTPUT_FILE}"
    )

    print()
    print("CATEGORY SUMMARY")
    print("-" * 70)

    for category, count in sorted(
        final_category_counter.items(),
        key=lambda item: (
            item[0].lower()
        )
    ):
        print(
            f"{category}: {count}"
        )

    print()
    print("SOURCE SUMMARY")
    print("-" * 70)

    for repo_name in repositories:

        stats = source_stats.get(
            repo_name,
            {
                "entries": 0,
                "files_ok": 0,
                "files_found": 0,
            }
        )

        if stats["files_found"] == 0:
            continue

        print(
            f"{repo_name}: "
            f"{stats['entries']} entries "
            f"from "
            f"{stats['files_ok']}/"
            f"{stats['files_found']} files"
        )

    if empty_playlists:
        print()
        print(
            f"EMPTY PLAYLISTS: "
            f"{len(empty_playlists)}"
        )

        for item in empty_playlists:
            print(
                f"  {item}"
            )

    if failed_playlists:
        print()
        print(
            f"FAILED PLAYLISTS: "
            f"{len(failed_playlists)}"
        )

        for item in failed_playlists:
            print(
                f"  {item}"
            )

    print()
    print("Done.")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    build()
