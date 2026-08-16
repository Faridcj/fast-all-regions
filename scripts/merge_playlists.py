#!/usr/bin/env python3

import json
import re
import sys
import time
import socket
import urllib.error
import urllib.parse
import urllib.request

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# CONFIG
# ============================================================

OWNER = "BuddyChewChew"

OUTPUT_FILE = "fast-all-regions.m3u"

GITHUB_API = "https://api.github.com"

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; FAST-All-Regions-Builder/2.0)"
)

PLAYLIST_EXTENSIONS = (
    ".m3u",
    ".m3u8",
)

# ------------------------------------------------------------
# Health check configuration
# ------------------------------------------------------------

HEALTH_CHECK_ENABLED = True

HEALTH_CHECK_WORKERS = 24

HEALTH_CHECK_TIMEOUT = 12

HEALTH_CHECK_RETRIES = 1

HEALTH_CHECK_BYTES = 16384

# ------------------------------------------------------------
# Source priority
#
# LOWER NUMBER = HIGHER PRIORITY
# ------------------------------------------------------------

SOURCE_PRIORITY = {
    "app-m3u-generator": 1,

    "My-Streams": 2,

    "buddylive": 3,
    "buddylive-combined": 3,
    "buddylive_v2": 3,
}

DEFAULT_SOURCE_PRIORITY = 100


# ============================================================
# SPECIAL CATEGORY SOURCES
# ============================================================

SPECIAL_GROUPS = {
    "app-m3u-generator": "App M3U",

    "buddylive": "Buddy Live",
    "buddylive-combined": "Buddy Live",
    "buddylive_v2": "Buddy Live",

    "My-Streams": "My-Streams",
}


# ============================================================
# SOURCE NAME NORMALIZATION
# ============================================================

SOURCE_NAME_MAP = {

    "airy-playlist-generator":
        "Airy",

    "app-m3u-generator":
        "App M3U",

    "buddylive":
        "Buddy Live",

    "buddylive-combined":
        "Buddy Live",

    "buddylive_v2":
        "Buddy Live",

    "distro-playlist-generator":
        "DistroTV",

    "dlxes":
        "dlxes",

    "lg-playlist-generator":
        "LG",

    "lg-playlist-generator2":
        "LG",

    "My-Streams":
        "My-Streams",

    "nz":
        "NZ",

    "oly":
        "oly",

    "plex":
        "Plex",

    "plex-alt-fast-channels":
        "Plex",

    "pluto":
        "Pluto TV",

    "RakutenTV":
        "Rakuten TV",

    "roku-playlist-generator":
        "Roku",

    "samsungtvplus":
        "Samsung TV Plus",

    "sports":
        "Sports",

    "tcl-playlist-generator":
        "TCL",

    "tubi-scraper":
        "Tubi",

    "vod":
        "vod",

    "whiplash-epg":
        "whiplash-epg",

    "xumo-playlist-generator":
        "Xumo",
}


# ============================================================
# HTTP HELPERS
# ============================================================

def http_get(url, timeout=45, retries=3, headers=None):

    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        headers=request_headers
    )

    last_error = None

    for attempt in range(retries):

        try:

            with urllib.request.urlopen(
                request,
                timeout=timeout
            ) as response:

                return response.read()

        except urllib.error.HTTPError as exc:

            last_error = exc

            if exc.code == 404:
                raise

            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue

            raise

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout
        ) as exc:

            last_error = exc

            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue

            raise

    raise last_error


def http_get_text(url, timeout=45, retries=3):

    data = http_get(
        url,
        timeout=timeout,
        retries=retries
    )

    return data.decode(
        "utf-8-sig",
        errors="replace"
    )


def github_api(path, retries=3):

    url = GITHUB_API + path

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }

    request = urllib.request.Request(
        url,
        headers=headers
    )

    last_error = None

    for attempt in range(retries):

        try:

            with urllib.request.urlopen(
                request,
                timeout=45
            ) as response:

                return json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )

        except urllib.error.HTTPError as exc:

            last_error = exc

            if exc.code == 404:
                raise

            if exc.code == 403:

                remaining = exc.headers.get(
                    "X-RateLimit-Remaining"
                )

                if remaining == "0":

                    raise RuntimeError(
                        "GitHub API rate limit exceeded"
                    )

            if attempt < retries - 1:

                time.sleep(
                    min(
                        10,
                        2 ** attempt
                    )
                )

                continue

            raise

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout
        ) as exc:

            last_error = exc

            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue

            raise

    raise last_error


