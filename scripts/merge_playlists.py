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
# REGION MAP
# ============================================================

REGIONS = {
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
# GITHUB
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
                f"[ERROR] Cannot read repositories: {error}"
            )

            break

        if not data:
            break

        for repo in data:

            if repo.get("fork"):
                continue

            if repo.get("archived"):
                continue

            repositories.append({
                "name": repo["name"],
                "default_branch": (
                    repo.get("default_branch")
                    or "main"
                ),
            })

        if len(data) < 100:
            break

        page += 1

    return repositories


def get_repository_tree(repo, branch):

    url = (
        f"https://api.github.com/repos/"
        f"{OWNER}/"
        f"{quote(repo, safe='')}"
        f"/git/trees/"
        f"{quote(branch, safe='/')}"
        f"?recursive=1"
    )

    try:

        data = github_json(url)

        if data.get("truncated"):

            print(
                f"[WARNING] GitHub tree truncated: {repo}"
            )

        return data.get("tree", [])

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

    if parts.intersection(IGNORE_PARTS):
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

        path = item.get("path", "")

        if is_playlist(path):
            result.append(path)

    return sorted(result)


# ============================================================
# SERVICE NAME
# ============================================================

def clean_service_name(repo):

    known = {
        "app-m3u-generator": "FAST Apps",
        "plex-alt-fast-channels": "Plex",
        "samsungtvplus": "Samsung TV Plus",
        "roku-playlist-generator": "Roku",
        "tubi-scraper": "Tubi",
        "xumo-playlist-generator": "Xumo",
        "localnow-playlist-generator": "Local Now",
        "lg-playlist-generator": "LG Channels",
        "lg-playlist-generator2": "LG Channels",
        "tcl-playlist-generator": "TCL TV+",
        "distro-playlist-generator": "DistroTV",
        "RakutenTV": "Rakuten TV",
        "airy-playlist-generator": "Airy TV",
        "pluto": "Pluto TV",
        "plex": "Plex",
        "My-Streams": "My Streams",
        "sports": "Sports",
        "buddylive": "BuddyLive",
        "buddylive_v2": "BuddyLive",
        "buddylive-combined": "BuddyLive",
        "nz": "NZ",
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


def normalize_region(value):

    value = normalize_text(value)

    compact = value.replace(
        " ",
        ""
    )

    if value in REGIONS:
        return REGIONS[value]

    if compact in REGIONS:
        return REGIONS[compact]

    return ""


# ============================================================
# REGION FROM FILE NAME ONLY
# ============================================================

def region_from_filename(path):

    filename = PurePosixPath(path).stem.lower()

    # Examples:
    # plex_us
    # plex_gb
    # samsungtvplus_us

    tokens = re.split(
        r"[^a-zA-Z]+",
        filename
    )

    # Only explicit region token.
    # NEVER guess.

    for token in reversed(tokens):

        region = normalize_region(
            token
        )

        if region:
            return region

    return ""


# ============================================================
# REGION FROM ORIGINAL GROUP
# ============================================================

def region_from_group(extinf):

    group = get_attribute(
        extinf,
        "group-title"
    )

    if not group:
        return ""

    # First inspect the complete group.
    region = normalize_region(group)

    if region:
        return region

    # Then inspect group components.
    pieces = re.split(
        r"[|>/,;:]+",
        group
    )

    for piece in pieces:

        region = normalize_region(
            piece
        )

        if region:
            return region

    return ""


# ============================================================
# REGION FROM M3U METADATA
# ============================================================

def region_from_metadata(extinf):

    for attr in (
        "country",
        "region",
        "tvg-country",
        "country-code",
        "iso_country",
    ):

        value = get_attribute(
            extinf,
            attr
        )

        region = normalize_region(
            value
        )

        if region:
            return region

    return ""


# ============================================================
# REGION
# ============================================================

def determine_region(
    extinf,
    path
):

    # ========================================================
    # RULE 1
    # Explicit country/region metadata.
    # ========================================================

    region = region_from_metadata(
        extinf
    )

    if region:
        return region

    # ========================================================
    # RULE 2
    # Explicit region inside original group-title.
    # ========================================================

    region = region_from_group(
        extinf
    )

    if region:
        return region

    # ========================================================
    # RULE 3
    # Explicit region in filename.
    #
    # IMPORTANT:
    # We DO NOT infer anything from service name.
    # ========================================================

    region = region_from_filename(
        path
    )

    if region:
        return region

    # ========================================================
    # RULE 4
    #
    # No explicit region.
    #
    # NEVER GUESS.
    # ========================================================

    return "Global"


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
# BUILD
# ============================================================

def main():

    print()
    print("=" * 70)
    print("FAST ALL REGIONS - CLEAN BUILDER")
    print("=" * 70)

    repositories = (
        get_all_repositories()
    )

    print(
        f"Repositories discovered: "
        f"{len(repositories)}"
    )

    all_entries = []

    failed_files = []

    repository_stats = {}

    # ========================================================
    # REPOSITORIES
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

                # Explicit region associated
                # with the FILE.
                file_region = (
                    region_from_filename(
                        path
                    )
                )

                for extinf, stream_url in entries:

                    stream_url = (
                        stream_url.strip()
                    )

                    if not stream_url:
                        continue

                    # =================================================
                    # REGION PRIORITY
                    #
                    # 1. channel metadata
                    # 2. original group
                    # 3. filename
                    # 4. Global
                    #
                    # Never guess.
                    # =================================================

                    region = (
                        determine_region(
                            extinf,
                            path
                        )
                    )

                    # =================================================
                    # IMPORTANT FOR *_ALL FILES
                    #
                    # If the filename is "all", do NOT force
                    # a country. Each channel keeps its own
                    # explicit region if present.
                    #
                    # Otherwise Global.
                    # =================================================

                    final_group = (
                        f"{service} | {region}"
                    )

                    new_extinf = (
                        replace_group_title(
                            extinf,
                            final_group
                        )
                    )

                    all_entries.append({
                        "extinf": new_extinf,
                        "url": stream_url,
                        "service": service,
                        "region": region,
                        "name": (
                            get_channel_name(
                                extinf
                            )
                        ),
                    })

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
    # DEDUPLICATION
    #
    # ONLY URL.
    #
    # This prevents the same stream from appearing multiple
    # times because of Plex/FAST Apps duplicate repositories,
    # while preserving different streams.
    # ========================================================

    print()
    print(
        "Removing duplicate URLs..."
    )

    seen_urls = set()

    unique_entries = []

    duplicate_count = 0

    for entry in all_entries:

        url_key = (
            entry["url"]
            .strip()
            .lower()
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
            normalize_text(
                item["service"]
            ),
            normalize_text(
                item["region"]
            ),
            normalize_text(
                item["name"]
            ),
        )
    )

    # ========================================================
    # WRITE
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
    # REPORT
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
        f"Unique URLs: "
        f"{len(unique_entries)}"
    )

    print(
        f"Duplicate URLs removed: "
        f"{duplicate_count}"
    )

    print(
        f"Output: "
        f"{OUTPUT}"
    )

    print()
    print(
        "GROUP FORMAT: Service | Region"
    )

    print(
        "REGION DETECTION: EXPLICIT ONLY"
    )

    print(
        "REGION GUESSING: DISABLED"
    )

    print(
        "STREAM HEALTH CHECKS: DISABLED"
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
    # FAILURES
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
