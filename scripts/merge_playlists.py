import json
import os
import re
import urllib.request
from urllib.parse import quote
from pathlib import PurePosixPath
from collections import defaultdict


# ============================================================
# CONFIG
# ============================================================

OWNER = "BuddyChewChew"
OUTPUT = "fast-all-regions.m3u"

REQUEST_TIMEOUT = 90

PLAYLIST_EXTENSIONS = (
    ".m3u",
    ".m3u8",
)

IGNORE_DIRS = {
    ".git",
    ".github",
    "docs",
    "documentation",
    "test",
    "tests",
    "example",
    "examples",
    "epg",
    "logos",
    "logo",
    "images",
    "archive",
    "backup",
}


# ============================================================
# GITHUB TOKEN
# ============================================================

GITHUB_TOKEN = os.environ.get(
    "GH_TOKEN",
    ""
).strip()

API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "FAST-All-Regions-Builder",
}

if GITHUB_TOKEN:
    API_HEADERS["Authorization"] = (
        f"Bearer {GITHUB_TOKEN}"
    )

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 FAST-All-Regions-Builder"
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

        except Exception as error:

            print(
                f"[ERROR] GitHub repositories: {error}"
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
                    "branch": (
                        repo.get("default_branch")
                        or "main"
                    ),
                }
            )

        if len(data) < 100:
            break

        page += 1

    return repositories


# ============================================================
# REPOSITORY TREE
# ============================================================

def get_repository_tree(repo, branch):

    url = (
        f"https://api.github.com/repos/"
        f"{OWNER}/{quote(repo, safe='')}"
        f"/git/trees/"
        f"{quote(branch, safe='')}"
        f"?recursive=1"
    )

    try:

        data = github_json(url)

    except Exception as error:

        print(
            f"[WARNING] Cannot read tree "
            f"{repo}: {error}"
        )

        return []

    if data.get("truncated"):

        print(
            f"[WARNING] Tree truncated: {repo}"
        )

    return data.get(
        "tree",
        []
    )


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
        part.lower()
        for part in PurePosixPath(path).parts
    }

    if parts.intersection(
        IGNORE_DIRS
    ):
        return False

    return True


def discover_playlists(repo, branch):

    tree = get_repository_tree(
        repo,
        branch
    )

    playlists = []

    for item in tree:

        if item.get("type") != "blob":
            continue

        path = item.get(
            "path",
            ""
        )

        if is_playlist(path):

            playlists.append(path)

    return sorted(
        playlists
    )


# ============================================================
# M3U FETCH
# ============================================================

def get_raw_url(repo, branch, path):

    return (
        "https://raw.githubusercontent.com/"
        f"{OWNER}/"
        f"{quote(repo, safe='')}/"
        f"{quote(path, safe='/')}"
        f"?ref={quote(branch, safe='')}"
    )


