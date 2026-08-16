#!/usr/bin/env python3

import gzip
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict


# ============================================================
# CONFIG
# ============================================================

M3U_FILE = "fast-all-regions.m3u"
REPORT_FILE = "epg-audit.txt"

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; FAST-EPG-Audit/1.0)"
)


# ============================================================
# EPG SOURCES
# ============================================================

EPG_SOURCES = {

    "Samsung TV Plus": [
        "https://raw.githubusercontent.com/"
        "BuddyChewChew/samsungtvplus/main/"
        "output/samsung_tvplus.xml",
    ],

    "LG TV": [
        "https://raw.githubusercontent.com/"
        "BuddyChewChew/lg-playlist-generator/main/"
        "lg_channels_us.xml",
    ],

    "TCL": [
        "https://raw.githubusercontent.com/"
        "BuddyChewChew/tcl-playlist-generator/main/"
        "tcl_epg.xml",
    ],

    "Rakuten TV": [
        "https://raw.githubusercontent.com/"
        "BuddyChewChew/RakutenTV/main/"
        "epg.xml",
    ],

    "Airy TV": [
        "https://raw.githubusercontent.com/"
        "BuddyChewChew/airy-playlist-generator/main/"
        "airy_channels.xml",
    ],

    "Pluto TV": [
        "https://raw.githubusercontent.com/"
        "matthuisman/i.mjh.nz/refs/heads/master/"
        "PlutoTV/all.xml.gz",

        "https://raw.githubusercontent.com/"
        "matthuisman/i.mjh.nz/refs/heads/master/"
        "PlutoTV/all.xml",
    ],

    "Plex TV": [
        "https://raw.githubusercontent.com/"
        "matthuisman/i.mjh.nz/refs/heads/master/"
        "Plex/all.xml.gz",
    ],

    "Xumo": [
        "https://raw.githubusercontent.com/"
        "BuddyChewChew/xumo-playlist-generator/main/"
        "xumo_epg.xml.gz",
    ],

    "Tubi": [
        "https://raw.githubusercontent.com/"
        "BuddyChewChew/tubi-scraper/main/"
        "tubi_epg.xml",
    ],
}


# ============================================================
# HTTP
# ============================================================

def http_get(url, timeout=120):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:

        return response.read()


# ============================================================
# M3U PARSER
# ============================================================

ATTRIBUTE_PATTERN = re.compile(
    r'([\w:-]+)="([^"]*)"'
)


def parse_extinf(line):

    comma = line.find(",")

    if comma >= 0:

        metadata = line[:comma]

    else:

        metadata = line

    attributes = {}

    for match in ATTRIBUTE_PATTERN.finditer(
        metadata
    ):

        attributes[
            match.group(1)
        ] = match.group(2)

    return attributes


def load_m3u():

    print(
        f"Reading M3U: {M3U_FILE}"
    )

    source_channels = defaultdict(set)

    current_attrs = None

    with open(
        M3U_FILE,
        "r",
        encoding="utf-8-sig",
        errors="replace",
    ) as file:

        for raw_line in file:

            line = raw_line.strip()

            if not line:
                continue

            if line.startswith("#EXTINF"):

                current_attrs = parse_extinf(
                    line
                )

                continue

            if line.startswith("#"):
                continue

            if current_attrs is None:
                continue

            tvg_id = (
                current_attrs
                .get("tvg-id", "")
                .strip()
            )

            group = (
                current_attrs
                .get("group-title", "")
                .strip()
            )

            if tvg_id:

                source = (
                    group.split(
                        " | ",
                        1
                    )[0]
                )

                source_channels[
                    source
                ].add(tvg_id)

            current_attrs = None

    return source_channels


# ============================================================
# XMLTV
# ============================================================

def parse_xmltv(data):

    if data[:2] == b"\x1f\x8b":

        data = gzip.decompress(data)

    root = ET.fromstring(data)

    channel_ids = set()

    for channel in root.findall(
        ".//channel"
    ):

        channel_id = (
            channel.get("id")
        )

        if channel_id:

            channel_ids.add(
                channel_id.strip()
            )

    return channel_ids


# ============================================================
# SOURCE MATCH
# ============================================================

