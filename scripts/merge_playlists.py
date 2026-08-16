#!/usr/bin/env python3

import base64
import os
import re
import sys
import time
from collections import Counter, defaultdict
from urllib.parse import urlsplit, urlunsplit

import requests


# ==============================================================
# CONFIG
# ==============================================================

OWNER = "BuddyChewChew"
OUTPUT_FILE = "fast-all-regions.m3u"

API_BASE = "https://api.github.com"

# Optional:
# export GITHUB_TOKEN="ghp_..."
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

REQUEST_TIMEOUT = 30
MAX_RETRIES = 4

PLAYLIST_EXTENSIONS = (".m3u", ".m3u8")


# ==============================================================
# HTTP SESSION
# ==============================================================

session = requests.Session()

session.headers.update({
    "Accept": "application/vnd.github+json",
    "User-Agent": "FAST-All-Regions-Builder/1.0",
    "X-GitHub-Api-Version": "2022-11-28",
})

if GITHUB_TOKEN:
    session.headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"


# ==============================================================
# GITHUB API
# ==============================================================

def github_get(url, params=None):
    """
    Read data directly from GitHub API.

    No raw URL construction.
    No guessed paths.
    """

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                return response

            # Rate limit
            if response.status_code == 403:
                remaining = response.headers.get("X-RateLimit-Remaining")
                reset = response.headers.get("X-RateLimit-Reset")

                if remaining == "0":
                    if reset:
                        wait = max(1, int(reset) - int(time.time()) + 1)
                        raise RuntimeError(
                            f"GitHub API rate limit reached. "
                            f"Reset in approximately {wait} seconds."
                        )

            # Temporary errors
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = RuntimeError(
                    f"GitHub HTTP {response.status_code}: {response.text[:300]}"
                )
                time.sleep(2 ** attempt)
                continue

            raise RuntimeError(
                f"GitHub HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2 ** attempt)

    raise RuntimeError(str(last_error))


# ==============================================================
# DISCOVER ALL REPOSITORIES
# ==============================================================

def discover_repositories():
    """
    Get the actual public repositories belonging to OWNER.

    Repository names are NEVER hard-coded.
    """

    repositories = []

    page = 1

    while True:
        response = github_get(
            f"{API_BASE}/users/{OWNER}/repos",
            params={
                "per_page": 100,
                "page": page,
                "type": "all",
                "sort": "updated",
                "direction": "desc",
            },
        )

        data = response.json()

        if not data:
            break

        for repo in data:
            if repo.get("fork"):
                # Skip forks.
                continue

            repositories.append({
                "name": repo["name"],
                "full_name": repo["full_name"],
                "default_branch": repo["default_branch"],
            })

        page += 1

    repositories.sort(key=lambda x: x["name"].lower())

    return repositories


# ==============================================================
# GET REAL REPOSITORY TREE
# ==============================================================

def get_repository_tree(repo):
    """
    Get the real Git tree from GitHub.

    This is important:
    we do NOT invent paths such as:
        raw.githubusercontent.com/.../playlists/foo.m3u

    GitHub itself tells us which files actually exist.
    """

    full_name = repo["full_name"]
    branch = repo["default_branch"]

    response = github_get(
        f"{API_BASE}/repos/{full_name}/git/trees/{branch}",
        params={
            "recursive": "1",
        },
    )

    data = response.json()

    if data.get("truncated"):
        raise RuntimeError(
            f"Git tree is truncated for {full_name}"
        )

    return data.get("tree", [])


# ==============================================================
# FIND ACTUAL PLAYLIST FILES
# ==============================================================

def find_playlist_files(tree):
    """
    Return only actual files ending in .m3u / .m3u8.

    Directories are ignored.
    """

    files = []

    for item in tree:
        if item.get("type") != "blob":
            continue

        path = item.get("path", "")

        if path.lower().endswith(PLAYLIST_EXTENSIONS):
            files.append({
                "path": path,
                "sha": item["sha"],
                "size": item.get("size", 0),
            })

    files.sort(key=lambda x: x["path"].lower())

    return files


# ==============================================================
# READ ACTUAL FILE FROM GITHUB BLOB
# ==============================================================

def read_blob(repo_full_name, sha):
    """
    Fetch the actual blob referenced by GitHub.

    Again: no guessed raw URL.
    """

    response = github_get(
        f"{API_BASE}/repos/{repo_full_name}/git/blobs/{sha}"
    )

    data = response.json()

    content = data.get("content", "")
    encoding = data.get("encoding")

    if encoding != "base64":
        raise RuntimeError(
            f"Unexpected blob encoding: {encoding}"
        )

    raw = base64.b64decode(
        content.replace("\n", "")
    )

    return raw.decode("utf-8-sig", errors="replace")


# ==============================================================
# PLAYLIST NAME
# ==============================================================

def playlist_name_from_path(path):
    """
    Example:

        playlists/plex_us.m3u
        -> plex_us

    The first category component is based on the actual M3U
    filename, not on a guessed service.
    """

    filename = os.path.basename(path)

    name = re.sub(
        r"\.(m3u8?|M3U8?)$",
        "",
        filename,
    )

    return name.strip()


# ==============================================================
# SERVICE NAME
# ==============================================================

def service_name_from_playlist(path):
    """
    First part of the output category.

    Examples:

        plex_us       -> plex
        plex_all      -> plex
        plutotv_us    -> plutotv
        samsungtvplus -> samsungtvplus
        roku           -> roku

    We derive this ONLY from the real playlist filename.
    """

    playlist_name = playlist_name_from_path(path)

    # Split only the filename's regional suffix.
    #
    # plex_us       -> plex
    # plex_all      -> plex
    # pluto_de      -> pluto
    #
    # But don't destroy names such as:
    # samsungtvplus
    # localnow
    # buddylive
    #

    parts = playlist_name.split("_")

    if len(parts) >= 2:
        return parts[0].strip()

    return playlist_name.strip()


# ==============================================================
# GROUP EXTRACTION
# ==============================================================

def extract_attribute(extinf, attribute):
    """
    Extract:

        group-title="Something"

    without guessing the value.
    """

    pattern = (
        rf'{re.escape(attribute)}\s*=\s*'
        r'"([^"]*)"'
    )

    match = re.search(
        pattern,
        extinf,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1).strip()

    return ""


def first_group_component(group):
    """
    If the original M3U has something like:

        Movies | USA | FAST

    only:

        Movies

    is kept.

    We do NOT invent a group when group-title is absent.
    """

    if not group:
        return ""

    # Common hierarchical separators.
    separators = [
        "|",
        "»",
        "›",
        "->",
        " / ",
        "\\",
    ]

    result = group.strip()

    for separator in separators:
        if separator in result:
            result = result.split(separator, 1)[0].strip()

    return result


# ==============================================================
# M3U PARSER
# ==============================================================

def parse_m3u(text):
    """
    Parse M3U into:

        {
            extinf: "...",
            url: "..."
        }

    We preserve the original EXTINF metadata.
    """

    lines = [
        line.strip()
        for line in text.splitlines()
    ]

    entries = []

    current_extinf = None

    for line in lines:

        if not line:
            continue

        if line.startswith("#EXTINF"):
            current_extinf = line
            continue

        if line.startswith("#"):
            continue

        if current_extinf is None:
            continue

        url = line.strip()

        if not url:
            continue

        entries.append({
            "extinf": current_extinf,
            "url": url,
        })

        current_extinf = None

    return entries


# ==============================================================
# URL NORMALIZATION
# ==============================================================

def normalize_stream_url(url):
    """
    Normalize only superficial URL differences.

    The stream identity remains the URL.

    We intentionally DO NOT:
        - resolve domains
        - follow redirects
        - test stream health
        - guess providers
        - guess regions
        - rename URLs
    """

    url = url.strip()

    if not url:
        return ""

    # Remove accidental surrounding quotes.
    url = url.strip('"').strip("'")

    # Remove URL fragment only.
    #
    # Query parameters are preserved because they may be
    # authentication/session parameters and therefore may
    # identify a different stream.
    try:
        parts = urlsplit(url)

        url = urlunsplit((
            parts.scheme,
            parts.netloc,
            parts.path,
            parts.query,
            "",
        ))

    except Exception:
        pass

    return url


# ==============================================================
# GROUP NAME
# ==============================================================

def build_group_name(playlist_path, extinf):
    """
    Required output format:

        M3U-NAME | ORIGINAL-FIRST-GROUP

    Example:

        plex | News
        plex | Entertainment
        pluto | Movies

    If the original entry has no group-title:

        plex | Ungrouped

    No region/source is guessed.
    """

    service = service_name_from_playlist(
        playlist_path
    )

    original_group = extract_attribute(
        extinf,
        "group-title",
    )

    group = first_group_component(
        original_group
    )

    if not group:
        group = "Ungrouped"

    return f"{service} | {group}"


# ==============================================================
# REWRITE EXTINF
# ==============================================================

def rewrite_extinf(extinf, group_name):
    """
    Replace group-title with our required category.

    All other EXTINF attributes are preserved.
    """

    if re.search(
        r'group-title\s*=\s*"[^"]*"',
        extinf,
        flags=re.IGNORECASE,
    ):
        return re.sub(
            r'group-title\s*=\s*"[^"]*"',
            f'group-title="{group_name}"',
            extinf,
            flags=re.IGNORECASE,
        )

    # No group-title existed.
    #
    # Insert it immediately after #EXTINF:-1
    # while keeping the original channel metadata.
    #
    # Example:
    # #EXTINF:-1 tvg-id="..." ...
    #
    # becomes:
    # #EXTINF:-1 group-title="..." tvg-id="..." ...

    return re.sub(
        r'^#EXTINF:-1',
        f'#EXTINF:-1 group-title="{group_name}"',
        extinf,
        count=1,
    )


# ==============================================================
# BUILD
# ==============================================================

def build():
    print()
    print("=" * 70)
    print("FAST ALL REGIONS BUILDER")
    print("=" * 70)
    print(f"Owner: {OWNER}")
    print(
        "GitHub authentication:",
        "ENABLED" if GITHUB_TOKEN else "DISABLED",
    )
    print()

    repositories = discover_repositories()

    print(
        f"Repositories discovered: {len(repositories)}"
    )
    print()

    all_entries = []

    source_stats = defaultdict(
        lambda: {
            "playlists": 0,
            "successful": 0,
            "entries": 0,
        }
    )

    failed_playlists = []

    for repo in repositories:

        repo_name = repo["name"]

        print("=" * 70)
        print(f"=== {repo_name} ===")
        print("=" * 70)

        try:
            tree = get_repository_tree(repo)

        except Exception as exc:
            print(
                f"  [ERROR] Could not read repository tree: {exc}"
            )
            continue

        playlist_files = find_playlist_files(tree)

        source_stats[repo_name]["playlists"] = len(
            playlist_files
        )

        print(
            f"Found {len(playlist_files)} playlist files"
        )

        for playlist in playlist_files:

            path = playlist["path"]

            try:
                text = read_blob(
                    repo["full_name"],
                    playlist["sha"],
                )

                entries = parse_m3u(text)

                source_stats[repo_name]["successful"] += 1
                source_stats[repo_name]["entries"] += len(
                    entries
                )

                print(
                    f"  [OK] {path}: "
                    f"{len(entries)} entries"
                )

                for entry in entries:

                    url = normalize_stream_url(
                        entry["url"]
                    )

                    if not url:
                        continue

                    group_name = build_group_name(
                        path,
                        entry["extinf"],
                    )

                    new_extinf = rewrite_extinf(
                        entry["extinf"],
                        group_name,
                    )

                    all_entries.append({
                        "repo": repo_name,
                        "playlist": path,
                        "group": group_name,
                        "extinf": new_extinf,
                        "url": url,
                    })

            except Exception as exc:

                failed_playlists.append({
                    "repo": repo_name,
                    "path": path,
                    "error": str(exc),
                })

                print(
                    f"  [SKIP] {path}: {exc}"
                )

        print()

    # ==========================================================
    # REMOVE DUPLICATE STREAM URLS
    # ==========================================================

    print()
    print("Removing duplicate stream URLs...")
    print()

    unique_entries = []
    seen_urls = set()

    duplicate_count = 0

    for entry in all_entries:

        url = entry["url"]

        if url in seen_urls:
            duplicate_count += 1
            continue

        seen_urls.add(url)
        unique_entries.append(entry)

    # ==========================================================
    # SORT
    # ==========================================================

    unique_entries.sort(
        key=lambda x: (
            x["group"].lower(),
            x["extinf"].lower(),
            x["url"].lower(),
        )
    )

    # ==========================================================
    # WRITE OUTPUT
    # ==========================================================

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as output:

        output.write("#EXTM3U\n")

        current_group = None

        for entry in unique_entries:

            group = entry["group"]

            # Optional group marker.
            # This does not replace group-title.
            if group != current_group:
                output.write(
                    f"\n"
                    f"# === {group} ===\n"
                )

                current_group = group

            output.write(
                entry["extinf"] + "\n"
            )

            output.write(
                entry["url"] + "\n"
            )

    # ==========================================================
    # SUMMARY
    # ==========================================================

    categories = Counter(
        entry["group"]
        for entry in unique_entries
    )

    print()
    print("=" * 70)
    print("BUILD COMPLETE")
    print("=" * 70)

    print(
        f"Repositories discovered: {len(repositories)}"
    )

    print(
        f"Playlist entries read: {len(all_entries)}"
    )

    print(
        f"Unique stream URLs: {len(unique_entries)}"
    )

    print(
        f"Duplicate URLs removed: {duplicate_count}"
    )

    print(
        f"Categories: {len(categories)}"
    )

    print(
        f"Output: {OUTPUT_FILE}"
    )

    print()
    print("CATEGORY SUMMARY")
    print("-" * 70)

    for group, count in sorted(
        categories.items(),
        key=lambda x: x[0].lower(),
    ):
        print(
            f"{group}: {count}"
        )

    print()
    print("SOURCE SUMMARY")
    print("-" * 70)

    for repo_name in sorted(
        source_stats,
        key=str.lower,
    ):

        stats = source_stats[repo_name]

        print(
            f"{repo_name}: "
            f"{stats['entries']} entries "
            f"from "
            f"{stats['successful']}/"
            f"{stats['playlists']} files"
        )

    if failed_playlists:

        print()
        print(
            f"FAILED PLAYLISTS: "
            f"{len(failed_playlists)}"
        )

        for failed in failed_playlists:
            print(
                f"  {failed['repo']}/{failed['path']}"
            )
            print(
                f"    {failed['error']}"
            )

    print()
    print("=" * 70)


# ==============================================================
# MAIN
# ==============================================================

if __name__ == "__main__":
    try:
        build()

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)

    except Exception as exc:
        print()
        print("BUILD FAILED")
        print("-" * 70)
        print(str(exc))
        sys.exit(1)
