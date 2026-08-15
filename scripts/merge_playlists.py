import json
import re
import urllib.request
from pathlib import PurePosixPath

OWNER = "BuddyChewChew"

REPOS = [
    "app-m3u-generator",
    "pluto",
    "plex",
    "roku-playlist-generator",
    "samsungtvplus",
    "tubi-scraper",
    "xumo-playlist-generator",
    "localnow-playlist-generator",
    "lg-playlist-generator",
    "tcl-playlist-generator",
    "distro-playlist-generator",
    "RakutenTV",
]

OUTPUT = "fast-all-regions.m3u"

HEADERS = {
    "User-Agent": "fast-all-regions-builder",
    "Accept": "application/vnd.github+json",
}

# Common country / region names
COUNTRIES = {
    "us": "US",
    "usa": "US",
    "united-states": "US",
    "united_states": "US",
    "america": "US",

    "uk": "UK",
    "gb": "UK",
    "england": "UK",
    "united-kingdom": "UK",
    "united_kingdom": "UK",

    "ca": "Canada",
    "canada": "Canada",

    "au": "Australia",
    "australia": "Australia",

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

    "nz": "New Zealand",
    "new-zealand": "New Zealand",
    "new_zealand": "New Zealand",

    "ie": "Ireland",
    "ireland": "Ireland",

    "se": "Sweden",
    "sweden": "Sweden",

    "no": "Norway",
    "norway": "Norway",

    "dk": "Denmark",
    "denmark": "Denmark",

    "nl": "Netherlands",
    "netherlands": "Netherlands",

    "at": "Austria",
    "austria": "Austria",

    "ch": "Switzerland",
    "switzerland": "Switzerland",

    "pl": "Poland",
    "poland": "Poland",

    "tr": "Turkey",
    "turkey": "Turkey",

    "za": "South Africa",
    "south-africa": "South Africa",
    "south_africa": "South Africa",
}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def github_json(url):
    return json.loads(get(url).decode("utf-8"))


def get_tree(repo):
    url = (
        f"https://api.github.com/repos/"
        f"{OWNER}/{repo}/git/trees/main?recursive=1"
    )

    try:
        data = github_json(url)
        return data.get("tree", [])

    except Exception as e:
        print(f"[WARN] {repo}: {e}")
        return []


def detect_country(path):
    """
    Try to identify country/region from playlist path.
    """

    parts = PurePosixPath(path.lower()).parts

    for part in parts:
        cleaned = (
            part.replace(".m3u8", "")
                .replace(".m3u", "")
                .replace(".json", "")
                .replace(".txt", "")
        )

        if cleaned in COUNTRIES:
            return COUNTRIES[cleaned]

        # Match names such as us-east / us_channels
        first = re.split(r"[-_. ]", cleaned)[0]

        if first in COUNTRIES:
            return COUNTRIES[first]

    return "Global"