# ============================================================
# GROUP CLEANING
# ============================================================

def clean_group(group):

    if not group:
        return ""

    group = group.strip()

    group = re.sub(
        r"\s+",
        " ",
        group
    )

    return group


def get_first_level_group(group):

    group = clean_group(group)

    if not group:
        return ""

    separators = (
        "|",
        " > ",
        " / ",
        "\\",
    )

    for separator in separators:

        if separator in group:

            group = group.split(
                separator,
                1
            )[0].strip()

            break

    return group


# ============================================================
# FINAL GROUP DETERMINATION
# ============================================================

def get_final_group(
    repo_name,
    original_group
):

    # --------------------------------------------------------
    # SPECIAL SOURCES
    #
    # ORIGINAL group-title IS COMPLETELY IGNORED.
    # --------------------------------------------------------

    if repo_name in SPECIAL_GROUPS:

        return SPECIAL_GROUPS[
            repo_name
        ]

    # --------------------------------------------------------
    # NORMAL SOURCES
    # --------------------------------------------------------

    source = SOURCE_NAME_MAP.get(
        repo_name,
        repo_name
    )

    first_level = get_first_level_group(
        original_group
    )

    if not first_level:

        return source

    return (
        f"{source} | "
        f"{first_level}"
    )


# ============================================================
# M3U ATTRIBUTE PARSER
# ============================================================

ATTRIBUTE_PATTERN = re.compile(
    r'([\w:-]+)="([^"]*)"'
)


def parse_extinf(line):

    attributes = {}

    comma = line.find(",")

    if comma >= 0:

        metadata = line[:comma]

        channel_name = line[
            comma + 1:
        ].strip()

    else:

        metadata = line
        channel_name = ""

    for match in ATTRIBUTE_PATTERN.finditer(
        metadata
    ):

        key = match.group(1)
        value = match.group(2)

        attributes[key] = value

    return (
        attributes,
        channel_name
    )


# ============================================================
# M3U PARSER
# ============================================================

def parse_m3u(text):

    entries = []

    current_attributes = None
    current_name = None
    waiting_for_url = False

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#EXTINF"):

            attributes, name = parse_extinf(
                line
            )

            current_attributes = attributes
            current_name = name

            waiting_for_url = True

            continue

        if line.startswith("#"):

            continue

        if waiting_for_url:

            stream_url = line

            if stream_url:

                entries.append(
                    {
                        "name":
                            current_name or "",

                        "attrs":
                            dict(
                                current_attributes
                                or {}
                            ),

                        "url":
                            stream_url,
                    }
                )

            current_attributes = None
            current_name = None
            waiting_for_url = False

    return entries


# ============================================================
# GITHUB REPOSITORY DISCOVERY
# ============================================================

def discover_repositories():

    repositories = []

    page = 1

    while True:

        path = (
            f"/users/"
            f"{urllib.parse.quote(OWNER)}"
            f"/repos"
            f"?per_page=100"
            f"&page={page}"
        )

        data = github_api(path)

        if not data:
            break

        for repo in data:

            if repo.get("fork"):
                continue

            name = repo.get("name")

            if name:
                repositories.append(
                    name
                )

        if len(data) < 100:
            break

        page += 1

    return sorted(
        repositories,
        key=str.lower
    )


# ============================================================
# PLAYLIST FILE DISCOVERY
# ============================================================

def discover_playlist_files(repo_name):

    repo_path = (
        f"/repos/"
        f"{urllib.parse.quote(OWNER)}"
        f"/{urllib.parse.quote(repo_name)}"
    )

    repo_data = github_api(
        repo_path
    )

    default_branch = repo_data.get(
        "default_branch",
        "main"
    )

    tree_path = (
        f"/repos/"
        f"{urllib.parse.quote(OWNER)}"
        f"/{urllib.parse.quote(repo_name)}"
        f"/git/trees/"
        f"{urllib.parse.quote(default_branch)}"
        f"?recursive=1"
    )

    tree_data = github_api(
        tree_path
    )

    files = []

    for item in tree_data.get(
        "tree",
        []
    ):

        if item.get("type") != "blob":
            continue

        path = item.get(
            "path",
            ""
        )

        if path.lower().endswith(
            PLAYLIST_EXTENSIONS
        ):

            files.append(path)

    return sorted(
        files,
        key=str.lower
    )


