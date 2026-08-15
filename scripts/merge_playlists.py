import re
import urllib.request
from collections import defaultdict

OUTPUT = "fast-all-regions.m3u"

HEADERS = {
    "User-Agent": "Mozilla/5.0 FAST-All-Regions"
}

# ============================================================
# CANONICAL PLAYLISTS FROM BUDDYCHEW
# ============================================================

SOURCES = [
    (
        "Pluto TV",
        "https://raw.githubusercontent.com/BuddyChewChew/pluto/main/pluto_all.m3u",
    ),

    (
        "Plex",
        "https://raw.githubusercontent.com/BuddyChewChew/plex/main/playlists/plex_all.m3u",
    ),

    (
        "Samsung TV Plus",
        "https://raw.githubusercontent.com/BuddyChewChew/samsungtvplus/main/output/samsung_tvplus.m3u",
    ),

    (
        "Roku",
        "https://raw.githubusercontent.com/BuddyChewChew/roku-playlist-generator/main/roku.m3u",
    ),

    (
        "Tubi",
        "https://raw.githubusercontent.com/BuddyChewChew/tubi-scraper/main/tubi_playlist.m3u",
    ),

    (
        "Xumo",
        "https://raw.githubusercontent.com/BuddyChewChew/xumo-playlist-generator/main/playlists/xumo_playlist.m3u",
    ),

    (
        "Local Now",
        "https://www.apsattv.com/localnow.m3u",
    ),

    (
        "LG Channels",
        "https://raw.githubusercontent.com/BuddyChewChew/lg-playlist-generator/main/lg_channels_us.m3u",
    ),

    (
        "TCL TV+",
        "https://raw.githubusercontent.com/BuddyChewChew/tcl-playlist-generator/main/tcl.m3u8",
    ),

    (
        "DistroTV",
        "https://raw.githubusercontent.com/BuddyChewChew/distro-playlist-generator/main/playlists/distrotv_all.m3u",
    ),

    (
        "Rakuten TV",
        "https://raw.githubusercontent.com/BuddyChewChew/RakutenTV/main/playlist.m3u",
    ),

    (
        "Airy TV",
        "https://raw.githubusercontent.com/BuddyChewChew/airy-playlist-generator/main/airy_channels.m3u",
    ),
]


# ============================================================
# COUNTRY / REGION DETECTION
# ============================================================

COUNTRY_MAP = {
    "us": "US",
    "usa": "US",
    "united states": "US",
    "united-states": "US",
    "america": "US",

    "uk": "UK",
    "gb": "UK",
    "great britain": "UK",
    "united kingdom": "UK",
    "united-kingdom": "UK",
    "england": "UK",

    "ca": "Canada",
    "canada": "Canada",

    "au": "Australia",
    "australia": "Australia",

    "nz": "New Zealand",
    "new zealand": "New Zealand",

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

    "ie": "Ireland",
    "ireland": "Ireland",

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

    "at": "Austria",
    "austria": "Austria",

    "ch": "Switzerland",
    "switzerland": "Switzerland",

    "tr": "Turkey",
    "turkey": "Turkey",

    "za": "South Africa",
    "south africa": "South Africa",
}


def normalize_country(value):
    value = value.strip().lower()

    value = re.sub(
        r"[_-]+",
        " ",
        value
    )

    return COUNTRY_MAP.get(value, "")


