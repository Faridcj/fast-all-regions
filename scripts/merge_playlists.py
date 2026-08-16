#!/usr/bin/env python3

import os
import re
import json
import urllib.request
import urllib.error
from collections import OrderedDict, defaultdict

# ============================================================
# FAST ALL REGIONS BUILDER
#
# Source:
#   BuddyChewChew repositories
#
# Logic:
#   1. Read repository list from GitHub API
#   2. Read the repository tree directly from GitHub
#   3. Find real .m3u / .m3u8 files
#   4. Fetch the actual playlist content
#   5. Read category/group exactly from the M3U
#   6. Output group as:
#         REPOSITORY | ORIGINAL_GROUP
#   7. If original group contains multiple levels:
#         keep only the first level
#   8. Read stream/source information from the M3U itself
#   9. Remove channels whose STREAM URL is duplicated
#  10. Do NOT guess source, region, category or channel data
# ============================================================

OWNER = "BuddyChewChew"

OUTPUT_FILE = "fast-all-regions.m3u"

API = "https://api.github.com"

HEADERS = {
    "User-Agent": "fast-all-regions-builder",
    "Accept": "application/vnd.github+json",
}

PLAYLIST_EXTENSIONS = (".m3u", ".m3u8")


# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------

def fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def fetch_json(url):
    return json.loads(fetch(url).decode("utf-8"))


def fetch_text(url):
    data = fetch(url)

    # Most M3U files are UTF-8, but some contain BOM or
    # non-UTF8 characters.
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


# ------------------------------------------------------------
# GitHub
# ------------------------------------------------------------

def get_repositories():
    """
    Read ALL public repositories owned by BuddyChewChew.

    No hard-coded repository list.
    No guessed repositories.
    """

    repositories = []
    page = 1

    while True:
        url = (
            f"{API}/users/{OWNER}/repos"
            f"?per_page=100&page={page}&type=all"
        )

        data = fetch_json(url)

        if not data:
            break

        for repo in data:
            if not repo.get("archived", False):
                repositories.append(repo["name"])

        if len(data) < 100:
            break

        page += 1

    return sorted(repositories, key=str.lower)


def get_repository_tree(repo):
    """
    Read the actual Git tree from GitHub.

    This is important:
    We don't construct playlist URLs ourselves.
    We first ask GitHub what files actually exist.
    """

    repo_info = fetch_json(
        f"{API}/repos/{OWNER}/{repo}"
    )

    default_branch = repo_info["default_branch"]

    branch = fetch_json(
        f"{API}/repos/{OWNER}/{repo}/branches/{default_branch}"
    )

    tree_sha = branch["commit"]["commit"]["tree"]["sha"]

    tree = fetch_json(
        f"{API}/repos/{OWNER}/{repo}/git/trees/{tree_sha}?recursive=1"
    )

    return tree.get("tree", [])


def get_playlist_files(repo):
    tree = get_repository_tree(repo)

    files = []

    for item in tree:
        if item.get("type") != "blob":
            continue

        path = item.get("path", "")

        if path.lower().endswith(PLAYLIST_EXTENSIONS):
            files.append(path)

    return sorted(files, key=str.lower)


# ------------------------------------------------------------
# M3U parsing
# ------------------------------------------------------------

def parse_attribute(text, attribute):
    """
    Parse:
        attribute="value"

    without assuming a fixed attribute order.
    """

    pattern = rf'{re.escape(attribute)}="([^"]*)"'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        return match.group(1).strip()

    return ""


def clean_group(group):
    """
    Keep the first group only.

    Examples:

        News;USA
            -> News

        Sports|USA
            -> Sports

        Entertainment / Movies
            -> Entertainment

    We do NOT invent a group when none exists.
    """

    if not group:
        return ""

    group = group.strip()

    # Common M3U hierarchy separators.
    for separator in (";", "|"):
        if separator in group:
            group = group.split(separator, 1)[0].strip()

    return group


def parse_extinf(line):
    """
    Parse one #EXTINF line.
    """

    attributes = {
        "group-title": parse_attribute(line, "group-title"),
        "tvg-id": parse_attribute(line, "tvg-id"),
        "tvg-name": parse_attribute(line, "tvg-name"),
        "tvg-logo": parse_attribute(line, "tvg-logo"),
        "tvg-country": parse_attribute(line, "tvg-country"),
        "tvg-language": parse_attribute(line, "tvg-language"),
    }

    # Channel title is the text after the last comma.
    if "," in line:
        name = line.split(",", 1)[1].strip()
    else:
        name = ""

    return attributes, name


def parse_playlist(text):
    """
    Return:

        [
            {
                "extinf": "...",
                "url": "...",
                "attributes": {...},
                "name": "..."
            }
        ]
    """

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    entries = []

    current_extinf = None

    for line in lines:

        if line.startswith("#EXTINF:"):
            current_extinf = line
            continue

        if line.startswith("#"):
            continue

        if current_extinf is None:
            continue

        url = line.strip()

        if not url:
            continue

        attributes, name = parse_extinf(current_extinf)

        entries.append({
            "extinf": current_extinf,
            "url": url,
            "attributes": attributes,
            "name": name,
        })

        current_extinf = None

    return entries


# ------------------------------------------------------------
# Output formatting
# ------------------------------------------------------------