def fetch_playlist(repo, branch, path):

    url = get_raw_url(
        repo,
        branch,
        path
    )

    try:

        return fetch_text(
            url,
            HTTP_HEADERS
        )

    except Exception as error:

        print(
            f"  [SKIP] {path}: {error}"
        )

        return None


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
            and (
                line.startswith("http://")
                or line.startswith("https://")
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


# ============================================================
# EXTINF ATTRIBUTES
# ============================================================

def get_attribute(extinf, attribute):

    match = re.search(
        rf'{re.escape(attribute)}="([^"]*)"',
        extinf,
        re.IGNORECASE
    )

    if match:

        return match.group(1).strip()

    return ""


def get_channel_name(extinf):

    if "," not in extinf:

        return ""

    return (
        extinf
        .split(",", 1)[1]
        .strip()
    )


# ============================================================
# PLAYLIST NAME
#
# IMPORTANT:
# The category source is the actual playlist filename.
# No service/country guessing.
# ============================================================

def playlist_name(path):

    return PurePosixPath(
        path
    ).stem


# ============================================================
# GROUP NAME
#
# We take ONLY the first level of group-title.
#
# Examples:
#
# News
# News | US
# News / Local
# News > Local
# News > Local > City
#
# all become:
#
# News
# ============================================================

def first_group_level(group):

    if not group:

        return "Uncategorized"

    group = group.strip()

    if not group:

        return "Uncategorized"

    parts = re.split(
        r"\s*(?:\||>|/|\\|;)\s*",
        group
    )

    first = parts[0].strip()

    if not first:

        return "Uncategorized"

    return first


# ============================================================
# CATEGORY
# ============================================================

def build_category(
    playlist,
    group
):

    return (
        f"{playlist} | "
        f"{first_group_level(group)}"
    )


# ============================================================
# GROUP TITLE REPLACEMENT
# ============================================================

def set_group_title(
    extinf,
    category
):

    escaped = (
        category
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
            f'group-title="{escaped}"',
            extinf,
            flags=re.IGNORECASE
        )

    comma = extinf.find(",")

    if comma == -1:

        return extinf

    return (
        extinf[:comma]
        + f' group-title="{escaped}"'
        + extinf[comma:]
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("FAST ALL REGIONS BUILDER")
    print("=" * 70)

    if GITHUB_TOKEN:

        print(
            "GitHub API authentication: ENABLED"
        )

    else:

        print(
            "GitHub API authentication: DISABLED"
        )

    print()

    repositories = (
        get_all_repositories()
    )

    print(
        f"Repositories discovered: "
        f"{len(repositories)}"
    )

    print()

    all_entries = []

    failed_playlists = []

    repository_stats = defaultdict(
        lambda: {
            "files": 0,
            "loaded": 0,
            "channels": 0,
        }
    )

    # ========================================================
    # READ EVERY PLAYLIST
    # ========================================================

    for repo_info in repositories:

        repo = repo_info["name"]
        branch = repo_info["branch"]

        print(
            f"=== {repo} ==="
        )

        playlist_paths = (
            discover_playlists(
                repo,
                branch
            )
        )

        print(
            f"Found "
            f"{len(playlist_paths)} "
            f"playlist files"
        )

        for path in playlist_paths:

            repository_stats[
                repo
            ]["files"] += 1

            text = fetch_playlist(
                repo,
                branch,
                path
            )

            if text is None:

                failed_playlists.append(
                    (
                        repo,
                        path
                    )
                )

                continue

            entries = parse_m3u(
                text
            )

            repository_stats[
                repo
            ]["loaded"] += 1

            repository_stats[
                repo
            ]["channels"] += len(
                entries
            )

            print(
                f"  {path}: "
                f"{len(entries)} channels"
            )

            # ------------------------------------------------
            # IMPORTANT
            #
            # Playlist filename is the first category level.
            #
            # group-title from the actual M3U is the second.
            # ------------------------------------------------

            p_name = playlist_name(
                path
            )

            for extinf, stream_url in entries:

                stream_url = (
                    stream_url.strip()
                )

                if not stream_url:

                    continue

                channel_name = (
                    get_channel_name(
                        extinf
                    )
                )

                if not channel_name:

                    continue

                original_group = (
                    get_attribute(
                        extinf,
                        "group-title"
                    )
                )

                category = (
                    build_category(
                        p_name,
                        original_group
                    )
                )

                new_extinf = (
                    set_group_title(
                        extinf,
                        category
                    )
                )

                all_entries.append(
                    {
                        "extinf": new_extinf,
                        "url": stream_url,
                        "repo": repo,
                        "playlist": p_name,
                        "group": first_group_level(
                            original_group
                        ),
                    }
                )

        print()

    # ========================================================
    # EXACT URL DEDUPLICATION
    #
    # ONLY stream URL is used.
    #
    # Same URL = duplicate.
    # Same channel name with different URL = KEEP.
    # ========================================================

    print(
        "Removing duplicate stream URLs..."
    )

    unique_entries = []

    seen_urls = set()

    duplicate_count = 0

    for entry in all_entries:

        url_key = (
            entry["url"]
            .strip()
        )

        if url_key in seen_urls:

            duplicate_count += 1

            continue

        seen_urls.add(
            url_key
        )

        unique_entries.append(
            entry
        )

    # ========================================================
    # SORT
    # ========================================================

    unique_entries.sort(
        key=lambda item: (
            item["playlist"].lower(),
            item["group"].lower(),
            item["extinf"].lower(),
        )
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
            f"{entry['playlist']} | "
            f"{entry['group']}"
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
        f"{len(categories)}"
    )

    print(
        f"Output: "
        f"{OUTPUT}"
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
            f"{category}: "
            f"{count}"
        )

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
            f"{stats['channels']} entries "
            f"from "
            f"{stats['loaded']}/"
            f"{stats['files']} files"
        )

    # ========================================================
    # FAILED FILES
    # ========================================================

    if failed_playlists:

        print()

        print(
            f"FAILED PLAYLISTS: "
            f"{len(failed_playlists)}"
        )

        for repo, path in failed_playlists:

            print(
                f"  {repo}/{path}"
            )

    print()
    print(
        "Done."
    )


if __name__ == "__main__":
    main()
