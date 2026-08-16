import re
import requests
from pathlib import Path
import xml.etree.ElementTree as ET

M3U_URL = "https://raw.githubusercontent.com/Faridcj/fast-all-regions/main/fast-all-regions.m3u"

# لینک EPG آرتیفکت/فایل خروجی‌ات را اینجا بگذار
EPG_URL = "YOUR_EPG_URL_HERE"

OUTPUT = "fast-all-regions-epg.m3u"


def download(url):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.text


def parse_epg(epg_text):
    root = ET.fromstring(epg_text)

    epg = {}

    for channel in root.findall("channel"):
        cid = channel.get("id")
        if not cid:
            continue

        display = channel.find("display-name")
        name = display.text.strip() if display is not None and display.text else ""

        epg[cid] = {
            "id": cid,
            "name": name
        }

    return epg


def normalize(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def find_epg(channel_name, epg):
    target = normalize(channel_name)

    if not target:
        return None

    # اول تطبیق دقیق
    for cid, data in epg.items():
        if normalize(data["name"]) == target:
            return cid

    # بعد تطبیق شامل‌شدن
    for cid, data in epg.items():
        epg_name = normalize(data["name"])

        if target in epg_name or epg_name in target:
            return cid

    return None


def merge(m3u, epg):
    lines = m3u.splitlines()

    output = []
    matched = 0
    total = 0

    for i, line in enumerate(lines):

        if line.startswith("#EXTINF"):
            total += 1

            # اسم کانال
            channel_name = line.split(",", 1)[1].strip() if "," in line else ""

            epg_id = find_epg(channel_name, epg)

            if epg_id:
                # اگر tvg-id قبلی وجود دارد، جایگزینش کن
                if 'tvg-id="' in line:
                    line = re.sub(
                        r'tvg-id="[^"]*"',
                        f'tvg-id="{epg_id}"',
                        line
                    )
                else:
                    line = line.replace(
                        "#EXTINF:",
                        f'#EXTINF: tvg-id="{epg_id}"',
                        1
                    )

                matched += 1

            output.append(line)

        else:
            output.append(line)

    print(f"Channels: {total}")
    print(f"EPG matched: {matched}")
    print(f"EPG unmatched: {total - matched}")

    return "\n".join(output) + "\n"


def main():
    print("Downloading M3U...")
    m3u = download(M3U_URL)

    print("Downloading EPG...")
    epg_text = download(EPG_URL)

    print("Parsing EPG...")
    epg = parse_epg(epg_text)

    print(f"EPG channels: {len(epg)}")

    print("Merging...")
    result = merge(m3u, epg)

    Path(OUTPUT).write_text(result, encoding="utf-8")

    print(f"Done: {OUTPUT}")


if __name__ == "__main__":
    main()
