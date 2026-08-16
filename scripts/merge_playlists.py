#!/usr/bin/env python3

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict


# ============================================================
# CONFIG
# ============================================================

OWNER = "BuddyChewChew"
OUTPUT_FILE = "fast-all-regions.m3u"

GITHUB_API = "https://api.github.com"

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; FAST-All-Regions-Builder/1.0)"
)

PLAYLIST_EXTENSIONS = (
    ".m3u",
    ".m3u8",
)


# ============================================================
# ABSOLUTE CATEGORY OVERRIDES
#
# These repositories are NEVER allowed to use their original
# M3U group-title.
#
# Every channel from these sources goes into ONE category only.
# ============================================================

SOURCE_CATEGORY_OVERRIDES = {

    "app-m3u-generator":
        "App M3U",

    "buddylive":
        "Buddy Live",

    "buddylive-combined":
        "Buddy Live",

    "buddylive_v2":
        "Buddy Live",

    "My-Streams":
        "My-Streams",
}


# ============================================================
# HTTP HELPERS
# ============================================================

def http_get(url, timeout=45, retries=3):

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
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
            TimeoutError
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
                    response.read().decode("utf-8")
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
                    min(10, 2 ** attempt)
                )

                continue

            raise

        except (
            urllib.error.URLError,
            TimeoutError
        ) as exc:

            last_error = exc

            if attempt < retries - 1:

                time.sleep(
                    2 ** attempt
                )

                continue

            raise

    raise last_error


# ============================================================
# SOURCE NAME NORMALIZATION
# ============================================================

def normalize_source_name(repo_name):

    mapping = {

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

        "lg-playlist-generator":
            "LG",

        "lg-playlist-generator2":
            "LG",

        "My-Streams":
            "My-Streams",

        "nz":
            "NZ",

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

        "tcl-playlist-generator":
            "TCL",

        "tubi-scraper":
            "Tubi",

        "xumo-playlist-generator":
            "Xumo",
    }

    return mapping.get(
        repo_name,
        repo_name
    )


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
# FINAL CATEGORY
# ============================================================

def get_final_group(
    repo_name,
    original_group
):

    # ========================================================
    # ABSOLUTE OVERRIDE
    #
    # IMPORTANT:
    #
    # original_group is NOT inspected for these sources.
    #
    # Therefore:
    #
    # APP M3U UNITED STATES CHANNEL-ID =...
    # APP M3U SPORTS CHANNEL-ID =...
    # APP M3U NEWS CHANNEL-ID =...
    #
    # can NEVER create categories.
    # ========================================================

    if repo_name in SOURCE_CATEGORY_OVERRIDES:

        return SOURCE_CATEGORY_OVERRIDES[
            repo_name
        ]

    # ========================================================
    # ALL OTHER SOURCES
    #
    # Use source name + first level of original group.
    # ========================================================

    source = normalize_source_name(
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
    r'([\w-]+)="([^"]*)"'
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

    return attributes, channel_name


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

        if line.startswith("#
