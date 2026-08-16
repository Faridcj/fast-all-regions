import json
import re
import urllib.request
from urllib.parse import quote, unquote
from pathlib import PurePosixPath
from collections import defaultdict

OWNER = "BuddyChewChew"
OUTPUT = "fast-all-regions.m3u"

REQUEST_TIMEOUT = 90

API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "FAST-All-Regions-Builder",
}

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
# COUNTRY / REGION MAP
# ============================================================

COUNTRIES = {
    "us": "US",
    "usa": "US",
    "unitedstates": "US",
    "united-states": "US",
    "united_states": "US",
    "america": "US",

    "uk": "UK",
    "gb": "UK",
    "greatbritain": "UK",
    "great-britain": "UK",
    "unitedkingdom": "UK",
    "united-kingdom": "UK",
    "united_kingdom": "UK",
    "england": "UK",

    "ca": "Canada",
    "canada": "Canada",

    "au": "Australia",
    "australia": "Australia",

    "nz": "New Zealand",
    "new-zealand": "New Zealand",
    "new_zealand": "New Zealand",

    "de": "Germany",
    "germany": "Germany",

    "fr": "France",
    "france": "France",

    "es": "Spain",
    "spain": "Spain",

    "it": "Italy",
    "italy": "Italy",

    "br": "Brazil",
    "brazil": "Brazil",

    "mx": "Mexico",
    "mexico": "Mexico",

    "in": "India",
    "india": "India",

    "jp": "Japan",
    "japan": "Japan",

    "kr": "South Korea",
    "korea": "South Korea",
    "south-korea": "South Korea",
    "south_korea": "South Korea",

    "at": "Austria",
    "austria": "Austria",

    "ch": "Switzerland",
    "switzerland": "Switzerland",

    "nl": "Netherlands",
    "netherlands": "Netherlands",

    "se": "Sweden",
    "sweden": "Sweden",

    "no": "Norway",
    "norway": "Norway",

    "dk": "Denmark",
    "denmark": "Denmark",

    "fi": "Finland",
    "finland": "Finland",

    "pl": "Poland",
    "poland": "Poland",

    "tr": "Turkey",
    "turkey": "Turkey",

    "ie": "Ireland",
    "ireland": "Ireland",

    "za": "South Africa",
    "south-africa": "South Africa",
    "south_africa": "South Africa",
    "southafrica": "South Africa",

    "ar": "Argentina",
    "argentina": "Argentina",

    "cl": "Chile",
    "chile": "Chile",

    "co": "Colombia",
    "colombia": "Colombia",

    "pe": "Peru",
    "peru": "Peru",

    "pt": "Portugal",
    "portugal": "Portugal",

    "gr": "Greece",
    "greece": "Greece",

    "il": "Israel",
    "israel": "Israel",

    "ph": "Philippines",
    "philippines": "Philippines",

    "sg": "Singapore",
    "singapore": "Singapore",

    "my": "Malaysia",
    "malaysia": "Malaysia",

    "th": "Thailand",
    "thailand": "Thailand",

    "hk": "Hong Kong",
    "hong-kong": "Hong Kong",
    "hong_kong": "Hong Kong",

    "tw": "Taiwan",
    "taiwan": "Taiwan",
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
            f"&sort=updated"
        )

        try:

            data = github_json(url)

        except Exception as error:

            print(
                f"[ERROR] Cannot read repositories: "
                f"{error}"
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
                    "default_branch": (
                        repo.get("default_branch")
                        or "main"
                    ),
                }
            )

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
                f"[WARNING] GitHub tree is truncated: "
                f"{repo}"
            )

        return data.get(
            "tree",
            []
        )

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
# SERVICE NAME
# ============================================================

