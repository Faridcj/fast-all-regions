import os
import re
import sys
import time
import json
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter, defaultdict
#!/usr/bin/env python3

import os
import re
import sys
import time
import json
import urllib.request
import urllib.error
from collections import Counter, defaultdict


# ============================================================
# CONFIG
# ============================================================

OWNER = "BuddyChewChew"

OUTPUT_FILE = "fast-all-regions.m3u"

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

PLAYLIST_EXTENSIONS = (
    ".m3u",
    ".m3u8",
)

REQUEST_TIMEOUT = 30

# Only these repositories get their original group-title
# collapsed into one single category.
SOURCE_CATEGORY_OVERRIDES = {
    "app-m3u-generator": "App M3U",
}


# ============================================================
# SOURCE NAME NORMALIZATION
# ============================================================

SOURCE_NAMES = {
    "airy-playlist-generator": "Airy",
    "app-m3u-generator": "App M3U",
    "buddylive": "Buddy Live",
    "buddylive-combined": "Buddy Live",
    "buddylive_v2": "Buddy Live",
    "distro-playlist-generator": "DistroTV",
    "lg-playlist-generator": "LG",
    "lg-playlist-generator2": "LG",
    "my-streams": "My-Streams",
    "nz": "NZ",
    "plex": "Plex",
    "plex-alt-fast-channels": "Plex Alt",
    "pluto": "Pluto TV",
    "rakutentv": "Rakuten TV",
    "roku-playlist-generator": "Roku",
    "samsungtvplus": "Samsung TV Plus",
    "sports": "Sports",
    "tcl-playlist-generator": "TCL",
    "tubi-scraper": "Tubi",
    "vod": "VOD",
    "whiplash-epg": "Whiplash",
    "xumo-playlist-generator": "Xumo",
    "dlxes": "dlxes",
    "oly": "oly",
}


def normalize_source_name(repo):
    key = repo.strip().lower()

    if key in SOURCE_NAMES:
        return SOURCE_NAMES[key]

    # Generic cleanup for newly discovered repositories.
    name = repo.replace("_", " ").replace("-", " ").strip()

    replacements = {
        "playlist generator": "",
        "playlist-generator": "",
        "scraper": "",
    }

    lowered = name.lower()

    for old, new in replacements.items():
        lowered = lowered.replace(old, new)

    lowered = re.sub(r"\s+", " ", lowered).strip()

    if not lowered:
        lowered = name

    return lowered.title()


# ============================================================
# HTTP
# ============================================================

def github_request(url, accept="application/vnd.github+json"):
    headers = {
        "User-Agent": "FAST-All-Regions-Builder/1.0",
        "Accept": accept,
    }

    token = os.environ.get("GITHUB_TOKEN")

    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        return response.read()


def get_json(url):
    return json.loads(github_request(url).decode("utf-8"))


def get_text(url):
    headers = {
        "User-Agent": "FAST-All-Regions-Builder/1.0",
    }

    req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        raw = response.read()

    # M3U files are normally UTF-8, but some repositories contain
    # BOMs or slightly different encodings.
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass

    return raw.decode("utf-8", errors="replace")


# ============================================================
# GITHUB REPOSITORY DISCOVERY
# ============================================================

def discover_repositories():
    print("Discovering repositories...")

    repos = []
    page = 1

    while True:
        url = (
            f"{GITHUB_API}/users/{OWNER}/repos"
            f"?per_page=100&page={page}&type=public"
        )

        try:
            data = get_json(url)
        except Exception as exc:
            print(f"[ERROR] Cannot discover repositories: {exc}")
            break

        if not data:
            break

        for repo in data:
            if not repo.get("fork", False):
                repos.append(repo["name"])

        if len(data) < 100:
            break

        page += 1

    return sorted(set(repos), key=str.lower)


# ============================================================
# TREE DISCOVERY
# ============================================================