# ============================================================
# RAW GITHUB URL
# ============================================================

def raw_url(
    repo_name,
    file_path
):

    encoded_parts = []

    for part in file_path.split("/"):

        encoded_parts.append(
            urllib.parse.quote(
                part,
                safe=""
            )
        )

    encoded_path = "/".join(
        encoded_parts
    )

    return (
        "https://raw.githubusercontent.com/"
        f"{OWNER}/"
        f"{urllib.parse.quote(repo_name)}/"
        f"HEAD/"
        f"{encoded_path}"
    )


# ============================================================
# SOURCE PRIORITY
# ============================================================

def get_source_priority(repo_name):

    return SOURCE_PRIORITY.get(
        repo_name,
        DEFAULT_SOURCE_PRIORITY
    )


# ============================================================
# CHANNEL IDENTITY
# ============================================================

def normalize_identity(value):

    if not value:
        return ""

    value = value.lower().strip()

    # Remove common punctuation
    value = re.sub(
        r"[\[\]\(\)\{\}:,._\-]+",
        " ",
        value
    )

    # Collapse whitespace
    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def get_channel_identity(entry):

    attrs = entry.get(
        "attrs",
        {}
    )

    # --------------------------------------------------------
    # Strongest identity: tvg-id
    # --------------------------------------------------------

    tvg_id = normalize_identity(
        attrs.get(
            "tvg-id",
            ""
        )
    )

    if tvg_id:

        return (
            "tvg-id:",
            tvg_id
        )

    # --------------------------------------------------------
    # Second: tvg-name
    # --------------------------------------------------------

    tvg_name = normalize_identity(
        attrs.get(
            "tvg-name",
            ""
        )
    )

    if tvg_name:

        return (
            "tvg-name:",
            tvg_name
        )

    # --------------------------------------------------------
    # Third: displayed channel name
    # --------------------------------------------------------

    channel_name = normalize_identity(
        entry.get(
            "name",
            ""
        )
    )

    if channel_name:

        return (
            "name:",
            channel_name
        )

    # --------------------------------------------------------
    # No reliable identity
    # --------------------------------------------------------

    return (
        "url:",
        entry.get(
            "url",
            ""
        ).strip()
    )


# ============================================================
# PLAYBACK URL HEADERS
# ============================================================

def get_stream_headers(entry):

    attrs = entry.get(
        "attrs",
        {}
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "application/vnd.apple.mpegurl,"
            "application/x-mpegURL,"
            "video/mp2t,"
            "*/*"
        ),
    }

    # --------------------------------------------------------
    # M3U commonly-used HTTP header attributes
    # --------------------------------------------------------

    user_agent = (
        attrs.get("http-user-agent")
        or attrs.get("user-agent")
        or attrs.get("http_ua")
    )

    if user_agent:

        headers["User-Agent"] = user_agent

    referrer = (
        attrs.get("http-referrer")
        or attrs.get("http-referrer")
        or attrs.get("referrer")
    )

    if referrer:

        headers["Referer"] = referrer

    return headers


# ============================================================
# HEALTH CHECK
# ============================================================

def is_hls_content(
    data,
    content_type=""
):

    sample = data[:HEALTH_CHECK_BYTES]

    text = sample.decode(
        "utf-8",
        errors="ignore"
    )

    if "#EXTM3U" in text:

        return True

    content_type = (
        content_type or ""
    ).lower()

    if (
        "mpegurl" in content_type
        or "vnd.apple.mpegurl" in content_type
    ):

        return True

    return False


def check_dns(hostname):

    try:

        socket.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM
        )

        return True, ""

    except Exception as exc:

        return (
            False,
            f"DNS: {exc}"
        )


