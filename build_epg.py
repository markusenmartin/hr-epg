"""Builds hr.xml.gz: EPG for the watched IPTV groups, with channel ids matching the playlist.

For every channel in channels.json (name, tvg-id, country prefix) the script looks the
channel up by normalized name in public XMLTV sources for that country, then writes one
XMLTV file where each channel's id is the playlist's tvg-id (when unambiguous) or its
tvg-name, so TiviMate links them automatically. Channel logos are included.
"""
import datetime as dt
import difflib
import gzip
import io
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

EPGSHARE = "https://epgshare01.online/epgshare01/epg_ripper_{}1.xml.gz"
IPTVEPG = "https://iptv-epg.org/files/epg-{}.xml.gz"
OPENEPG = "http://www.open-epg.com/files/{}.xml.gz"

# Playlist prefix -> sources in priority order.
SOURCES = {
    "HR": [IPTVEPG.format("hr"), EPGSHARE.format("HR"), OPENEPG.format("croatia")],
    "RS": [IPTVEPG.format("rs"), EPGSHARE.format("RS"), OPENEPG.format("serbia")],
    "BH": [IPTVEPG.format("ba"), EPGSHARE.format("BA"), OPENEPG.format("bosnia")],
    "MN": [IPTVEPG.format("me"), OPENEPG.format("montenegro")],
    "SL": [IPTVEPG.format("si"), OPENEPG.format("slovenia")],
    "DK": [IPTVEPG.format("dk"), EPGSHARE.format("DK"), OPENEPG.format("denmark")],
    "SW": [IPTVEPG.format("se"), EPGSHARE.format("SE"), OPENEPG.format("sweden")],
    "UK": [IPTVEPG.format("gb"), EPGSHARE.format("UK"), OPENEPG.format("unitedkingdom")],
}
# Extra logo folders in github.com/tv-logo/tv-logos (countries/<folder>), per playlist prefix.
EXYU_LOGOS = ["croatia", "serbia", "slovenia", "international", "world-europe"]
LOGO_DIRS = {
    "HR": EXYU_LOGOS, "RS": ["serbia", "croatia", "slovenia", "international", "world-europe"],
    "BH": EXYU_LOGOS, "MN": ["serbia", "croatia", "international", "world-europe"],
    "SL": ["slovenia", "croatia", "serbia", "international", "world-europe"],
    "DK": ["nordic", "international", "world-europe"],
    "SW": ["nordic", "international", "world-europe"],
    "UK": ["united-kingdom", "international", "world-europe"],
}
# Countries whose channels may also be found in each other's sources.
FALLBACK = {cc: ["HR", "RS", "BH", "MN", "SL"] for cc in ["HR", "RS", "BH", "MN", "SL"]}

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

KEEP_PAST = dt.timedelta(days=1)
KEEP_FUTURE = dt.timedelta(days=8)


