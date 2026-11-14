"""Builds hr.xml.gz: Croatian EPG with channel ids matching the IPTV playlist.

Downloads public HR XMLTV sources, matches every playlist channel (channels.json)
to a source channel by normalized name, and writes one XMLTV file where each
channel's id is the playlist's tvg-name (and the tvg-id where it is unambiguous),
so TiviMate links them automatically.
"""
import gzip
import io
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

# Priority order: first source that has programmes for a channel wins.
SOURCES = [
    "https://iptv-epg.org/files/epg-hr.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_HR1.xml.gz",
    "http://www.open-epg.com/files/croatia.xml.gz",
]

# Normalized playlist name -> normalized source name, where names differ.
ALIASES = {
    "cinestar": "cinestar1",
    "cinestarcomedy": "cinestarcomedyandfamily",
    "hrtint": "hrthrtint",
    "investigationdiscoveryxtra": "investigationdiscovery",
    "m1filmgold": "m1gold",
    "marymedjugorje": "mariavisionmedugorje",
    "nickjunior": "nickjrhrvatski",
    "vinkovacka": "plavavinkovacka",
    "yuhbo2": "hbo2",
    "yumini": "mini",
    "yufoxlife": "starlife",
    "foxcrime": "starcrime",
    "foxmovies": "starmovies",
}


def norm(s):
    s = (s or "").lower().replace("&amp;", "&")
    s = re.sub(r"^hr\s*[:\-]\s*", "", s)
    s = re.sub(r"\.hr$", "", s)
    s = s.replace("htv", "hrt").replace("&", " and ").replace("+", " and ")
    s = re.sub(r"\b(fhd|uhd|hd|4k|adria|hr|croatia)\b", " ", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s.replace("tv", "")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 hr-epg"})
    data = urllib.request.urlopen(req, timeout=180).read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return ET.parse(io.BytesIO(data)).getroot()


def main():
    channels = json.load(open("channels.json", encoding="utf-8"))
    index = {}   # norm name -> (source no, channel id)
    progs = {}   # (source no, channel id) -> [programme elements]
    for i, url in enumerate(SOURCES):
        try:
            root = fetch(url)
        except Exception as e:  # one broken source must not break the build
            print(f"WARN {url}: {e}", file=sys.stderr)
            continue
        for p in root.iter("programme"):
            progs.setdefault((i, p.get("channel")), []).append(p)
        for ch in root.iter("channel"):
            key = (i, ch.get("id"))
            if key not in progs:
                continue
            names = [d.text for d in ch.findall("display-name")] + [ch.get("id")]
            for n in names:
                k = norm(n)
                if k and k not in index:
                    index[k] = key

    # Resolve each playlist channel to a source channel.
    resolved = {}
    for c in channels:
        k = norm(c["name"])
        src = index.get(ALIASES.get(k, k)) or index.get(k)
        if src:
            resolved[c["name"]] = src
    # A tvg-id is safe to emit only if every channel using it maps to the same source.
    by_id = {}
    for c in channels:
        if c["tvg_id"].endswith(".hr"):
            by_id.setdefault(c["tvg_id"], set()).add(resolved.get(c["name"]))
    safe_ids = {i: next(iter(s)) for i, s in by_id.items() if len(s) == 1 and None not in s}

    out = ET.Element("tv", {"generator-info-name": "hr-epg"})
    outputs = [(name, src) for name, src in resolved.items()]
    outputs += [(tid, src) for tid, src in safe_ids.items()]
    for oid, _ in outputs:
        ch = ET.SubElement(out, "channel", {"id": oid})
        ET.SubElement(ch, "display-name").text = oid
    for oid, src in outputs:
        for p in progs[src]:
            q = ET.SubElement(out, "programme", dict(p.attrib, channel=oid))
            q.extend(list(p))

    buf = io.BytesIO()
    ET.ElementTree(out).write(buf, encoding="utf-8", xml_declaration=True)
    with gzip.open("hr.xml.gz", "wb", compresslevel=9) as f:
        f.write(buf.getvalue())
    missing = [c["name"] for c in channels if c["name"] not in resolved]
    print(f"Matched {len(resolved)}/{len(channels)} channels, {len(safe_ids)} tvg-ids.")
    print("No EPG for: " + ", ".join(missing))


if __name__ == "__main__":
    main()