def audit_source(
    source_name,
    m3u_ids,
):

    result = {
        "source": source_name,
        "m3u": len(m3u_ids),
        "epg": 0,
        "matched": 0,
        "missing": len(m3u_ids),
        "rate": 0.0,
        "epg_url": "",
        "error": "",
    }

    urls = EPG_SOURCES.get(
        source_name,
        []
    )

    if not urls:

        result["error"] = (
            "No EPG source configured"
        )

        return result

    errors = []

    for url in urls:

        try:

            print(
                f"  Downloading EPG: "
                f"{source_name}"
            )

            data = http_get(url)

            epg_ids = parse_xmltv(
                data
            )

            matched_ids = (
                m3u_ids & epg_ids
            )

            result["epg"] = len(
                epg_ids
            )

            result["matched"] = len(
                matched_ids
            )

            result["missing"] = (
                len(m3u_ids)
                - len(matched_ids)
            )

            if m3u_ids:

                result["rate"] = (
                    len(matched_ids)
                    / len(m3u_ids)
                    * 100
                )

            result["epg_url"] = url
            result["error"] = ""

            return result

        except Exception as exc:

            errors.append(
                f"{url} -> {exc}"
            )

    result["error"] = (
        "All EPG sources failed: "
        + " | ".join(errors)
    )

    return result


# ============================================================
# REPORT
# ============================================================

def write_report(results):

    with open(
        REPORT_FILE,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as report:

        report.write(
            "FAST ALL REGIONS - EPG AUDIT\n"
        )

        report.write(
            "=" * 70
            + "\n\n"
        )

        total_m3u = 0
        total_matched = 0

        for result in results:

            report.write(
                f"{result['source']}\n"
            )

            report.write(
                "-" * 70
                + "\n"
            )

            report.write(
                f"M3U channels : "
                f"{result['m3u']}\n"
            )

            report.write(
                f"EPG channels : "
                f"{result['epg']}\n"
            )

            report.write(
                f"MATCH        : "
                f"{result['matched']}\n"
            )

            report.write(
                f"NO MATCH     : "
                f"{result['missing']}\n"
            )

            report.write(
                f"MATCH RATE   : "
                f"{result['rate']:.2f}%\n"
            )

            if result["epg_url"]:

                report.write(
                    f"EPG URL      : "
                    f"{result['epg_url']}\n"
                )

            if result["error"]:

                report.write(
                    f"ERROR        : "
                    f"{result['error']}\n"
                )

            report.write("\n")

            total_m3u += result["m3u"]
            total_matched += result["matched"]

        report.write(
            "=" * 70
            + "\n"
        )

        report.write(
            "TOTAL\n"
        )

        report.write(
            "-" * 70
            + "\n"
        )

        report.write(
            f"M3U channels : "
            f"{total_m3u}\n"
        )

        report.write(
            f"MATCH        : "
            f"{total_matched}\n"
        )

        if total_m3u:

            total_rate = (
                total_matched
                / total_m3u
                * 100
            )

        else:

            total_rate = 0

        report.write(
            f"MATCH RATE   : "
            f"{total_rate:.2f}%\n"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("FAST ALL REGIONS - EPG AUDIT")
    print("=" * 70)

    try:

        source_channels = load_m3u()

    except Exception as exc:

        print(
            f"ERROR reading M3U: {exc}"
        )

        sys.exit(1)

    print()

    print(
        f"Sources detected: "
        f"{len(source_channels)}"
    )

    print()

    results = []

    for source_name in sorted(
        source_channels,
        key=str.lower,
    ):

        print(
            f"=== {source_name} ==="
        )

        result = audit_source(
            source_name,
            source_channels[
                source_name
            ],
        )

        results.append(
            result
        )

        print(
            f"  M3U: "
            f"{result['m3u']}"
        )

        print(
            f"  EPG: "
            f"{result['epg']}"
        )

        print(
            f"  MATCH: "
            f"{result['matched']}"
        )

        print(
            f"  NO MATCH: "
            f"{result['missing']}"
        )

        print(
            f"  RATE: "
            f"{result['rate']:.2f}%"
        )

        if result["error"]:

            print(
                f"  ERROR: "
                f"{result['error']}"
            )

        print()

    write_report(
        results
    )

    print("=" * 70)

    print(
        "Audit complete."
    )

    print(
        f"Report: {REPORT_FILE}"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()