def health_check_entry(entry):

    url = entry.get(
        "url",
        ""
    ).strip()

    if not url:

        return (
            False,
            "EMPTY_URL"
        )

    try:

        parsed = urllib.parse.urlparse(
            url
        )

    except Exception as exc:

        return (
            False,
            f"INVALID_URL: {exc}"
        )

    if parsed.scheme.lower() not in (
        "http",
        "https",
    ):

        # ----------------------------------------------------
        # Non-HTTP streams cannot reliably be checked with
        # urllib. Keep them instead of falsely deleting them.
        # ----------------------------------------------------

        return (
            True,
            "NON_HTTP_UNCHECKED"
        )

    if not parsed.hostname:

        return (
            False,
            "NO_HOST"
        )

    # --------------------------------------------------------
    # DNS
    # --------------------------------------------------------

    dns_ok, dns_reason = check_dns(
        parsed.hostname
    )

    if not dns_ok:

        return (
            False,
            dns_reason
        )

    # --------------------------------------------------------
    # HTTP / HLS
    # --------------------------------------------------------

    headers = get_stream_headers(
        entry
    )

    headers["Range"] = (
        f"bytes=0-{HEALTH_CHECK_BYTES - 1}"
    )

    request = urllib.request.Request(
        url,
        headers=headers
    )

    last_reason = ""

    for attempt in range(
        HEALTH_CHECK_RETRIES + 1
    ):

        try:

            with urllib.request.urlopen(
                request,
                timeout=HEALTH_CHECK_TIMEOUT
            ) as response:

                status = response.status

                content_type = (
                    response.headers.get(
                        "Content-Type",
                        ""
                    )
                )

                data = response.read(
                    HEALTH_CHECK_BYTES
                )

                # ------------------------------------------------
                # Definite HTTP failure
                # ------------------------------------------------

                if status >= 400:

                    return (
                        False,
                        f"HTTP_{status}"
                    )

                # ------------------------------------------------
                # Empty response
                # ------------------------------------------------

                if not data:

                    return (
                        False,
                        "EMPTY_RESPONSE"
                    )

                # ------------------------------------------------
                # HLS validation
                # ------------------------------------------------

                if is_hls_content(
                    data,
                    content_type
                ):

                    text = data.decode(
                        "utf-8",
                        errors="ignore"
                    )

                    # A valid HLS manifest should at least
                    # contain EXT-X or EXTINF information.
                    if (
                        "#EXT-X-" in text
                        or "#EXTINF" in text
                    ):

                        return (
                            True,
                            "HLS_OK"
                        )

                    # Some servers return a manifest whose
                    # useful data is beyond the first chunk.
                    return (
                        True,
                        "HLS_MANIFEST"
                    )

                # ------------------------------------------------
                # Generic HTTP stream
                #
                # Do not require HLS markers.
                # ------------------------------------------------

                return (
                    True,
                    f"HTTP_{status}"
                )

        except urllib.error.HTTPError as exc:

            last_reason = (
                f"HTTP_{exc.code}"
            )

            # 404 / 410 are definitely dead.
            if exc.code in (
                404,
                410,
            ):

                return (
                    False,
                    last_reason
                )

            # Other HTTP errors get one retry.
            if attempt < HEALTH_CHECK_RETRIES:

                time.sleep(1)

                continue

            return (
                False,
                last_reason
            )

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout
        ) as exc:

            last_reason = (
                f"CONNECTION: {exc}"
            )

            if attempt < HEALTH_CHECK_RETRIES:

                time.sleep(1)

                continue

            return (
                False,
                last_reason
            )

        except Exception as exc:

            last_reason = (
                f"ERROR: {exc}"
            )

            if attempt < HEALTH_CHECK_RETRIES:

                time.sleep(1)

                continue

            return (
                False,
                last_reason
            )

    return (
        False,
        last_reason or "UNKNOWN"
    )


# ============================================================
# HEALTH CHECK ALL ENTRIES
# ============================================================

