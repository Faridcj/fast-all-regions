#!/usr/bin/env python3

import os
import re
import sys
import time
from collections import Counter, defaultdict
from urllib.parse import quote

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    sys.exit("Python urllib is required.")

# ============================================================
# CONFIG
# ============================================================

OWNER = "BuddyChewChew"
OUTPUT_FILE = "fast-all-regions.m3u"

GITHUB_API = "https://api.github.com"

# GitHub token is optional.
# Recommended:
#   export GITHUB_TOKEN="ghp_..."
#
# Or add it as a GitHub Actions secret named GITHUB_TOKEN.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

REQUEST_TIMEOUT = 30

PLAYLIST_EXTENSIONS = (".m3u", ".m3u8")

# ------------------------------------------------------------
# Source display names
# ------------------------------------------------------------

SOURCE_NAMES = {
    "airy-playlist-generator": "Airy",
    "app-m3u-generator": "App M3U",

    "buddylive": "Buddy Live",
    "buddylive-combined": "Buddy Live",
    "buddylive_v2": "Buddy Live",

    "distro-playlist-generator": "DistroTV",

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

    "sports": "Sports",

    "tcl-playlist-generator": "TCL",

    "tubi-scraper": "Tubi",

    "whiplash-epg": "Whiplash",

    "xumo-playlist-generator": "Xumo",
}


# ============================================================
# HTTP
# ============================================================

def github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "fast-all-regions-builder",
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    return headers


def http_get(url, headers=None, timeout=REQUEST_TIMEOUT):
    req = Request(
        url,
        headers=headers or {
            "User-Agent": "fast-all-regions-builder"
        }
    )

    with urlopen(req, timeout=timeout) as response:
        return response.read()


def github_get_json(url):
    data = http_get(url, github_headers())

    import json
    return json.loads(data.decode("utf-8"))


# ============================================================
# GITHUB
# ============================================================

def discover_repositories():
    """
    Get all repositories owned by BuddyChewChew.

    Uses pagination.
    """

    repositories = []
    page = 1

    while True:
        url = (
            f"{GITHUB_API}/users/{quote(OWNER)}/repos"
            f"?per_page=100&page={page}"
            f"&type=all&sort=name"
        )

        try:
            data = github_get_json(url)
        except HTTPError as e:
            print(f"[ERROR] Cannot discover repositories: HTTP {e.code}")
            return repositories
        except Exception as e:
            print(f"[ERROR] Cannot discover repositories: {e}")
            return repositories

        if not data:
            break

        for repo in data:
            if not repo.get("fork", False):
                repositories.append(repo)

        if len(data) < 100:
            break

        page += 1

    return repositories


def discover_playlist_files(repo):
    """
    Read repository Git tree recursively.

    This is intentionally based on the actual GitHub repository tree,
    not guessed file names.
    """

    repo_name = repo["name"]
    default_branch = repo.get("default_branch") or "main"

    url = (
        f"{GITHUB_API}/repos/{quote(OWNER)}/{quote(repo_name)}"
        f"/git/trees/{quote(default_branch)}?recursive=1"
    )

    data = github_get_json(url)

    files = []

    for item in data.get("tree", []):
        if item.get("type") != "blob":
            continue

        path = item.get("path", "")

        if path.lower().endswith(PLAYLIST_EXTENSIONS):
            files.append(path)

    return sorted(files)


# ============================================================
# PLAYLIST DOWNLOAD
# ============================================================

def raw_github_url(repo_name, branch, path):
    encoded_path = quote(path, safe="/")

    return (
        f"https://raw.githubusercontent.com/"
        f"{quote(OWNER)}/{quote(repo_name)}/"
        f"{quote(branch)}/{encoded_path}"
    )


def download_playlist(repo, path):
    repo_name = repo["name"]
    branch = repo.get("default_branch") or "main"

    url = raw_github_url(repo_name, branch, path)

    data = http_get(
        url,
        headers={
            "User-Agent": "fast-all-regions-builder"
        }
    )

    return data.decode("utf-8", errors="replace")


# ============================================================
# M3U PARSER
# ============================================================

