# EPG za TiviMate

`hr.xml.gz` se automatski gradi dvaput dnevno (GitHub Actions) iz javnih EPG izvora
(iptv-epg.org, epgshare01, open-epg) za grupe koje se gledaju: Hrvatska, ex-YU (dokumentarni,
sportski, filmski, dječji, Pink), Srbija, Bosna, Crna Gora, Danska, Viaplay, Švedska i UK.
Kanali su preimenovani tako da odgovaraju nazivima u IPTV playlisti, pa ih TiviMate sam poveže.
Uz program se šalju i logotipi kanala.

- Popis kanala: `channels.json` (naziv, tvg-id, grupa i zemlja iz playliste)
- Izvori po zemlji: `SOURCES` u `build_epg.py`
- Ručna povezivanja naziva: `ALIASES` u `build_epg.py`
- Nakon izgradnje: `matches.txt` (koji kanal je povezan s čim) i `missing.txt` (kanali bez EPG-a)
- URL za TiviMate: `https://raw.githubusercontent.com/markusenmartin/hr-epg/main/hr.xml.gz`