def discover_playlist_files(repo):
    """
    Primary method:
        Git Trees API

    Fallback:
        GitHub contents API

    Returns repository-relative paths.
    """

    tree_url = (
        f"{GITHUB_API}/repos/{OWNER}/{repo}/git/trees/main"
        f"?recursive=1"
    )

    try:
        data = get_json(tree_url)

        if isinstance(data, dict) and "tree" in data:
            paths = []

            for item in data["tree"]:
                if item.get("type") != "blob":
                    continue

                path = item.get("path", "")

                if path.lower().endswith(PLAYLIST_EXTENSIONS):
                    paths.append(path)

            return sorted(paths)

    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            pass
    except Exception:
        pass

    # Try master branch.
    tree_url = (
        f"{GITHUB_API}/repos/{OWNER}/{repo}/git/trees/master"
        f"?recursive=1"
    )

    try:
        data = get_json(tree_url)

        if isinstance(data, dict) and "tree" in data:
            paths = []

            for item in data["tree"]:
                if item.get("type") != "blob":
                    continue

                path = item.get("path", "")

                if path.lower().endswith(PLAYLIST_EXTENSIONS):
                    paths.append(path)

            return sorted(paths)

    except Exception:
        pass

    # Contents API fallback.
    return discover_playlist_files_contents(repo)


def discover_playlist_files_contents(repo, path=""):
    """
    Recursive GitHub Contents API fallback.
    """

    url = f"{GITHUB_API}/repos/{OWNER}/{repo}/contents/{path}"

    try:
        data = get_json(url)
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    results = []

    for item in data:
        item_type = item.get("type")
        item_path = item.get("path", "")

        if item_type == "file":
            if item_path.lower().endswith(PLAYLIST_EXTENSIONS):
                results.append(item_path)

        elif item_type == "dir":
            results.extend(
                discover_playlist_files_contents(
                    repo,
                    item_path,
                )
            )

    return results


# ============================================================
# RAW FILE FETCH
# ============================================================