def norm(s, loose=False):
    """Comparable channel name. loose=True also drops country tags and filler words."""
    s = (s or "").lower().replace("&amp;", "&")
    s = re.sub(r"^[a-z]{2,4}\s*[:\-|]\s*", "", s)          # "HR: ", "HR - ", "DK| "
    s = re.sub(r"\.[a-z]{2,3}$", "", s)                     # ".hr", ".dk", ".uk"
    s = s.replace("htv", "hrt").replace("&", " and ").replace("+", " and ")
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    s = re.sub(r"\b(fhd|uhd|hd|sd|4k|hevc|adria|hr|croatia|yu|ex yu|dk|se|uk)\b", " ", s)
    if loose:
        s = re.sub(r"\b(rs|srbija|serbia|bih|bh|ba|cg|me|channel|network|nordic|live)\b", " ", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    s = s.replace("tv", "")
    return re.sub(r"arenasport(\d)premium", r"arenapremium\1", s)


def candidates(k):
    """Name variants to try, most specific first."""
    out = [ALIASES.get(k, k), k]
    if k.endswith("1"):
        out.append(k[:-1])          # "pink1" -> "pink"
    else:
        out.append(k + "1")         # "bht" -> "bht1"
    return [c for c in out if c]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 hr-epg"})
    data = urllib.request.urlopen(req, timeout=300).read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return ET.parse(io.BytesIO(data)).getroot()


def tv_logos(folder):
    """{norm name: png url} for one tv-logos country folder."""
    api = f"https://api.github.com/repos/tv-logo/tv-logos/contents/countries/{folder}"
    headers = {"User-Agent": "hr-epg", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    items = json.load(urllib.request.urlopen(urllib.request.Request(api, headers=headers), timeout=60))
    out = {}
    for it in sorted(items, key=lambda x: len(x["name"])):   # plain names before variants
        name = it["name"]
        if not name.endswith(".png"):
            continue
        stem = re.sub(r"-[a-z]{2}$", "", name[:-4])          # drop country suffix "-hr"
        for loose in (False, True):
            k = norm(stem.replace("-", " "), loose)
            if k and (loose, k) not in out:
                out[(loose, k)] = it["download_url"]
    return out


def parse_time(s):
    try:
        return dt.datetime.strptime(s[:20].strip(), "%Y%m%d%H%M%S %z")
    except ValueError:
        return None


def main():
    channels = json.load(open("channels.json", encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    index = {}   # country -> {norm name: source key}
    progs = {}   # source key (url, channel id) -> [programme elements]
    icons = {}   # source key -> logo URL
    logo_idx = {}  # country -> {norm name: logo URL}, also for channels without programmes
    fetched = {}
    for cc, urls in SOURCES.items():
        idx = index.setdefault(cc, {})
        lidx = logo_idx.setdefault(cc, {})
        for url in urls:
            if url not in fetched:
                try:
                    fetched[url] = fetch(url)
                except Exception as e:  # one broken source must not break the build
                    print(f"WARN {url}: {e}", file=sys.stderr)
                    fetched[url] = None
                    continue
                for p in fetched[url].iter("programme"):
                    start, stop = parse_time(p.get("start", "")), parse_time(p.get("stop", ""))
                    if stop and stop < now - KEEP_PAST or start and start > now + KEEP_FUTURE:
                        continue
                    progs.setdefault((url, p.get("channel")), []).append(p)
            root = fetched[url]
            if root is None:
                continue
            for ch in root.iter("channel"):
                key = (url, ch.get("id"))
                icon = ch.find("icon")
                names = [d.text for d in ch.findall("display-name")] + [ch.get("id")]
                if icon is not None and icon.get("src"):
                    icons[key] = icon.get("src")
                    for n in names:
                        for loose in (False, True):
                            lidx.setdefault((loose, norm(n, loose)), icon.get("src"))
                if key not in progs:
                    continue
                for n in names:
                    for loose in (False, True):
                        k = norm(n, loose)
                        if k and (loose, k) not in idx:
                            idx[(loose, k)] = key

    def lookup(c):
        if "|" in c["name"]:            # one-off event channels have no EPG
            return None
        countries = [c["cc"]] + [x for x in FALLBACK.get(c["cc"], []) if x != c["cc"]]
        for loose in (False, True):     # exact names first, then without country tags
            k = norm(c["name"], loose)
            for cc in countries:
                idx = index.get(cc, {})
                for cand in candidates(k):
                    if (loose, cand) in idx:
                        return idx[(loose, cand)]
        k = norm(c["name"])
        if len(k) >= 5:                 # last resort: near-identical name in own country
            idx = {n: v for (l, n), v in index.get(c["cc"], {}).items() if not l}
            close = difflib.get_close_matches(k, list(idx), n=1, cutoff=0.93)
            if close:
                return idx[close[0]]
        return None

    resolved = {c["name"]: s for c in channels if (s := lookup(c))}

    # A tvg-id is used only if every channel carrying it maps to the same source.
    by_id = {}
    for c in channels:
        if c["tvg_id"]:
            by_id.setdefault(c["tvg_id"], set()).add(resolved.get(c["name"]))
    safe_ids = {i: next(iter(s)) for i, s in by_id.items() if len(s) == 1 and None not in s}

    # Logos: EPG source channel first, then any source channel by name, then tv-logos.
    folders = {}

    def folder(name):
        if name not in folders:
            try:
                folders[name] = tv_logos(name)
            except Exception as e:
                print(f"WARN logos {name}: {e}", file=sys.stderr)
                folders[name] = {}
        return folders[name]

    def logo_for(c):
        if "|" in c["name"]:
            return None
        src = resolved.get(c["name"])
        if src in icons:
            return icons[src]
        countries = [c["cc"]] + [x for x in FALLBACK.get(c["cc"], []) if x != c["cc"]]
        tables = [logo_idx.get(cc, {}) for cc in countries]
        tables += [folder(f) for f in LOGO_DIRS.get(c["cc"], [])]
        for loose in (False, True):
            k = norm(c["name"], loose)
            for table in tables:
                for cand in candidates(k):
                    if (loose, cand) in table:
                        return table[(loose, cand)]
        return None

    logos = {c["name"]: u for c in channels if (u := logo_for(c))}

    # id -> (programme source or None, logo or None)
    outputs = {i: (s, None) for i, s in safe_ids.items()}
    for c in channels:
        if c["name"] in resolved and c["tvg_id"] not in safe_ids:
            outputs[c["name"]] = (resolved[c["name"]], None)
    for c in channels:                  # attach logos, incl. channels that only have a logo
        u = logos.get(c["name"])
        if not u:
            continue
        oid = c["tvg_id"] if c["tvg_id"] in safe_ids else c["name"]
        src, logo = outputs.get(oid, (None, None))
        outputs[oid] = (src, logo or u)

    out = ET.Element("tv", {"generator-info-name": "hr-epg"})
    for oid, (src, logo) in outputs.items():
        ch = ET.SubElement(out, "channel", {"id": oid})
        ET.SubElement(ch, "display-name").text = oid
        if logo:
            ET.SubElement(ch, "icon", {"src": logo})
    for oid, (src, _) in outputs.items():
        if src is None:
            continue
        for p in progs[src]:
            q = ET.SubElement(out, "programme", dict(p.attrib, channel=oid))
            q.extend(list(p))

    buf = io.BytesIO()
    ET.ElementTree(out).write(buf, encoding="utf-8", xml_declaration=True)
    with gzip.open("hr.xml.gz", "wb", compresslevel=9) as f:
        f.write(buf.getvalue())

    real = [c for c in channels if "|" not in c["name"]]
    print(f"Matched {len(resolved)}/{len(channels)} channels ({len(outputs)} EPG ids).")
    print(f"Logos for {sum(c['name'] in logos for c in real)}/{len(real)} channels "
          f"(event channels excluded).")
    by_cc = {}
    for c in channels:
        t = by_cc.setdefault(c["cc"], [0, 0])
        t[1] += 1
        t[0] += c["name"] in resolved
    print("  " + ", ".join(f"{cc} {a}/{b}" for cc, (a, b) in sorted(by_cc.items())))
    with open("matches.txt", "w", encoding="utf-8") as f:
        for c in channels:
            if c["name"] in resolved:
                url, cid = resolved[c["name"]]
                f.write(f"{c['name']}  ->  {cid}  ({url.split('/')[-1]})\n")
    with open("logos.txt", "w", encoding="utf-8") as f:
        for c in real:
            f.write(f"{c['name']}  ->  {logos.get(c['name'], '-')}\n")
    missing = [c["name"] for c in channels if c["name"] not in resolved]
    with open("missing.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(missing) + "\n")


if __name__ == "__main__":
    main()
