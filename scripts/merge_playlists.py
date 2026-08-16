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
# GITHUB DISCOVERY
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
        f"{OWNER}/{quote(repo)}"
        f"/git/trees/{quote(branch)}"
        f"?recursive=1"
    )

    try:

        data = github_json(url)

        if data.get("truncated"):

            print(
                f"[WARNING] Tree truncated: {repo}"
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

        if is_playlist(path):

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

    if re.search(
        r'group-title="[^"]*"',
        extinf,
        re.IGNORECASE
    ):

        return re.sub(
            r'group-title="[^"]*"',
            lambda m: f'group-title="{group}"',
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
# COUNTRY / REGION
# ============================================================

def detect_country(
    extinf,
    path,
    service
):

    # --------------------------------------------------------
    # 1. Explicit metadata
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 2. Filename/path
    # --------------------------------------------------------

    stem = (
        PurePosixPath(path)
        .stem
        .lower()
    )

    tokens = re.split(
        r"[^a-zA-Z]+",
        stem
    )

    for token in tokens:

        country = normalize_country(
            token
        )

        if country:
            return country

    # --------------------------------------------------------
    # 3. Original group
    # --------------------------------------------------------

    original_group = get_attribute(
        extinf,
        "group-title"
    )

    if original_group:

        pieces = re.split(
            r"[|>/,;:]+",
            original_group
        )

        for piece in pieces:

            country = normalize_country(
                piece
            )

            if country:
                return country

    # --------------------------------------------------------
    # 4. tvg-id
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 5. Known US-oriented services
    # --------------------------------------------------------

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


# ============================================================
# ORIGINAL GROUP
# ============================================================

def extract_original_group(extinf):

    group = get_attribute(
        extinf,
        "group-title"
    )

    if not group:
        return "General"

    group = group.strip()

    return group or "General"


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


def detect_previous_repo(extinf):

    """
    Try to recover repository information from the
    generated group-title.

    Example:
      group-title="Plex | US | News"

    This is intentionally conservative.
    """

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

    previous_by_service = defaultdict(list)

    for extinf, url in previous_entries:

        service = detect_previous_repo(
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

    failed_repositories = []

    # ========================================================
    # EVERY PUBLIC BUDDYCHEWCHEW REPOSITORY
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
            continue

        service = clean_service_name(
            repo
        )

        repo_entries_before = len(
            all_entries
        )

        successful_files = 0

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

                successful_files += 1

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

                    # IMPORTANT:
                    #
                    # The genre/category is NEVER hard-coded.
                    #
                    # It is read directly from the source playlist.
                    #
                    # Therefore future changes in Buddy's
                    # group-title are automatically reflected.

                    final_group = (
                        f"{service} | "
                        f"{country} | "
                        f"{original_group}"
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
                            "url": stream_url.strip(),
                            "service": service,
                            "country": country,
                            "original_group": original_group,
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

        # ----------------------------------------------------
        # If the whole repository failed, keep previous
        # entries belonging to the same service.
        # ----------------------------------------------------

        repo_entries_after = len(
            all_entries
        )

        if (
            successful_files == 0
            and repo_entries_after
            == repo_entries_before
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
                    f"Keeping {len(old_entries)} "
                    f"previous entries for "
                    f"{service}"
                )

                for extinf, url in old_entries:

                    all_entries.append(
                        {
                            "extinf": extinf,
                            "url": url.strip(),
                            "service": service,
                            "country": "",
                            "original_group": (
                                get_attribute(
                                    extinf,
                                    "group-title"
                                )
                            ),
                            "name": get_channel_name(
                                extinf
                            ),
                        }
                    )

            else:

                failed_repositories.append(
                    repo
                )

    # ========================================================
    # DEDUPLICATION
    # ========================================================

    print()
    print(
        "Removing only metadata-identical duplicates..."
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

        service_key = normalize_text(
            entry["service"]
        )

        name_key = normalize_text(
            entry["name"]
        )

        group_key = normalize_text(
            entry["original_group"]
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

    # ========================================================
    # SORT
    # ========================================================

    unique_entries.sort(
        key=lambda item: (
            normalize_text(
                item["service"]
            ),
            normalize_text(
                item["country"]
            ),
            normalize_text(
                item["original_group"]
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

    print()
    print(
        "Stream health checks: DISABLED"
    )

    print(
        "Offline streams: KEPT"
    )

    print(
        "Source group-title: DYNAMIC"
    )

    print(
        "Repository discovery: DYNAMIC"
    )

    if failed_repositories:

        print()
        print(
            "[WARNING] Repositories with no "
            "usable playlist:"
        )

        for repo in failed_repositories:

            print(
                f"  - {repo}"
            )


if __name__ == "__main__":
    main()
