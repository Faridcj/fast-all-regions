import json
import re
import urllib.request
import urllib.error
from urllib.parse import quote, unquote
from pathlib import PurePosixPath
from collections import defaultdict

OWNER = "BuddyChewChew"
OUTPUT = "fast-all-regions.m3u"

API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "FAST-All-Regions-Builder",
}

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 FAST-All-Regions-Builder"
}

# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

REQUEST_TIMEOUT = 90

# Files considered playlists
PLAYLIST_EXTENSIONS = (
    ".m3u",
    ".m3u8",
)

# Files/directories that should not be treated as channel lists
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

# ------------------------------------------------------------
# COUNTRY / REGION MAP
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# GITHUB DISCOVERY
# ------------------------------------------------------------

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
                f"[ERROR] Cannot read repository list: "
                f"{error}"
            )

            break

        if not data:
            break

        for repo in data:

            if repo.get("fork"):
                continue

            repositories.append(
                {
                    "name": repo["name"],
                    "default_branch": (
                        repo.get(
                            "default_branch"
                        )
                        or "main"
                    ),
                }
            )

        if len(data) < 100:
            break

        page += 1

    return repositories


def get_repository_tree(
    repo,
    branch
):

    url = (
        f"https://api.github.com/repos/"
        f"{OWNER}/{quote(repo)}"
        f"/git/trees/{quote(branch)}"
        f"?recursive=1"
    )

    try:

        data = github_json(url)

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


# ------------------------------------------------------------
# PLAYLIST DISCOVERY
# ------------------------------------------------------------

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


def discover_playlists(
    repo,
    branch
):

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


# ------------------------------------------------------------
# SERVICE NAME
# ------------------------------------------------------------

def clean_service_name(repo):

    names = {
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
    }

    if repo in names:
        return names[repo]

    # Generic fallback for future Buddy repos
    name = repo

    name = re.sub(
        r"[-_]+",
        " ",
        name
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


# ------------------------------------------------------------
# ATTRIBUTE HELPERS
# ------------------------------------------------------------

def get_attribute(
    extinf,
    attribute
):

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


def replace_group_title(
    extinf,
    group
):

    if re.search(
        r'group-title="[^"]*"',
        extinf,
        re.IGNORECASE
    ):

        return re.sub(
            r'group-title="[^"]*"',
            f'group-title="{group}"',
            extinf,
            flags=re.IGNORECASE
        )

    comma = extinf.find(",")

    if comma == -1:
        return extinf

    return (
        extinf[:comma]
        + f' group-title="{group}"'
        + extinf[comma:]
    )


# ------------------------------------------------------------
# NORMALIZATION
# ------------------------------------------------------------

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


def normalize_country(
    value
):

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


# ------------------------------------------------------------
# COUNTRY DETECTION
# ------------------------------------------------------------

def detect_country(
    extinf,
    path,
    service
):

    # 1. Explicit metadata
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

    # 2. File/path tokens
    path_text = (
        PurePosixPath(path)
        .stem
        .lower()
    )

    tokens = re.split(
        r"[^a-zA-Z]+",
        path_text
    )

    for token in tokens:

        country = normalize_country(
            token
        )

        if country:
            return country

    # 3. Group title
    group = get_attribute(
        extinf,
        "group-title"
    )

    if group:

        pieces = re.split(
            r"[|>/,;:]+",
            group
        )

        for piece in pieces:

            country = normalize_country(
                piece
            )

            if country:
                return country

    # 4. tvg-id prefix
    tvgid = get_attribute(
        extinf,
        "tvg-id"
    )

    if tvgid:

        for token in re.split(
            r"[-_.:]+",
            tvgid
        ):

            country = normalize_country(
                token
            )

            if country:
                return country

    # 5. Known service defaults
    defaults = {
        "LG Channels": "US",
        "LG Channels 2": "US",
        "TCL TV+": "US",
        "Xumo": "US",
        "Local Now": "US",
        "Tubi": "US",
        "Airy TV": "US",
    }

    return defaults.get(
        service,
        "Global"
    )


# ------------------------------------------------------------
# GENRE
# ------------------------------------------------------------

def extract_original_group(
    extinf
):

    group = get_attribute(
        extinf,
        "group-title"
    )

    if not group:
        return "General"

    group = group.strip()

    if not group:
        return "General"

    return group


# ------------------------------------------------------------
# PLAYLIST PARSER
# ------------------------------------------------------------

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
                    line.strip()
                )
            )

            current_extinf = None

    return entries


# ------------------------------------------------------------
# CHANNEL NAME
# ------------------------------------------------------------

def get_channel_name(
    extinf
):

    if "," not in extinf:
        return ""

    return (
        extinf
        .split(",", 1)[1]
        .strip()
    )


# ------------------------------------------------------------
# SOURCE ID
# ------------------------------------------------------------

def source_id(
    repo,
    path
):

    return (
        f"{repo}/{path}"
    )


# ------------------------------------------------------------
# LOAD PREVIOUS PLAYLIST
#
# Used only as a safety net when a source temporarily
# becomes unavailable.
# ------------------------------------------------------------

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


def extract_source_marker(
    extinf
):

    return get_attribute(
        extinf,
        "x-source"
    )