def rebuild_extinf(repository, entry):
    """
    Build the output EXTINF.

    Repository is explicitly added as the first category.

    Final group:

        REPOSITORY | ORIGINAL_GROUP

    If the original playlist has no group, we keep it as:

        REPOSITORY

    No region/source is guessed.
    """

    attrs = entry["attributes"]
    name = entry["name"]

    original_group = clean_group(
        attrs.get("group-title", "")
    )

    if original_group:
        final_group = f"{repository} | {original_group}"
    else:
        final_group = repository

    # Preserve useful metadata from the ORIGINAL M3U.
    parts = ["#EXTINF:-1"]

    if attrs.get("tvg-id"):
        parts.append(f'tvg-id="{attrs["tvg-id"]}"')

    if attrs.get("tvg-name"):
        parts.append(f'tvg-name="{attrs["tvg-name"]}"')

    if attrs.get("tvg-logo"):
        parts.append(f'tvg-logo="{attrs["tvg-logo"]}"')

    if attrs.get("tvg-country"):
        parts.append(f'tvg-country="{attrs["tvg-country"]}"')

    if attrs.get("tvg-language"):
        parts.append(f'tvg-language="{attrs["tvg-language"]}"')

    parts.append(f'group-title="{final_group}"')

    return " ".join(parts) + "," + name


# ------------------------------------------------------------
# Main builder
# ------------------------------------------------------------

def main():

    print("=" * 70)
    print("FAST ALL REGIONS BUILDER")
    print("=" * 70)
    print("Source: BuddyChewChew")
    print("Playlist discovery: GitHub repository tree")
    print("Category source: ORIGINAL M3U")
    print("Region guessing: DISABLED")
    print("Source guessing: DISABLED")
    print("Channel-name guessing: DISABLED")
    print("Duplicate detection: STREAM URL")
    print()

    repositories = get_repositories()

    print(f"Repositories discovered: {len(repositories)}")
    print()

    all_entries = []

    source_summary = OrderedDict()

    for repo in repositories:

        print(f"=== {repo} ===")

        try:
            playlist_files = get_playlist_files(repo)

        except Exception as exc:
            print(f"  [ERROR] Cannot read repository tree: {exc}")
            print()
            continue

        print(f"Found {len(playlist_files)} playlist files")

        successful_files = 0
        repo_entries = 0

        for path in playlist_files:

            # Raw GitHub content URL.
            url = (
                f"https://raw.githubusercontent.com/"
                f"{OWNER}/{repo}/"
                f"HEAD/{urllib.parse.quote(path, safe='/')}"
            )

            try:
                text = fetch_text(url)

            except urllib.error.HTTPError as exc:
                print(
                    f"  [SKIP] {path}: "
                    f"HTTP Error {exc.code}: {exc.reason}"
                )
                continue

            except Exception as exc:
                print(f"  [SKIP] {path}: {exc}")
                continue

            entries = parse_playlist(text)

            if not entries:
                print(f"  [EMPTY] {path}")
                continue

            successful_files += 1
            repo_entries += len(entries)

            print(
                f"  [OK] {path}: "
                f"{len(entries)} entries"
            )

            for entry in entries:
                entry["repository"] = repo
                entry["playlist_file"] = path

                all_entries.append(entry)

        source_summary[repo] = {
            "files": len(playlist_files),
            "successful": successful_files,
            "entries": repo_entries,
        }

        print()

    # --------------------------------------------------------
    # Remove duplicate STREAM URLs.
    #
    # IMPORTANT:
    # We do NOT compare channel names.
    # We do NOT compare groups.
    # We do NOT compare guessed sources.
    #
    # The stream URL itself is the identity.
    # --------------------------------------------------------

    print("Removing duplicate stream URLs...")

    unique_entries = []
    seen_urls = set()

    duplicate_count = 0

    for entry in all_entries:

        stream_url = entry["url"].strip()

        if not stream_url:
            continue

        if stream_url in seen_urls:
            duplicate_count += 1
            continue

        seen_urls.add(stream_url)
        unique_entries.append(entry)

    # --------------------------------------------------------
    # Write output
    # --------------------------------------------------------

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as output:

        output.write(
            "#EXTM3U "
            'x-tvg-url="" '
            'url-tvg=""\n'
        )

        for entry in unique_entries:

            output.write(
                rebuild_extinf(
                    entry["repository"],
                    entry,
                )
                + "\n"
            )

            output.write(
                entry["url"]
                + "\n"
            )

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    categories = OrderedDict()

    for entry in unique_entries:

        group = clean_group(
            entry["attributes"].get(
                "group-title",
                ""
            )
        )

        if group:
            category = (
                f'{entry["repository"]} | {group}'
            )
        else:
            category = entry["repository"]

        categories[category] = (
            categories.get(category, 0) + 1
        )

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
        f"{OUTPUT_FILE}"
    )

    print()
    print("CATEGORY SUMMARY")
    print("-" * 70)

    for category, count in categories.items():
        print(f"{category}: {count}")

    print()
    print("SOURCE SUMMARY")
    print("-" * 70)

    for repo, data in source_summary.items():

        print(
            f"{repo}: "
            f"{data['entries']} entries "
            f"from "
            f"{data['successful']}/"
            f"{data['files']} files"
        )


if __name__ == "__main__":
    main()