def health_check_entries(entries):

    if not entries:

        return [], 0, 0, {}

    print()
    print(
        "=" * 70
    )

    print(
        "HEALTH CHECK"
    )

    print(
        "=" * 70
    )

    print(
        f"URLs to test: {len(entries)}"
    )

    print(
        f"Workers: {HEALTH_CHECK_WORKERS}"
    )

    print(
        f"Timeout: {HEALTH_CHECK_TIMEOUT}s"
    )

    print()

    healthy = []

    failed = 0

    reasons = Counter()

    results = {}

    with ThreadPoolExecutor(
        max_workers=HEALTH_CHECK_WORKERS
    ) as executor:

        future_map = {
            executor.submit(
                health_check_entry,
                entry
            ): entry
            for entry in entries
        }

        completed = 0

        total = len(
            future_map
        )

        for future in as_completed(
            future_map
        ):

            entry = future_map[
                future
            ]

            try:

                ok, reason = future.result()

            except Exception as exc:

                ok = False

                reason = (
                    f"CHECK_EXCEPTION: "
                    f"{exc}"
                )

            url = entry[
                "url"
            ].strip()

            results[url] = (
                ok,
                reason
            )

            completed += 1

            if ok:

                healthy.append(
                    entry
                )

            else:

                failed += 1

                reasons[
                    reason.split(
                        ":",
                        1
                    )[0]
                ] += 1

            if (
                completed % 100 == 0
                or completed == total
            ):

                print(
                    f"  Checked "
                    f"{completed}/"
                    f"{total}"
                    f" | Healthy: "
                    f"{len(healthy)}"
                    f" | Failed: "
                    f"{failed}"
                )

    print()

    print(
        f"Healthy URLs: "
        f"{len(healthy)}"
    )

    print(
        f"Failed URLs: "
        f"{failed}"
    )

    if reasons:

        print()
        print(
            "FAILURE REASONS"
        )

        for reason, count in sorted(
            reasons.items()
        ):

            print(
                f"  {reason}: "
                f"{count}"
            )

    return (
        healthy,
        failed,
        len(entries),
        results
    )


# ============================================================
# PRIORITY DUPLICATE RESOLUTION
# ============================================================

def choose_preferred_entries(
    entries
):

    """
    Build candidates by channel identity.

    Priority:

        App M3U
        My-Streams
        Buddy Live
        Other sources

    IMPORTANT:

    We do NOT immediately discard lower-priority URLs.

    All candidates are retained until health checking.

    This allows:

        App M3U   -> DEAD
        My-Streams -> HEALTHY

    to result in My-Streams being selected.
    """

    candidates = defaultdict(list)

    for entry in entries:

        identity = get_channel_identity(
            entry
        )

        candidates[
            identity
        ].append(
            entry
        )

    groups = []

    for identity, group in candidates.items():

        group.sort(
            key=lambda entry: (
                get_source_priority(
                    entry["repo"]
                ),
                entry["repo"].lower(),
                entry["url"].lower(),
            )
        )

        groups.append(
            (
                identity,
                group
            )
        )

    return groups


# ============================================================
# SELECT HEALTHY PREFERRED URL
# ============================================================

def select_best_entries(
    candidate_groups,
    health_results
):

    selected = []

    no_healthy_candidate = 0

    priority_replacements = 0

    selected_source_counter = Counter()

    for identity, candidates in candidate_groups:

        # ----------------------------------------------------
        # Sort by source priority first.
        # ----------------------------------------------------

        candidates = sorted(
            candidates,
            key=lambda entry: (
                get_source_priority(
                    entry["repo"]
                ),
                entry["repo"].lower(),
                entry["url"].lower(),
            )
        )

        healthy_candidates = []

        for entry in candidates:

            url = entry[
                "url"
            ].strip()

            result = health_results.get(
                url
            )

            if result and result[0]:

                healthy_candidates.append(
                    entry
                )

        # ----------------------------------------------------
        # No healthy URL
        # ----------------------------------------------------

        if not healthy_candidates:

            no_healthy_candidate += 1

            continue

        # ----------------------------------------------------
        # Highest priority healthy URL
        # ----------------------------------------------------

        best = healthy_candidates[0]

        # ----------------------------------------------------
        # Did health check force us away from the highest
        # priority source?
        # ----------------------------------------------------

        if (
            candidates
            and best["repo"]
            != candidates[0]["repo"]
        ):

            priority_replacements += 1

        selected.append(
            best
        )

        selected_source_counter[
            best["repo"]
        ] += 1

    return (
        selected,
        no_healthy_candidate,
        priority_replacements,
        selected_source_counter
    )