# ------------------------------------------------------------
# BUILD
# ------------------------------------------------------------

def main():

    print()
    print("=" * 70)
    print("FAST ALL REGIONS - DYNAMIC BUILDER")
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

    # Previous entries grouped by repository.
    previous_by_repo = defaultdict(list)

    for extinf, url in previous_entries:

        marker = extract_source_marker(
            extinf
        )

        if marker:

            repo = marker.split(
                "/",
                1
            )[0]

            previous_by_repo[
                repo
            ].append(
                (
                    extinf,
                    url
                )
            )

    all_entries = []

    successful_sources = set()
    failed_sources = []

    # --------------------------------------------------------
    # DISCOVER EVERY REPO
    # --------------------------------------------------------

    for repo_info in repositories:

        repo = repo_info[
            "name"
        ]

        branch = repo_info[
            "default_branch"
        ]

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

            continue

        service = clean_service_name(
            repo
        )

        repo_success = False

        for path in playlist_paths:

            raw_url = (
                "https://raw.githubusercontent.com/"
                f"{OWNER}/"
                f"{quote(repo)}/"
                f"{quote(path)}"
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

                successful_sources.add(
                    source_id(
                        repo,
                        path
                    )
                )

                repo_success = True

                for extinf, stream_url in entries:

                    country = detect_country(
                        extinf,
                        path,
                        service
                    )

                    original_group = (
                        extract_original_group(
                            extinf
                        )
                    )

                    # ------------------------------------------------
                    # IMPORTANT:
                    #
                    # We do NOT hard-code genres.
                    #
                    # Whatever group-title the source currently has
                    # is automatically used.
                    #
                    # Therefore if Buddy changes:
                    #
                    # News -> News & Politics
                    #
                    # our next automatic run picks it up.
                    # ------------------------------------------------

                    group = (
                        f"{service} | "
                        f"{country} | "
                        f"{original_group}"
                    )

                    new_extinf = (
                        replace_group_title(
                            extinf,
                            group
                        )
                    )

                    # Add an internal source marker.
                    # This is metadata only and does not alter the
                    # channel URL.
                    if 'x-source="' not in new_extinf:

                        comma = new_extinf.find(
                            ","
                        )

                        if comma != -1:

                            new_extinf = (
                                new_extinf[:comma]
                                + ' x-source="'
                                + source_id(
                                    repo,
                                    path
                                )
                                + '"'
                                + new_extinf[comma:]
                            )

                    all_entries.append(
                        {
                            "extinf": new_extinf,
                            "url": stream_url,
                            "repo": repo,
                            "path": path,
                            "service": service,
                            "country": country,
                            "group": original_group,
                            "name": get_channel_name(
                                extinf
                            ),
                        }
                    )

            except Exception as error:

                print(
                    f"  [WARNING] "
                    f"{path} failed: "
                    f"{error}"
                )

                failed_sources.append(
                    (
                        repo,
                        path,
                        str(error)
                    )
                )

        # --------------------------------------------------------
        # If an entire repo has failed, retain its previous
        # entries from the last successful run.
        # --------------------------------------------------------

        if not repo_success:

            old_entries = (
                previous_by_repo.get(
                    repo,
                    []
                )
            )

            if old_entries:

                print(
                    f"  [FALLBACK] "
                    f"Keeping {len(old_entries)} "
                    f"previous channels from {repo}"
                )

                for extinf, url in old_entries:

                    all_entries.append(
                        {
                            "extinf": extinf,
                            "url": url,
                            "repo": repo,
                            "path": extract_source_marker(
                                extinf
                            ),
                            "service": clean_service_name(
                                repo
                            ),
                            "country": "",
                            "group": "",
                            "name": get_channel_name(
                                extinf
                            ),
                        }
                    )

    # --------------------------------------------------------
    # DEDUPLICATION
    #
    # NOT URL-only.
    #
    # Same stream URL + same service + same channel name
    # + same group = duplicate.
    #
    # If metadata differs, retain it.
    # --------------------------------------------------------

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

        service_key = normalize_text(
            entry["service"]
        )

        group_key = normalize_text(
            entry["group"]
        )

        dedup_key = (
            url_key,
            service_key,
            name_key,
            group_key,
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

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    unique_entries.sort(
        key=lambda item: (
            normalize_text(
                item["service"]
            ),
            normalize_text(
                item["country"]
            ),
            normalize_text(
                item["group"]
            ),
            normalize_text(
                item["name"]
            ),
        )
    )

    # --------------------------------------------------------
    # WRITE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("BUILD COMPLETE")
    print("=" * 70)

    print(
        f"Repositories: "
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
        f"Output: "
        f"{OUTPUT}"
    )

    if failed_sources:

        print()
        print(
            "Sources with errors:"
        )

        for repo, path, error in (
            failed_sources
        ):

            print(
                f"  {repo}/{path}"
            )

            print(
                f"    {error}"
            )

    print()
    print(
        "IMPORTANT:"
    )

    print(
        "No stream health checks were performed."
    )

    print(
        "Offline/temporary streams were NOT removed."
    )

    print(
        "Playlist group titles are read dynamically "
        "from the source files."
    )


if __name__ == "__main__":
    main()