def parse_extinf(line):
    """
    Parse:

    #EXTINF:-1 tvg-id="..." tvg-name="..." group-title="News",
    Channel Name

    Returns:
        attributes, channel_name
    """

    if not line.startswith("#EXTINF"):
        return {}, ""

    comma = line.find(",")

    if comma >= 0:
        metadata = line[:comma]
        channel_name = line[comma + 1:].strip()
    else:
        metadata = line
        channel_name = ""

    attributes = {}

    # Supports quoted and unquoted attributes.
    pattern = re.compile(
        r'([A-Za-z0-9_-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s]+))'
    )

    for match in pattern.finditer(metadata):
        key = match.group(1)
        value = (
            match.group(2)
            if match.group(2) is not None
            else match.group(3)
            if match.group(3) is not None
            else match.group(4)
        )

        attributes[key] = value

    return attributes, channel_name


def first_group(group_title):
    """
    Keep only the first group level.

    Examples:

        "Sports | Football" -> "Sports"
        "News;US"            -> "News"
        "Sports / NBA"       -> "Sports"

    IMPORTANT:
    We do NOT invent or guess a group.
    We only split an existing group-title.
    """

    if not group_title:
        return ""

    value = group_title.strip()

    # Common hierarchical separators.
    for separator in ("|", ">>", ">", ";"):
        if separator in value:
            value = value.split(separator, 1)[0].strip()
            break

    return value


def parse_m3u(text):
    """
    Parse playlist entries.

    Only actual M3U metadata is used.

    No source guessing.
    No region guessing.
    No channel-name guessing.
    """

    entries = []

    lines = text.splitlines()

    current_extinf = None
    current_attrs = None
    current_name = None

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#EXTINF"):
            current_extinf = line
            current_attrs, current_name = parse_extinf(line)
            continue

        # Ignore all other # lines.
        if line.startswith("#"):
            continue

        # This is the stream URL following EXTINF.
        if current_extinf is not None:

            url = line.strip()

            if not url:
                current_extinf = None
                current_attrs = None
                current_name = None
                continue

            group_title = current_attrs.get("group-title", "").strip()

            entry = {
                "url": url,
                "name": current_name or current_attrs.get("tvg-name", "").strip(),
                "attrs": current_attrs.copy(),
                "group": first_group(group_title),
            }

            entries.append(entry)

            current_extinf = None
            current_attrs = None
            current_name = None

    return entries


# ============================================================
# OUTPUT
# ============================================================

def escape_attr(value):
    if value is None:
        return ""

    return str(value).replace('"', "'").strip()