def get_attribute(extinf, attribute):
    pattern = (
        rf'{re.escape(attribute)}="([^"]*)"'
    )

    match = re.search(
        pattern,
        extinf,
        re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return ""


def detect_country(extinf, url, service):

    # --------------------------------------------------------
    # 1. Explicit country metadata
    # --------------------------------------------------------

    for attribute in (
        "country",
        "region",
        "tvg-country",
        "country-code",
        "iso_country",
    ):

        value = get_attribute(
            extinf,
            attribute
        )

        country = normalize_country(value)

        if country:
            return country

    # --------------------------------------------------------
    # 2. Existing group-title
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 3. tvg-id ISO prefix
    # --------------------------------------------------------

    tvgid = get_attribute(
        extinf,
        "tvg-id"
    )

    if tvgid:

        match = re.match(
            r"^([A-Za-z]{2})",
            tvgid
        )

        if match:

            country = normalize_country(
                match.group(1)
            )

            if country:
                return country

    # --------------------------------------------------------
    # 4. Service defaults
    # --------------------------------------------------------

    defaults = {
        "LG Channels": "US",
        "TCL TV+": "US",
        "Xumo": "US",
        "Local Now": "US",
        "Rakuten TV": "UK",
        "Airy TV": "US",
        "Tubi": "US",
    }

    return defaults.get(
        service,
        "Global"
    )


# ============================================================
# GENRE
# ============================================================

def get_genre(extinf):

    group = get_attribute(
        extinf,
        "group-title"
    )

    if not group:
        return "General"

    pieces = [
        p.strip()
        for p in re.split(
            r"\s*[|>]\s*",
            group
        )
        if p.strip()
    ]

    # Remove country if it is already
    # present at the beginning.

    if pieces:

        if normalize_country(
            pieces[0]
        ):

            pieces = pieces[1:]

    if not pieces:
        return "General"

    return " | ".join(pieces)


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


# ============================================================
# FETCH
# ============================================================

def fetch(url):

    request = urllib.request.Request(
        url,
        headers=HEADERS
    )

    with urllib.request.urlopen(
        request,
        timeout=90
    ) as response:

        return response.read().decode(
            "utf-8",
            errors="replace"
        )


# ============================================================
# REPLACE GROUP TITLE
# ============================================================

def replace_group(
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


# ============================================================
# CHANNEL NAME
# ============================================================

def channel_name(extinf):

    if "," in extinf:

        return (
            extinf
            .split(",", 1)[1]
            .strip()
            .lower()
        )

    return ""


# ============================================================
# MAIN
# ============================================================

def main():

    all_entries = []

    failed_sources = []

    source_counts = defaultdict(int)

    print()
    print("=" * 70)
    print("FAST ALL REGIONS")
    print("=" * 70)

    # --------------------------------------------------------
    # Download every source
    # --------------------------------------------------------

    for service, url in SOURCES:

        print()
        print(
            f"[SOURCE] {service}"
        )

        try:

            text = fetch(url)

            entries = parse_m3u(
                text
            )

            print(
                f"Channels found: "
                f"{len(entries)}"
            )

            # IMPORTANT:
            #
            # We NEVER delete channels because
            # their stream is currently offline.
            #
            # We only remove exact duplicate URLs later.

            for extinf, stream in entries:

                country = detect_country(
                    extinf,
                    stream,
                    service
                )

                genre = get_genre(
                    extinf
                )

                group = (
                    f"{service} | "
                    f"{country} | "
                    f"{genre}"
                )

                new_extinf = replace_group(
                    extinf,
                    group
                )

                all_entries.append(
                    {
                        "extinf": new_extinf,
                        "url": stream.strip(),
                        "service": service,
                        "country": country,
                        "genre": genre,
                    }
                )

                source_counts[
                    service
                ] += 1

        except Exception as error:

            print(
                f"[WARNING] "
                f"{service} failed:"
            )

            print(error)

            failed_sources.append(
                (
                    service,
                    url,
                    str(error)
                )
            )

    # --------------------------------------------------------
    # EXACT STREAM DEDUPLICATION
    # --------------------------------------------------------

    print()
    print(
        "Removing exact duplicate "
        "stream URLs..."
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

        if not url_key:
            continue

        if url_key in seen_urls:

            duplicate_count += 1

            continue

        seen_urls.add(
            url_key
        )

        unique_entries.append(
            entry
        )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    unique_entries.sort(
        key=lambda item: (
            item["service"].lower(),
            item["country"].lower(),
            item["genre"].lower(),
            channel_name(
                item["extinf"]
            ),
        )
    )

    # --------------------------------------------------------
    # WRITE OUTPUT
    # --------------------------------------------------------

    with open(
        OUTPUT,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as output:

        output.write(
            "#EXTM3U\n"
        )

        for entry in unique_entries:

            output.write(
                entry["extinf"]
                + "\n"
            )

            output.write(
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
        f"Total collected: "
        f"{len(all_entries)}"
    )

    print(
        f"Unique channels: "
        f"{len(unique_entries)}"
    )

    print(
        f"Exact duplicates removed: "
        f"{duplicate_count}"
    )

    print()

    print(
        "Channels by source:"
    )

    for service, count in (
        source_counts.items()
    ):

        print(
            f"  {service}: {count}"
        )

    # --------------------------------------------------------
    # FAILED SOURCES
    # --------------------------------------------------------

    if failed_sources:

        print()
        print(
            "WARNING - SOURCES "
            "THAT COULD NOT BE LOADED:"
        )

        for (
            service,
            url,
            error
        ) in failed_sources:

            print(
                f"- {service}"
            )

            print(
                f"  {url}"
            )

            print(
                f"  {error}"
            )

        print()
        print(
            "IMPORTANT: existing "
            "channels from failed sources "
            "are NOT deleted by this script."
        )


if __name__ == "__main__":

    main()