def extract_group(extinf):
    """
    Extract existing group-title.
    """

    match = re.search(
        r'group-title="([^"]*)"',
        extinf,
        flags=re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return "General"


def replace_group(extinf, group):
    """
    Replace or add group-title.
    """

    if re.search(r'group-title="[^"]*"', extinf, re.IGNORECASE):

        return re.sub(
            r'group-title="[^"]*"',
            f'group-title="{group}"',
            extinf,
            flags=re.IGNORECASE
        )

    # Insert group-title after EXTINF attributes.
    comma = extinf.find(",")

    if comma == -1:
        return extinf

    prefix = extinf[:comma]
    name = extinf[comma:]

    return f'{prefix} group-title="{group}"{name}'


def service_name(repo):
    """
    Convert repository name into a clean service name.
    """

    names = {
        "app-m3u-generator": "FAST Apps",
        "pluto": "Pluto TV",
        "plex": "Plex",
        "roku-playlist-generator": "Roku",
        "samsungtvplus": "Samsung TV Plus",
        "tubi-scraper": "Tubi",
        "xumo-playlist-generator": "Xumo",
        "localnow-playlist-generator": "Local Now",
        "lg-playlist-generator": "LG Channels",
        "tcl-playlist-generator": "TCL TV+",
        "distro-playlist-generator": "Distro",
        "RakutenTV": "Rakuten TV",
    }

    return names.get(repo, repo)


def normalize_url(url):
    return (
        url.strip()
        .strip('"')
        .strip("'")
    )


def parse_m3u(text):
    lines = (
        text.replace("\r\n", "\n")
            .replace("\r", "\n")
            .split("\n")
    )

    entries = []

    current_info = None

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if line.startswith("#EXTINF:"):
            current_info = line

        elif line.startswith("#"):
            continue

        elif current_info:

            url = normalize_url(line)

            if url.startswith(("http://", "https://")):
                entries.append(
                    (current_info, url)
                )

            current_info = None

    return entries


def download_playlist(url):
    try:

        raw = get(url)

        text = raw.decode(
            "utf-8",
            errors="replace"
        )

        if "#EXTINF:" not in text:
            return []

        return parse_m3u(text)

    except Exception as e:

        print(
            f"[WARN] Failed playlist: "
            f"{url} -> {e}"
        )

        return []


def main():

    all_entries = []

    for repo in REPOS:

        print()
        print("=" * 60)
        print(service_name(repo))
        print("=" * 60)

        tree = get_tree(repo)

        playlist_files = [
            item["path"]
            for item in tree
            if item.get("type") == "blob"
            and item["path"].lower().endswith(
                (".m3u", ".m3u8")
            )
        ]

        print(
            f"Playlist files found: "
            f"{len(playlist_files)}"
        )

        for path in playlist_files:

            if "epg" in path.lower():
                continue

            url = (
                f"https://raw.githubusercontent.com/"
                f"{OWNER}/{repo}/main/{path}"
            )

            entries = download_playlist(url)

            print(
                f"{path}: "
                f"{len(entries)} channels"
            )

            country = detect_country(path)
            service = service_name(repo)

            for extinf, stream_url in entries:

                original_group = extract_group(
                    extinf
                )

                # Build hierarchical group:
                #
                # Service | Country | Genre
                #
                # Example:
                # Pluto TV | US | News

                group = (
                    f"{service} | "
                    f"{country} | "
                    f"{original_group}"
                )

                new_extinf = replace_group(
                    extinf,
                    group
                )

                all_entries.append(
                    (
                        new_extinf,
                        stream_url,
                        service,
                        country,
                        original_group,
                    )
                )

    # -------------------------------------------------
    # Remove duplicate streams
    # -------------------------------------------------

    seen = set()
    unique = []

    for entry in all_entries:

        extinf = entry[0]
        url = entry[1]

        key = url.lower()

        if key in seen:
            continue

        seen.add(key)
        unique.append(entry)

    # -------------------------------------------------
    # Sort
    # -------------------------------------------------

    def sort_key(entry):

        extinf, url, service, country, genre = entry

        channel = (
            extinf.split(",", 1)[1]
            if "," in extinf
            else extinf
        )

        return (
            service.lower(),
            country.lower(),
            genre.lower(),
            channel.lower(),
        )

    unique.sort(key=sort_key)

    # -------------------------------------------------
    # Write final M3U
    # -------------------------------------------------

    with open(
        OUTPUT,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as f:

        f.write(
            "#EXTM3U "
            'x-tvg-url=""\n'
        )

        for (
            extinf,
            url,
            service,
            country,
            genre
        ) in unique:

            f.write(extinf + "\n")
            f.write(url + "\n")

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)

    print(
        f"Total collected : "
        f"{len(all_entries)}"
    )

    print(
        f"Unique channels : "
        f"{len(unique)}"
    )

    print(
        f"Duplicates removed : "
        f"{len(all_entries) - len(unique)}"
    )

    print(
        f"Output : {OUTPUT}"
    )


if __name__ == "__main__":
    main()
