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

PLAYLIST_EXTENSIONS = (".m3u", ".m3u8")

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
        "buddylive": "BuddyLive",
        "buddylive_v2": "BuddyLive",
        "buddylive-combined": "BuddyLive",
        "My-Streams": "My Streams",
        "sports": "Sports",
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


def normalize_country(value):

    value = normalize_text(
        value
    )

    compact = value.replace(
        " ",
        ""
    )

    if value in COUNTRIES:
        return COUNTRIES[value]

    if compact in COUNTRIES:
        return COUNTRIES[compact]

    return ""


# ============================================================
# EXPLICIT REGION ONLY
# ============================================================

def region_from_filename(path):

    stem = PurePosixPath(path).stem

    # Only inspect the filename itself.
    #
    # Examples:
    #
    # plex_us.m3u       -> US
    # plex_gb.m3u       -> UK
    # samsungtvplus_de  -> Germany
    #
    # No channel-name guessing.

    tokens = re.split(
        r"[^a-zA-Z]+",
        stem
    )

    for token in reversed(tokens):

        country = normalize_country(
            token
        )

        if country:
            return country

    return ""


def region_from_metadata(extinf):

    # Explicit country/region attributes only.

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

        country = normalize_country(
            value
        )

        if country:
            return country

    return ""


def determine_region(
    extinf,
    path
):

    # ========================================================
    # PRIORITY 1:
    # Explicit metadata in the channel.
    # ========================================================

    region = region_from_metadata(
        extinf
    )

    if region:
        return region

    # ========================================================
    # PRIORITY 2:
    # Explicit region in playlist filename.
    # ========================================================

    region = region_from_filename(
        path
    )

    if region:
        return region

    # ========================================================
    # IMPORTANT:
    #
    # NO GUESSING.
    #
    # If the playlist is "all" and there is no explicit
    # region metadata, the whole playlist stays ALL.
    # ========================================================

    return "All"


# ============================================================
# PARSE M3U
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

            return parse_m3u(
                file.read()
            )

    except Exception:

        return []


# ============================================================
# BUILD
# ============================================================

def main():

    print()
    print("=" * 70)
    print("FAST ALL REGIONS - FINAL BUILDER")
    print("=" * 70)

    print(
        "Region detection: EXPLICIT ONLY"
    )

    print(
        "Category format: SERVICE | REGION"
    )

    print(
        "Channel-name region guessing: DISABLED"
    )

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

                # Region defined by the playlist itself.
                file_region = (
                    determine_region(
                        "",
                        path
                    )
                )

                for extinf, stream_url in entries:

                    stream_url = (
                        stream_url.strip()
                    )

                    if not stream_url:
                        continue

                    # Metadata may explicitly define a region
                    # inside an otherwise "all" playlist.
                    metadata_region = (
                        region_from_metadata(
                            extinf
                        )
                    )

                    region = (
                        metadata_region
                        or file_region
                    )

                    final_group = (
                        f"{service} | "
                        f"{region}"
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
                            "region": region,
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
    # DEDUPLICATION
    # ========================================================

    print()
    print(
        "Removing exact duplicate streams..."
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
    # GROUP STATISTICS
    # ========================================================

    groups = defaultdict(int)

    for entry in unique_entries:

        groups[
            f"{entry['service']} | "
            f"{entry['region']}"
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
        f"Exact duplicate URLs removed: "
        f"{duplicate_count}"
    )

    print(
        f"Final categories: "
        f"{len(groups)}"
    )

    print(
        f"Output: "
        f"{OUTPUT}"
    )

    print()
    print(
        "Category format: SERVICE | REGION"
    )

    print(
        "Original group-title: NOT USED"
    )

    print(
        "Region guessing: DISABLED"
    )

    print(
        "All playlists without explicit region: All"
    )

    print(
        "Stream health checks: DISABLED"
    )

    print(
        "Offline/temporary streams: KEPT"
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
    # CATEGORY SUMMARY
    # ========================================================

    print()
    print(
        "CATEGORY SUMMARY"
    )
    print(
        "-" * 70
    )

    for group, count in sorted(
        groups.items(),
        key=lambda x: (
            normalize_text(x[0])
        )
    ):

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
