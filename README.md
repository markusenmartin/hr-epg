# HR EPG za TiviMate

`hr.xml.gz` se automatski gradi dvaput dnevno (GitHub Actions) iz javnih hrvatskih EPG izvora
(iptv-epg.org, epgshare01, open-epg). Kanali su preimenovani tako da odgovaraju nazivima
u IPTV playlisti, pa ih TiviMate sam poveže.

- Popis kanala: `channels.json` (naziv i tvg-id iz playliste)
- Ručna povezivanja naziva: `ALIASES` u `build_epg.py`
- URL za TiviMate: `https://raw.githubusercontent.com/markusenmartin/hr-epg/main/hr.xml.gz`