def clean_service_name(repo):

    known = {
        "app-m3u-generator": "FAST Apps",
        "plex-alt-fast-channels": "Plex Alt",
        "samsungtvplus": "Samsung TV Plus",
        "roku-playlist-generator": "Roku",
        "tubi-scraper": "Tubi",
        "xumo-playlist-generator": "Xumo",
        "localnow-playlist-generator": "Local Now",
        "lg-playlist-generator": "LG Channels",
        "lg-playlist-generator2": "LG Channels 2",
        "tcl-playlist-generator": "TCL TV+",
        "distro-playlist-generator": "DistroTV",
        "RakutenTV": "Rakuten TV",
        "airy-playlist-generator": "Airy TV",
        "pluto": "Pluto TV",
        "plex": "Plex",
        "buddylive": "BuddyLive",
        "buddylive_v2": "BuddyLive V2",
        "buddylive-combined": "BuddyLive",
        "My-Streams": "My Streams",
    }

    if repo in known:
        return known[repo]

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

    escaped_group = (
        group
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
            f'group-title="{escaped_group}"',
            extinf,
            flags=re.IGNORECASE
        )

    comma = extinf.find(",")

    if comma == -1:
        return extinf

    return (
        extinf[:comma]
        + f' group-title="{escaped_group}"'
        + extinf[comma:]
    )


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(value):

    value = unquote(
        value or ""
    )

    value = value.lower()

    value = re.sub(
        r"[_\-]+",
        " ",
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


# ============================================================
# ORIGINAL GROUP
# ============================================================

def extract_original_group(extinf):

    group = get_attribute(
        extinf,
        "group-title"
    )

    if not group:
        return ""

    return group.strip()


# ============================================================
# GROUP HANDLING
# ============================================================

def simplify_group(group):

    if not group:
        return "General"

    group = group.strip()

    # Preserve multi-level groups exactly.
    #
    # Examples:
    #
    # News | US
    # Entertainment | Movies
    # Sports | Football
    #
    # are NOT flattened.
    #
    # Only duplicated separators are cleaned.

    group = re.sub(
        r"\s*\|\s*",
        " | ",
        group
    )

    group = re.sub(
        r"\s*>\s*",
        " > ",
        group
    )

    group = re.sub(
        r"\s+",
        " ",
        group
    )

    return group.strip(
        " |>"
    ) or "General"


def choose_group(
    extinf,
    path,
    service
):

    original = extract_original_group(
        extinf
    )

    # ========================================================
    # MOST IMPORTANT RULE:
    #
    # If source already supplies group-title,
    # KEEP IT.
    # ========================================================

    if original:

        return simplify_group(
            original
        )

    # ========================================================
    # If source has NO group-title,
    # use a simple fallback.
    # ========================================================

    filename = (
        PurePosixPath(path)
        .stem
    )

    filename = re.sub(
        r"[_\-]+",
        " ",
        filename
    )

    filename = re.sub(
        r"\s+",
        " ",
        filename
    ).strip()

    lower = filename.lower()

    if lower in {
        "all",
        "playlist",
        "combined playlist",
        "combined",
        "tv",
        "videoall",
    }:

        return service

    if filename:

        return (
            f"{service} | "
            f"{filename}"
        )

    return service


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

        if line.startswith(
            "#EXTINF:"
        ):

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
# PREVIOUS OUTPUT
# ============================================================

def parse_previous_output():

    try:

        with open(
            OUTPUT,
            "r",
            encoding="utf-8"
        ) as file:

            text = file.read()

        return parse_m3u(
            text
        )

    except Exception:

        return []


def get_previous_service(extinf):

    group = get_attribute(
        extinf,
        "group-title"
    )

    if not group:
        return ""

    return group.split(
        "|",
        1
    )[0].strip()


# ============================================================
# BUILD
# ============================================================

def main():

    print()
    print("=" * 70)
    print("FAST ALL REGIONS - CLEAN GROUP BUILDER")
    print("=" * 70)

    repositories = (
        get_all_repositories()
    )

    print(
        f"Repositories discovered: "
        f"{len(repositories)}"
    )

    previous_entries = (
        parse_previous_output()
    )

    previous_by_service = defaultdict(list)

    for extinf, url in previous_entries:

        service = get_previous_service(
            extinf
        )

        if service:

            previous_by_service[
                service
            ].append(
                (
                    extinf,
                    url
                )
            )

    all_entries = []

    failed_files = []

    repository_stats = {}

    # ========================================================
    # DISCOVER ALL REPOSITORIES
    # ========================================================

    for repo_info in repositories:

        repo = repo_info["name"]
        branch = repo_info["default_branch"]

        print()
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

        if not playlist_paths:

            repository_stats[
                repo
            ] = {
                "files": 0,
                "successful": 0,
                "channels": 0,
            }

            continue

        service = clean_service_name(
            repo
        )

        successful_files = 0
        repo_channels = 0

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
                repo_channels += len(
                    entries
                )

                for extinf, stream_url in entries:

                    stream_url = (
                        stream_url.strip()
                    )

                    if not stream_url:
                        continue

                    final_group = choose_group(
                        extinf,
                        path,
                        service
                    )

                    new_extinf = (
                        replace_group_title(
                            extinf,
                            final_group
                        )
                    )

                    all_entries.append(
                        {
                            "extinf": new_extinf,
                            "url": stream_url,
                            "service": service,
                            "group": final_group,
                            "name": (
                                get_channel_name(
                                    extinf
                                )
                            ),
                        }
                    )

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

        repository_stats[
            repo
        ] = {
            "files": len(
                playlist_paths
            ),
            "successful": successful_files,
            "channels": repo_channels,
        }

        # ========================================================
        # FALLBACK ONLY IF ENTIRE REPO FAILED
        # ========================================================

        if (
            len(playlist_paths) > 0
            and successful_files == 0
        ):

            old_entries = (
                previous_by_service.get(
                    service,
                    []
                )
            )

            if old_entries:

                print(
                    f"  [FALLBACK] "
                    f"Keeping "
                    f"{len(old_entries)} "
                    f"previous entries for "
                    f"{service}"
                )

                for extinf, url in old_entries:

                    group = (
                        get_attribute(
                            extinf,
                            "group-title"
                        )
                        or service
                    )

                    all_entries.append(
                        {
                            "extinf": extinf,
                            "url": url.strip(),
                            "service": service,
                            "group": group,
                            "name": (
                                get_channel_name(
                                    extinf
                                )
                            ),
                        }
                    )

    # ========================================================
    # DEDUPLICATION
    # ========================================================

    print()
    print(
        "Removing duplicate streams..."
    )

    seen = set()

    unique_entries = []

    duplicate_count = 0

    for entry in all_entries:

        url_key = (
            entry["url"]
            .strip()
            .lower()
        )

        name_key = normalize_text(
            entry["name"]
        )

        group_key = normalize_text(
            entry["group"]
        )

        # IMPORTANT:
        #
        # Same stream + same channel name
        # = duplicate.
        #
        # Group is NOT used to keep duplicates alive.
        #

        dedup_key = (
            url_key,
            name_key,
        )

        if dedup_key in seen:

            duplicate_count += 1

            continue

        seen.add(
            dedup_key
        )

        unique_entries.append(
            entry
        )

    # ========================================================
    # SORT
    # ========================================================

    unique_entries.sort(
        key=lambda item: (
            normalize_text(
                item["service"]
            ),
            normalize_text(
                item["group"]
            ),
            normalize_text(
                item["name"]
            ),
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
    # GROUP STATISTICS
    # ========================================================

    groups = defaultdict(int)

    for entry in unique_entries:

        groups[
            entry["group"]
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
        f"Unique entries: "
        f"{len(unique_entries)}"
    )

    print(
        f"Duplicates removed: "
        f"{duplicate_count}"
    )

    print(
        f"Unique groups: "
        f"{len(groups)}"
    )

    print(
        f"Output: "
        f"{OUTPUT}"
    )

    print()
    print(
        "Group structure: ORIGINAL SOURCE"
    )

    print(
        "Artificial country grouping: DISABLED"
    )

    print(
        "Artificial service grouping: DISABLED"
    )

    print(
        "Stream health checks: DISABLED"
    )

    print(
        "Offline/temporary streams: KEPT"
    )

    print(
        "Repository discovery: DYNAMIC"
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
    # TOP GROUPS
    # ========================================================

    print()
    print(
        "TOP GROUPS"
    )
    print(
        "-" * 70
    )

    top_groups = sorted(
        groups.items(),
        key=lambda x: x[1],
        reverse=True
    )

    for group, count in top_groups[:50]:

        print(
            f"{count:5d}  {group}"
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