def build_extinf(entry, source_name):
    """
    Rebuild EXTINF while preserving original M3U attributes.

    Only group-title is changed to:

        SOURCE | ORIGINAL_GROUP
    """

    attrs = entry["attrs"].copy()

    original_group = entry["group"]

    if original_group:
        final_group = f"{source_name} | {original_group}"
    else:
        final_group = source_name

    attrs["group-title"] = final_group

    # Preserve original attribute order as much as possible.
    preferred_order = [
        "tvg-id",
        "tvg-name",
        "tvg-logo",
        "tvg-language",
        "tvg-country",
        "tvg-url",
        "tvg-chno",
        "group-title",
    ]

    emitted = set()
    attr_parts = []

    for key in preferred_order:
        if key in attrs:
            value = escape_attr(attrs[key])
            attr_parts.append(f'{key}="{value}"')
            emitted.add(key)

    for key, value in attrs.items():
        if key in emitted:
            continue

        value = escape_attr(value)
        attr_parts.append(f'{key}="{value}"')

    channel_name = entry["name"] or attrs.get("tvg-name", "") or "Unknown"

    return (
        "#EXTINF:-1 "
        + " ".join(attr_parts)
        + ","
        + channel_name
    )


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

    if GITHUB_TOKEN:
        print("GitHub API authentication: ENABLED")
    else:
        print("GitHub API authentication: DISABLED")

    print()

    repositories = discover_repositories()

    print(f"Repositories discovered: {len(repositories)}")
    print()

    # --------------------------------------------------------
    # Data
    # --------------------------------------------------------

    all_entries = []

    source_stats = defaultdict(lambda: {
        "files_found": 0,
        "files_ok": 0,
        "files_empty": 0,
        "entries": 0,
    })

    failed_files = []
    empty_files = []

    # --------------------------------------------------------
    # Repository loop
    # --------------------------------------------------------

    for repo in repositories:

        repo_name = repo["name"]

        print(f"=== {repo_name} ===")

        try:
            playlist_files = discover_playlist_files(repo)

        except HTTPError as e:
            print(
                f"  [ERROR] Cannot read repository tree: "
                f"HTTP {e.code}"
            )
            print()
            continue

        except Exception as e:
            print(
                f"  [ERROR] Cannot read repository tree: {e}"
            )
            print()
            continue

        source_stats[repo_name]["files_found"] = len(playlist_files)

        if not playlist_files:
            print("Found 0 playlist files")
            print()
            continue

        print(f"Found {len(playlist_files)} playlist files")

        source_name = SOURCE_NAMES.get(repo_name, repo_name)

        for path in playlist_files:

            try:
                text = download_playlist(repo, path)

            except HTTPError as e:
                print(
                    f"  [SKIP] {path}: "
                    f"HTTP Error {e.code}: {e.reason}"
                )

                failed_files.append(
                    (repo_name, path, f"HTTP {e.code}")
                )

                continue

            except URLError as e:
                print(
                    f"  [SKIP] {path}: "
                    f"{e.reason}"
                )

                failed_files.append(
                    (repo_name, path, str(e.reason))
                )

                continue

            except Exception as e:
                print(
                    f"  [SKIP] {path}: {e}"
                )

                failed_files.append(
                    (repo_name, path, str(e))
                )

                continue

            entries = parse_m3u(text)

            if not entries:
                print(f"  [EMPTY] {path}")

                source_stats[repo_name]["files_empty"] += 1

                empty_files.append(
                    (repo_name, path)
                )

                continue

            print(
                f"  [OK] {path}: "
                f"{len(entries)} entries"
            )

            source_stats[repo_name]["files_ok"] += 1
            source_stats[repo_name]["entries"] += len(entries)

            for entry in entries:
                entry["source_repo"] = repo_name
                entry["source_name"] = source_name
                entry["source_file"] = path

                all_entries.append(entry)

    # --------------------------------------------------------
    # Deduplicate by EXACT STREAM URL
    # --------------------------------------------------------

    print()
    print("Removing duplicate stream URLs...")

    seen_urls = set()
    unique_entries = []
    duplicate_count = 0

    for entry in all_entries:

        url = entry["url"].strip()

        if not url:
            continue

        if url in seen_urls:
            duplicate_count += 1
            continue

        seen_urls.add(url)
        unique_entries.append(entry)

    # --------------------------------------------------------
    # Category statistics
    # --------------------------------------------------------

    category_counter = Counter()

    for entry in unique_entries:
        source = entry["source_name"]
        group = entry["group"]

        category = (
            f"{source} | {group}"
            if group
            else source
        )

        category_counter[category] += 1

    # --------------------------------------------------------
    # Write output
    # --------------------------------------------------------

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as f:

        f.write("#EXTM3U\n")

        for entry in unique_entries:

            extinf = build_extinf(
                entry,
                entry["source_name"]
            )

            f.write(extinf + "\n")
            f.write(entry["url"] + "\n")

    # --------------------------------------------------------
    # Final report
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("BUILD COMPLETE")
    print("=" * 70)

    print(f"Repositories discovered: {len(repositories)}")
    print(f"Playlist entries read: {len(all_entries)}")
    print(f"Unique stream URLs: {len(unique_entries)}")
    print(f"Duplicate URLs removed: {duplicate_count}")
    print(f"Categories: {len(category_counter)}")
    print(f"Output: {OUTPUT_FILE}")

    print()
    print("CATEGORY SUMMARY")
    print("-" * 70)

    for category, count in sorted(
        category_counter.items(),
        key=lambda x: (x[0].lower(), x[1])
    ):
        print(f"{category}: {count}")

    print()
    print("SOURCE SUMMARY")
    print("-" * 70)

    for repo_name in sorted(source_stats.keys(), key=str.lower):

        stats = source_stats[repo_name]

        print(
            f"{repo_name}: "
            f"{stats['entries']} entries "
            f"from "
            f"{stats['files_ok']}/{stats['files_found']} files"
        )

    if empty_files:
        print()
        print(f"EMPTY PLAYLISTS: {len(empty_files)}")

        for repo_name, path in empty_files:
            print(f"  {repo_name}/{path}")

    if failed_files:
        print()
        print(f"FAILED PLAYLISTS: {len(failed_files)}")

        for repo_name, path, reason in failed_files:
            print(f"  {repo_name}/{path}")
            print(f"    {reason}")

    print()
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    try:
        build()

    except KeyboardInterrupt:
        print("\nBuild cancelled.")
        sys.exit(130)

    except Exception as e:
        print()
        print("=" * 70)
        print("FATAL ERROR")
        print("=" * 70)
        print(str(e))
        sys.exit(1)