def fetch_playlist(repo, path):
    """
    Try the repository's default branches.
    """

    branches = ["main", "master"]

    for branch in branches:
        url = (
            f"{GITHUB_RAW}/{OWNER}/{repo}/"
            f"{branch}/{urllib.parse.quote(path, safe='/')}"
        )

        try:
            return get_text(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue

            raise

    raise FileNotFoundError(
        f"Playlist not found: {repo}/{path}"
    )


# ============================================================
# M3U PARSER
# ============================================================

ATTRIBUTE_RE = re.compile(
    r'([A-Za-z0-9_-]+)\s*=\s*"([^"]*)"'
)


def parse_attributes(line):
    """
    Parse standard M3U attributes.

    Example:
        #EXTINF:-1 tvg-id="abc" group-title="News",Channel
    """

    attrs = {}

    for match in ATTRIBUTE_RE.finditer(line):
        key = match.group(1)
        value = match.group(2)
        attrs[key] = value

    return attrs


def extract_channel_name(extinf_line):
    """
    Extract text after the final comma in EXTINF.

    No guessing or modification.
    """

    if "," not in extinf_line:
        return ""

    return extinf_line.split(",", 1)[1].strip()


def normalize_group(group):
    """
    We do NOT invent categories.

    We only normalize whitespace and remove surrounding quotes
    that may have survived malformed source data.
    """

    if group is None:
        return ""

    group = group.strip()

    group = group.strip('"').strip("'").strip()

    group = re.sub(r"\s+", " ", group)

    return group


def first_level_group(group):
    """
    Keep only the first group level.

    Supports common separators such as:
        A > B
        A / B
        A | B

    IMPORTANT:
    This is only structural parsing.
    We do not infer a category.
    """

    if not group:
        return ""

    separators = (
        " > ",
        ">>",
        " / ",
        " | ",
        " :: ",
        " >",
        "> ",
    )

    for sep in separators:
        if sep in group:
            return group.split(sep, 1)[0].strip()

    return group.strip()


def parse_m3u(text):
    """
    Returns a list of:
        {
            "extinf": original EXTINF line,
            "attrs": parsed attributes,
            "name": channel name,
            "url": stream URL
        }
    """

    lines = text.splitlines()

    entries = []

    current_extinf = None
    current_attrs = None

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#EXTINF"):
            current_extinf = line
            current_attrs = parse_attributes(line)
            continue

        if line.startswith("#"):
            continue

        # Anything non-comment following EXTINF is treated
        # as the stream URL.
        if current_extinf is not None:
            url = line

            entries.append({
                "extinf": current_extinf,
                "attrs": current_attrs or {},
                "name": extract_channel_name(current_extinf),
                "url": url,
            })

            current_extinf = None
            current_attrs = None

    return entries


# ============================================================
# OUTPUT EXTINF
# ============================================================

def rebuild_extinf(entry, source_name, repo):
    """
    Preserve original EXTINF metadata but replace group-title
    with the final category.

    App M3U is the one explicit grouping override.
    """

    original = entry["extinf"]

    attrs = entry["attrs"].copy()

    original_name = entry["name"]

    # --------------------------------------------------------
    # Category
    # --------------------------------------------------------

    if repo.lower() in SOURCE_CATEGORY_OVERRIDES:
        category = SOURCE_CATEGORY_OVERRIDES[repo.lower()]
    else:
        original_group = attrs.get("group-title", "")
        category = first_level_group(
            normalize_group(original_group)
        )

        if not category:
            category = "Uncategorized"

        category = f"{source_name} | {category}"

    # --------------------------------------------------------
    # Preserve everything except group-title.
    # --------------------------------------------------------

    # Find EXTINF prefix before first attribute.
    prefix_match = re.match(
        r"^#EXTINF:[^ ]*",
        original
    )

    if prefix_match:
        prefix = prefix_match.group(0)
    else:
        prefix = "#EXTINF:-1"

    # Reconstruct attributes in their original order as much
    # as possible. group-title is replaced.
    rebuilt_attrs = []

    seen_group = False

    for match in ATTRIBUTE_RE.finditer(original):
        key = match.group(1)

        if key == "group-title":
            rebuilt_attrs.append(
                f'group-title="{category}"'
            )
            seen_group = True
        else:
            rebuilt_attrs.append(
                f'{key}="{match.group(2)}"'
            )

    if not seen_group:
        rebuilt_attrs.append(
            f'group-title="{category}"'
        )

    if original_name:
        return (
            prefix
            + " "
            + " ".join(rebuilt_attrs)
            + ","
            + original_name
        )

    return (
        prefix
        + " "
        + " ".join(rebuilt_attrs)
        + ","
    )


# ============================================================
# BUILD
# ============================================================

def main():

    print("=" * 70)
    print("FAST ALL REGIONS BUILDER")
    print("=" * 70)

    print(f"Source: {OWNER}")
    print("Playlist discovery: GitHub repository tree")
    print("Category source: ORIGINAL M3U group-title")
    print("Group depth: FIRST LEVEL ONLY")
    print("App M3U category: COLLAPSED TO ONE GROUP")
    print("Region guessing: DISABLED")
    print("Source guessing: DISABLED")
    print("Channel-name guessing: DISABLED")
    print("Duplicate detection: STREAM URL")
    print()

    token = os.environ.get("GITHUB_TOKEN")

    print(
        "GitHub API authentication: "
        + ("ENABLED" if token else "DISABLED")
    )
    print()

    repositories = discover_repositories()

    print(f"Repositories discovered: {len(repositories)}")
    print()

    # --------------------------------------------------------
    # Global collections
    # --------------------------------------------------------

    all_entries = []

    seen_urls = set()

    category_counter = Counter()

    source_stats = defaultdict(
        lambda: {
            "entries": 0,
            "files_ok": 0,
            "files_total": 0,
        }
    )

    empty_playlists = []
    failed_playlists = []

    # --------------------------------------------------------
    # Process repositories
    # --------------------------------------------------------

    for repo in repositories:

        print(f"=== {repo} ===")

        try:
            playlist_files = discover_playlist_files(repo)
        except Exception as exc:
            print(
                f"  [ERROR] Cannot read repository tree: {exc}"
            )
            print()
            continue

        print(
            f"Found {len(playlist_files)} playlist files"
        )

        source_name = normalize_source_name(repo)

        source_stats[repo]["files_total"] = len(
            playlist_files
        )

        for path in playlist_files:

            try:
                text = fetch_playlist(repo, path)
                entries = parse_m3u(text)

            except Exception as exc:
                print(
                    f"  [SKIP] {path}: {exc}"
                )

                failed_playlists.append(
                    f"{repo}/{path}"
                )

                continue

            if not entries:
                print(
                    f"  [EMPTY] {path}"
                )

                empty_playlists.append(
                    f"{repo}/{path}"
                )

                continue

            print(
                f"  [OK] {path}: {len(entries)} entries"
            )

            source_stats[repo]["files_ok"] += 1

            for entry in entries:

                url = entry["url"].strip()

                if not url:
                    continue

                # ------------------------------------------------
                # Duplicate detection:
                # EXACT STREAM URL
                # ------------------------------------------------

                if url in seen_urls:
                    continue

                seen_urls.add(url)

                # ------------------------------------------------
                # Build final EXTINF
                # ------------------------------------------------

                extinf = rebuild_extinf(
                    entry,
                    source_name,
                    repo,
                )

                # Determine category for reporting.
                if repo.lower() in SOURCE_CATEGORY_OVERRIDES:
                    final_category = SOURCE_CATEGORY_OVERRIDES[
                        repo.lower()
                    ]
                else:
                    original_group = entry["attrs"].get(
                        "group-title",
                        "",
                    )

                    group = first_level_group(
                        normalize_group(
                            original_group
                        )
                    )

                    if not group:
                        group = "Uncategorized"

                    final_category = (
                        f"{source_name} | {group}"
                    )

                category_counter[final_category] += 1

                source_stats[repo]["entries"] += 1

                all_entries.append(
                    (
                        extinf,
                        url,
                        source_name,
                        repo,
                    )
                )

        print()

    # ========================================================
    # WRITE OUTPUT
    # ========================================================

    print("Removing duplicate stream URLs...")
    print()

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as output:

        output.write("#EXTM3U\n")

        for extinf, url, _, _ in all_entries:
            output.write(extinf + "\n")
            output.write(url + "\n")

    # ========================================================
    # SUMMARY
    # ========================================================

    total_read = sum(
        source_stats[r]["entries"]
        for r in source_stats
    )

    unique_count = len(all_entries)

    duplicates_removed = (
        total_read - unique_count
    )

    print("=" * 70)
    print("BUILD COMPLETE")
    print("=" * 70)

    print(
        f"Repositories discovered: {len(repositories)}"
    )

    print(
        f"Playlist entries read: {total_read}"
    )

    print(
        f"Unique stream URLs: {unique_count}"
    )

    print(
        f"Duplicate URLs removed: {duplicates_removed}"
    )

    print(
        f"Categories: {len(category_counter)}"
    )

    print(
        f"Output: {OUTPUT_FILE}"
    )

    print()
    print("CATEGORY SUMMARY")
    print("-" * 70)

    for category, count in sorted(
        category_counter.items(),
        key=lambda x: (x[0].lower(), x[1]),
    ):
        print(
            f"{category}: {count}"
        )

    print()
    print("SOURCE SUMMARY")
    print("-" * 70)

    for repo in repositories:

        stats = source_stats[repo]

        if stats["files_total"] == 0 and stats["entries"] == 0:
            continue

        print(
            f"{repo}: "
            f"{stats['entries']} entries "
            f"from "
            f"{stats['files_ok']}/"
            f"{stats['files_total']} files"
        )

    if empty_playlists:
        print()
        print(
            f"EMPTY PLAYLISTS: {len(empty_playlists)}"
        )

        for item in empty_playlists:
            print(f"  {item}")

    if failed_playlists:
        print()
        print(
            f"FAILED PLAYLISTS: {len(failed_playlists)}"
        )

        for item in failed_playlists:
            print(f"  {item}")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