# ============================================================
# EXTINF OUTPUT
# ============================================================

def rebuild_extinf(
    entry,
    final_group
):

    attributes = dict(
        entry["attrs"]
    )

    attributes["group-title"] = (
        final_group
    )

    preferred_order = [

        "tvg-id",
        "tvg-name",
        "tvg-logo",

        "group-title",

        "tvg-language",
        "tvg-country",

        "tvg-url",
        "x-tvg-url",

        "catchup",
        "catchup-days",
        "catchup-source",

        "http-user-agent",
        "http-referrer",
    ]

    ordered_keys = []

    for key in preferred_order:

        if key in attributes:

            ordered_keys.append(
                key
            )

    for key in attributes:

        if key not in ordered_keys:

            ordered_keys.append(
                key
            )

    attribute_string = " ".join(
        f'{key}="{attributes[key]}"'
        for key in ordered_keys
    )

    channel_name = (
        entry["name"]
    )

    return (
        "#EXTINF:-1 "
        f"{attribute_string},"
        f"{channel_name}"
    )


# ============================================================
# MAIN BUILD
# ============================================================

def build():

    print(
        "=" * 70
    )

    print(
        "FAST ALL REGIONS BUILDER"
    )

    print(
        "=" * 70
    )

    print(
        f"Source: {OWNER}"
    )

    print(
        "Playlist discovery: "
        "GitHub repository tree"
    )

    print(
        "Category source: "
        "ORIGINAL M3U group-title"
    )

    print(
        "Group depth: "
        "FIRST LEVEL ONLY"
    )

    print()

    print(
        "SPECIAL CATEGORY SOURCES:"
    )

    print(
        "  App M3U     -> App M3U"
    )

    print(
        "  My-Streams  -> My-Streams"
    )

    print(
        "  Buddy Live  -> Buddy Live"
    )

    print()

    print(
        "SOURCE PRIORITY:"
    )

    print(
        "  1. App M3U"
    )

    print(
        "  2. My-Streams"
    )

    print(
        "  3. Buddy Live"
    )

    print(
        "  4. All other sources"
    )

    print()

    print(
        "Region guessing: DISABLED"
    )

    print(
        "Source guessing: DISABLED"
    )

    print(
        "Channel-name guessing: "
        "DISABLED"
    )

    print(
        "Duplicate resolution: "
        "CHANNEL IDENTITY + SOURCE PRIORITY"
    )

    print(
        "Health checking: "
        f"{'ENABLED' if HEALTH_CHECK_ENABLED else 'DISABLED'}"
    )

    print()

    print(
        "GitHub API authentication: "
        "ENABLED"
    )

    print()

    # ========================================================
    # DISCOVER REPOSITORIES
    # ========================================================

    try:

        repositories = (
            discover_repositories()
        )

    except Exception as exc:

        print()
        print(
            "ERROR: Could not discover "
            "repositories."
        )

        print(
            str(exc)
        )

        sys.exit(1)

    print(
        f"Repositories discovered: "
        f"{len(repositories)}"
    )

    print()

    # ========================================================
    # STORAGE
    # ========================================================

    all_entries = []

    source_stats = defaultdict(
        lambda: {
            "entries": 0,
            "files_ok": 0,
            "files_found": 0,
        }
    )

    empty_playlists = []

    failed_playlists = []

    # ========================================================
    # PROCESS REPOSITORIES
    # ========================================================

    for repo_name in repositories:

        print(
            f"=== {repo_name} ==="
        )

        try:

            playlist_files = (
                discover_playlist_files(
                    repo_name
                )
            )

        except Exception as exc:

            print(
                "  [ERROR] Cannot read "
                "repository tree: "
                f"{exc}"
            )

            print()

            continue

        print(
            f"Found "
            f"{len(playlist_files)} "
            f"playlist files"
        )

        source_stats[
            repo_name
        ]["files_found"] = (
            len(playlist_files)
        )

        for playlist_path in playlist_files:

            try:

                source_url = raw_url(
                    repo_name,
                    playlist_path
                )

                text = http_get_text(
                    source_url
                )

                entries = parse_m3u(
                    text
                )

                if not entries:

                    print(
                        f"  [EMPTY] "
                        f"{playlist_path}"
                    )

                    empty_playlists.append(
                        f"{repo_name}/"
                        f"{playlist_path}"
                    )

                    continue

                print(
                    f"  [OK] "
                    f"{playlist_path}: "
                    f"{len(entries)} entries"
                )

                source_stats[
                    repo_name
                ]["files_ok"] += 1

                source_stats[
                    repo_name
                ]["entries"] += len(
                    entries
                )

                for entry in entries:

                    if repo_name in SPECIAL_GROUPS:

                        final_group = (
                            SPECIAL_GROUPS[
                                repo_name
                            ]
                        )

                    else:

                        original_group = (
                            entry["attrs"].get(
                                "group-title",
                                ""
                            )
                        )

                        final_group = (
                            get_final_group(
                                repo_name,
                                original_group
                            )
                        )

                    entry["repo"] = (
                        repo_name
                    )

                    entry["playlist_path"] = (
                        playlist_path
                    )

                    entry["final_group"] = (
                        final_group
                    )

                    entry["source_priority"] = (
                        get_source_priority(
                            repo_name
                        )
                    )

                    all_entries.append(
                        entry
                    )

            except Exception as exc:

                print(
                    f"  [SKIP] "
                    f"{playlist_path}: "
                    f"{exc}"
                )

                failed_playlists.append(
                    f"{repo_name}/"
                    f"{playlist_path}"
                )

        print()

    # ========================================================
    # RAW URL DUPLICATE COUNT
    # ========================================================

    print(
        "=" * 70
    )

    print(
        "RAW URL ANALYSIS"
    )

    print(
        "=" * 70
    )

    raw_seen = set()

    raw_duplicates = 0

    for entry in all_entries:

        url = entry[
            "url"
        ].strip()

        if not url:
            continue

        if url in raw_seen:

            raw_duplicates += 1

        else:

            raw_seen.add(
                url
            )

    print(
        f"Entries collected: "
        f"{len(all_entries)}"
    )

    print(
        f"Unique URLs before selection: "
        f"{len(raw_seen)}"
    )

    print(
        f"Exact duplicate URLs: "
        f"{raw_duplicates}"
    )

    # ========================================================
    # CHANNEL CANDIDATES
    # ========================================================

    print()

    print(
        "Building channel candidates..."
    )

    candidate_groups = (
        choose_preferred_entries(
            all_entries
        )
    )

    print(
        f"Channel identity groups: "
        f"{len(candidate_groups)}"
    )

    # ========================================================
    # HEALTH CHECK
    # ========================================================

    # --------------------------------------------------------
    # Important:
    #
    # We test ALL unique candidate URLs.
    #
    # We do NOT simply test the first priority source.
    #
    # This allows:
    #
    # App M3U       DEAD
    # My-Streams    HEALTHY
    #
    # to select My-Streams.
    # --------------------------------------------------------

    candidate_entries = []

    seen_candidate_urls = set()

    for identity, candidates in candidate_groups:

        for entry in candidates:

            url = entry[
                "url"
            ].strip()

            if not url:
                continue

            if url in seen_candidate_urls:
                continue

            seen_candidate_urls.add(
                url
            )

            candidate_entries.append(
                entry
            )

    if HEALTH_CHECK_ENABLED:

        (
            healthy_entries,
            failed_count,
            tested_count,
            health_results
        ) = health_check_entries(
            candidate_entries
        )

    else:

        health_results = {}

        for entry in candidate_entries:

            health_results[
                entry["url"].strip()
            ] = (
                True,
                "NOT_CHECKED"
            )

        failed_count = 0

        tested_count = 0

    # ========================================================
    # SELECT BEST HEALTHY URL
    # ========================================================

    print()

    print(
        "=" * 70
    )

    print(
        "SELECTING BEST STREAMS"
    )

    print(
        "=" * 70
    )

    (
        unique_entries,
        no_healthy_candidate,
        priority_replacements,
        selected_source_counter
    ) = select_best_entries(
        candidate_groups,
        health_results
    )

    print(
        f"Final channels: "
        f"{len(unique_entries)}"
    )

    print(
        f"Channels with no healthy URL: "
        f"{no_healthy_candidate}"
    )

    print(
        f"Priority fallbacks caused by "
        f"unhealthy higher source: "
        f"{priority_replacements}"
    )

    # ========================================================
    # SAFETY CHECK SPECIAL CATEGORIES
    # ========================================================

    category_counter = Counter()

    for entry in unique_entries:

        category_counter[
            entry["final_group"]
        ] += 1

    forbidden_prefixes = (
        "App M3U |",
        "Buddy Live |",
        "My-Streams |",
    )

    bad_special_categories = []

    for category in category_counter:

        for prefix in forbidden_prefixes:

            if category.startswith(
                prefix
            ):

                bad_special_categories.append(
                    category
                )

    if bad_special_categories:

        print()

        print(
            "ERROR: Special-source "
            "subcategories detected!"
        )

        for category in sorted(
            set(
                bad_special_categories
            )
        ):

            print(
                f"  {category}"
            )

        print()

        sys.exit(
            "BUILD STOPPED: "
            "special category validation failed"
        )

    # ========================================================
    # WRITE OUTPUT
    # ========================================================

    print()

    print(
        "Writing output playlist..."
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as output:

        output.write(
            "#EXTM3U\n"
        )

        for entry in unique_entries:

            output.write(
                rebuild_extinf(
                    entry,
                    entry["final_group"]
                )
                + "\n"
            )

            output.write(
                entry["url"].strip()
                + "\n"
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()

    print(
        "=" * 70
    )

    print(
        "BUILD COMPLETE"
    )

    print(
        "=" * 70
    )

    print(
        f"Repositories discovered: "
        f"{len(repositories)}"
    )

    print(
        f"Playlist entries read: "
        f"{len(all_entries)}"
    )

    print(
        f"Unique channel identities: "
        f"{len(candidate_groups)}"
    )

    print(
        f"Unique candidate URLs tested: "
        f"{tested_count}"
    )

    print(
        f"Healthy URLs: "
        f"{tested_count - failed_count}"
    )

    print(
        f"Failed URLs: "
        f"{failed_count}"
    )

    print(
        f"Final playable channels: "
        f"{len(unique_entries)}"
    )

    print(
        f"Channels without healthy URL: "
        f"{no_healthy_candidate}"
    )

    print(
        f"Priority fallbacks: "
        f"{priority_replacements}"
    )

    print(
        f"Categories: "
        f"{len(category_counter)}"
    )

    print(
        f"Output: "
        f"{OUTPUT_FILE}"
    )

    # ========================================================
    # SELECTED SOURCE SUMMARY
    # ========================================================

    print()

    print(
        "SELECTED SOURCE SUMMARY"
    )

    print(
        "-" * 70
    )

    for repo_name, count in sorted(
        selected_source_counter.items(),
        key=lambda x: (
            get_source_priority(x[0]),
            x[0].lower()
        )
    ):

        source_name = SOURCE_NAME_MAP.get(
            repo_name,
            repo_name
        )

        print(
            f"{source_name}: "
            f"{count}"
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

    for category, count in sorted(
        category_counter.items(),
        key=lambda x: x[0].lower()
    ):

        print(
            f"{category}: {count}"
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

    for repo_name in repositories:

        stats = source_stats.get(
            repo_name
        )

        if not stats:
            continue

        if stats["files_found"] == 0:
            continue

        print(
            f"{repo_name}: "
            f"{stats['entries']} entries "
            f"from "
            f"{stats['files_ok']}/"
            f"{stats['files_found']} files"
        )

    # ========================================================
    # EMPTY PLAYLISTS
    # ========================================================

    if empty_playlists:

        print()

        print(
            f"EMPTY PLAYLISTS: "
            f"{len(empty_playlists)}"
        )

        for playlist in empty_playlists:

            print(
                f"  {playlist}"
            )

    # ========================================================
    # FAILED PLAYLISTS
    # ========================================================

    if failed_playlists:

        print()

        print(
            f"FAILED PLAYLISTS: "
            f"{len(failed_playlists)}"
        )

        for playlist in failed_playlists:

            print(
                f"  {playlist}"
            )

    print()

    print(
        "Done."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    build()
