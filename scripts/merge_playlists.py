import json
import re
import urllib.request
from urllib.parse import urlsplit

OWNER = "BuddyChewChew"

REPOS = [
    "app-m3u-generator",
    "pluto",
    "plex",
    "plex-alt-fast-channels",
    "samsungtvplus",
    "roku-playlist-generator",
    "tubi-scraper",
    "xumo-playlist-generator",
    "localnow-playlist-generator",
    "lg-playlist-generator",
    "lg-playlist-generator2",
    "tcl-playlist-generator",
    "distro-playlist-generator",
    "RakutenTV",
    "airy-playlist-generator",
]

OUTPUT = "fast-all-regions.m3u"

HEADERS = {
    "User-Agent": "fast-all-regions-builder",
    "Accept": "application/vnd.github+json",
}

def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

def github_json(url):
    return json.loads(get(url).decode("utf-8"))

def get_tree(repo):
    url = f"https://api.github.com/repos/{OWNER}/{repo}/git/trees/main?recursive=1"
    try:
        data = github_json(url)
        return data.get("tree", [])
    except Exception as e:
        print(f"[WARN] {repo}: {e}")
        return []

def normalize_url(url):
    url = url.strip()
    if not url:
        return ""

    # Remove accidental quotes
    url = url.strip('"').strip("'")

    # Normalize whitespace
    url = re.sub(r"\s+", "", url)

    return url

def parse_m3u(text, source):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

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
                entries.append((current_info, url, source))

            current_info = None

    return entries

def download_playlist(url, source):
    try:
        raw = get(url)
        text = raw.decode("utf-8", errors="replace")

        if "#EXTINF:" not in text:
            return []

        return parse_m3u(text, source)

    except Exception as e:
        print(f"[WARN] Failed {url}: {e}")
        return []

def clean_extinf(extinf, source):
    # Preserve metadata but add source to group if useful.
    if 'group-title="' in extinf:
        extinf = re.sub(
            r'group-title="([^"]*)"',
            lambda m: f'group-title="{m.group(1)}"',
            extinf,
            count=1,
        )

    return extinf

def main():
    all_entries = []

    for repo in REPOS:
        print(f"\n=== {repo} ===")

        tree = get_tree(repo)

        m3u_files = [
            x["path"]
            for x in tree
            if x.get("type") == "blob"
            and x["path"].lower().endswith((".m3u", ".m3u8"))
        ]

        print(f"Found {len(m3u_files)} playlist files")

        for path in m3u_files:
            # Avoid EPG/XML or obvious non-live files.
            lower = path.lower()

            if "epg" in lower:
                continue

            url = (
                f"https://raw.githubusercontent.com/"
                f"{OWNER}/{repo}/main/{path}"
            )

            entries = download_playlist(url, f"{repo}/{path}")
            print(f"  {path}: {len(entries)} channels")

            all_entries.extend(entries)

    # Deduplicate by actual stream URL.
    # This removes the same stream appearing in multiple regions/services.
    seen_urls = set()
    unique = []

    for extinf, url, source in all_entries:
        key = url.lower()

        if key in seen_urls:
            continue

        seen_urls.add(key)
        unique.append((extinf, url, source))

    # Stable ordering: source first, then channel name.
    def channel_name(extinf):
        if "," in extinf:
            return extinf.split(",", 1)[1].strip().lower()
        return extinf.lower()

    unique.sort(key=lambda x: (x[2].lower(), channel_name(x[0])))

    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("#EXTM3U\n")

        for extinf, url, source in unique:
            f.write(extinf + "\n")
            f.write(url + "\n")

    print("\n======================================")
    print(f"Total discovered entries : {len(all_entries)}")
    print(f"Unique streams            : {len(unique)}")
    print(f"Removed duplicates        : {len(all_entries) - len(unique)}")
    print(f"Output                    : {OUTPUT}")
    print("======================================")

if __name__ == "__main__":
    main()
