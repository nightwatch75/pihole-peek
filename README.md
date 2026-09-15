# pihole-peek

**Version 2.4.0** · Pi-hole v6 · MIT · [what changed](#versions)

Ask the **Pi-hole v6 REST API** what a device on your network talks to, grouped by domain: the
smart TV that phones home, the phone with an ad SDK, the IoT box that never goes quiet. Export it
as a table, a domain list, CSV, JSON, or a self-contained **HTML report** with live filters,
sortable columns and a per-domain look-up.

Two scripts, `pihole-peek` (bash) and `pihole-peek.py` (Python 3.8, no dependencies). Same options,
same output.

## Quickstart

```sh
# get it
git clone https://github.com/nightwatch75/pihole-peek.git
cd pihole-peek

# tell it where your Pi-hole is
cp config.example config
$EDITOR config                 # PIHOLE_URL="http://192.0.2.10"

# export a report of the last 24 hours
./pihole-peek -f html > all-clients.html           # every client
./pihole-peek -c 192.0.2.70 -f html > tv.html      # one client
```

Open the `.html` in a browser. No `jq` on this machine? Use `./pihole-peek.py` instead — same
options, only Python needed.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/hero-dark.png">
  <img alt="The HTML report: a client's domains with their state, category, hit count and last seen"
       src="docs/hero-light.png">
</picture>

And the same data in the terminal:

```
$ pihole-peek --client 192.0.2.70 --status blocked
DOMAIN                                                  HITS  LAST SEEN
nrdp25.logs.netflix.com                                  807  2026-09-11 23:35
unagi-eu.amazon.com                                      765  2026-09-12 14:14
eic.service.lgtvcommon.com                               469  2026-09-11 23:41
eu-acr92.alphonso.tv                                     399  2026-09-11 21:46
prov-lg.alphonso.tv                                      214  2026-09-11 23:35

192.0.2.70 · blocked · 5 domains · 2654 queries · last 24 h
```

Pi-hole v6 only. Version 5 used `admin/api.php` with an auth token, which this tool does not speak.

## Requirements

A Pi-hole v6, and one of:

- **`pihole-peek`** — `bash` 3.2+, `curl`, `jq` 1.6+, and the POSIX `awk`, `mktemp` and `dd` every
  Unix already ships.
- **`pihole-peek.py`** — Python 3.8+, standard library only.

[Which one to pick](#two-implementations-one-behaviour).

**Tested on Pi-hole core v6.4.3 with FTL v6.7.** Other 6.x builds should work; if one does not,
open an issue with `pihole-peek -f raw | jq '.queries[0]'` and `/api/info/version`.

## Install

To call it from anywhere, link either script into your PATH:

```sh
ln -s "$PWD/pihole-peek" ~/.local/bin/pihole-peek        # the bash one
ln -s "$PWD/pihole-peek.py" ~/.local/bin/pihole-peek     # or the Python one, same name
```

Both follow their own symlink, so `config` and `categories` are still found next to the real file.

On Windows, install Python and run the script where it lies:

```powershell
py pihole-peek.py -u http://pihole.example.lan -f html > report.html
```

Every example below says `pihole-peek`; they all hold for `pihole-peek.py` too.

## Two implementations, one behaviour

|  | `pihole-peek` | `pihole-peek.py` |
|---|---|---|
| Linux | yes | yes |
| macOS | yes, once `jq` is installed | yes, with the Python the Command Line Tools install |
| Windows | only inside WSL or Git Bash, and neither ships `jq` | yes |
| CPU for a week of traffic | 1.0 s | 0.3 s |
| Peak memory | 34 MB | 45 MB, and 22 MB of that is the interpreter |

Both read the same `config` and `categories` and write the same bytes: every format is compared
file by file before a release, down to a 343 KB HTML report of 57755 queries. One difference is on
purpose — with `-f raw` the bash script pipes the answer through `jq`, which rewrites `5.79e-05` as
`0.0000579`, while the Python one writes the API bytes untouched.

Pick Python for the easy install, for Windows, or to spend less CPU. Pick bash for the smaller
memory floor on a tiny box. Neither is faster end to end: the Pi-hole needs about eleven seconds to
hand over a week of queries, and that is most of the wait either way.

## Configuration

**Command line > environment > config file.**

| Source | Where |
|---|---|
| command line | `--url`, `--client`, … |
| environment | `PIHOLE_URL`, `PIHOLE_CLIENT`, `PIHOLE_ALIAS`, `PIHOLE_PASSWORD` |
| config file | `config` next to the script, or the path in `PIHOLE_PEEK_CONFIG` |

```sh
cp config.example config
chmod 600 config          # it can hold a password
```

```sh
PIHOLE_URL="http://pihole.example.lan"
#PIHOLE_CLIENT="192.0.2.70"
#PIHOLE_ALIAS="living room TV"
#PIHOLE_PASSWORD="change-me"
#PIHOLE_STATUS="all"
#PIHOLE_HOURS="24"
#PIHOLE_PAGE_SIZE="10000"
#PIHOLE_FORMAT="count"
#PIHOLE_INSECURE="0"
```

`config` is gitignored, so your address and password stay on your machine. If it sets a default
client, `--all-clients` puts the report back on every client.

Keep it to plain `NAME="value"` lines: bash sources the file, Python only reads assignments, so
`PIHOLE_PASSWORD="$(pass show pihole)"` works in one and not in the other.

## Usage

```sh
pihole-peek --list-clients                       # which clients does the Pi-hole see?

pihole-peek -c 192.0.2.70                        # every query of one client, last 24 h
pihole-peek -c 192.0.2.70 -s blocked             # only what the Pi-hole stopped
pihole-peek -c 192.0.2.70 -s allowed -t 6        # only what went out, last 6 hours
pihole-peek -c tv.lan -s blocked -f list > tv-domains.txt   # one domain per line

pihole-peek                                      # every client, with a CLIENT column
pihole-peek -n 20 -f csv > report.csv            # top 20 rows as CSV
pihole-peek -d 'doubleclick|googleads'           # only the domains that match a regex

pihole-peek -f html > report.html                # interactive report, open it in a browser
pihole-peek -c 192.0.2.70 -A "living room TV" -f html > tv.html

pihole-peek --since '2026-09-12 00:00' --until '2026-09-12 08:00'
pihole-peek -u https://pihole.example.lan:8443 -k    # HTTPS with a self-signed certificate
pihole-peek -f raw | jq '.queries[] | .upstream'     # raw API answer, your own jq
```

### Options

| Flag | Environment | Default | What it does |
|---|---|---|---|
| `-u`, `--url URL` | `PIHOLE_URL` | — | Pi-hole base URL, e.g. `http://pihole.lan` or `https://pihole.lan:8443`. The API is at `URL/api`. A missing scheme becomes `http://`, a trailing `/admin` is removed. |
| `-c`, `--client ADDR` | `PIHOLE_CLIENT` | every client | client IP or hostname |
| `-a`, `--all-clients` | — | — | report every client, even when a default client is configured |
| `-A`, `--alias NAME` | `PIHOLE_ALIAS` | — | friendly name of the client, written next to its address in the HTML report. It needs a client, so `--all-clients` clears it. |
| `-s`, `--status SET` | `PIHOLE_STATUS` | `all` | which queries to export — see the table below |
| `-t`, `--hours N` | `PIHOLE_HOURS` | `24` | time window, hours back from now |
| `--since TS` | — | — | absolute start. `YYYY-MM-DD`, optionally with ` HH:MM` or ` HH:MM:SS`, or `@EPOCH`. The bash script also takes anything GNU `date -d` reads, where GNU `date` is the one installed. |
| `--until TS` | — | now | absolute end |
| `-d`, `--domain REGEX` | — | — | keep only the domains that match the regex (case insensitive) |
| `-n`, `--top N` | — | every row | keep only the first N rows |
| `-f`, `--format FMT` | `PIHOLE_FORMAT` | `count` | `count`, `list`, `csv`, `json`, `html` or `raw` |
| `--page-size N` | `PIHOLE_PAGE_SIZE` | `10000` | queries per API request. The server never returns more than 10000; lower it to use less memory on a small box. |
| `--categories F` | `PIHOLE_PEEK_CATEGORIES` | a file named `categories` next to the script | the category rules of the HTML report; the rules in `F.local` are read first and win |
| `--list-clients` | — | — | list the clients the Pi-hole knows, with their query count, and exit |
| `--client-names` | `PIHOLE_CLIENT_NAMES` | off | show each client's DHCP/DNS name instead of its address, in the CLIENT column and, for the HTML report, the client filter too. Falls back to the address when a client has no known name. |
| `-k`, `--insecure` | `PIHOLE_INSECURE` | off | accept a self-signed TLS certificate |
| `--totp CODE` | — | — | two-factor code, when the Pi-hole asks for one |
| — | `PIHOLE_PASSWORD` | — | web or app password. There is no flag for it, so it never lands in your shell history. |
| `-V`, `--version` / `-h`, `--help` | — | — | |

## What to export: the status sets

Without `--status` the export holds **every** query of the window. Narrow it with a group name or
a comma separated list of FTL statuses.

| Value | Statuses it covers | Use it for |
|---|---|---|
| `blocked` | `GRAVITY`, `GRAVITY_CNAME`, `DENYLIST`, `DENYLIST_CNAME`, `REGEX`, `REGEX_CNAME`, `EXTERNAL_BLOCKED_IP`, `EXTERNAL_BLOCKED_NULL`, `EXTERNAL_BLOCKED_NXRA`, `EXTERNAL_BLOCKED_EDE15`, `SPECIAL_DOMAIN` | what the Pi-hole stopped |
| `allowed` | `FORWARDED`, `RETRIED`, `RETRIED_DNSSEC` | what really went out to the upstream resolver |
| `cached` | `CACHE`, `CACHE_STALE` | what was answered from the cache |
| `all` *(default)* | every status | the full picture, blocked and allowed together |
| a list | e.g. `GRAVITY,DENYLIST` or `FORWARDED` | one exact status, or your own mix |

`GRAVITY` is a blocklist, `DENYLIST` an exact rule of yours, `REGEX` one of your regular
expressions. The `*_CNAME` variants mean the domain itself is clean but points at a blocked one.

> The API accepts one `status` per request, so a group is fetched whole and filtered locally:
> `--status blocked` is still a single HTTP request.

## Output formats

**`count`** (default) — a table sorted by hits, local timestamps, a summary line. A `CLIENT`
column appears when no client is selected.

```
DOMAIN                                               CLIENT              HITS  LAST SEEN
ms.applovin.com                                      192.0.2.128          947  2026-09-12 14:00
pubads.g.doubleclick.net                             192.0.2.128          332  2026-09-12 14:00

all clients · blocked · 2 domains · 1279 queries · last 24 h
```

**`list`** — the unique domains, one per line, sorted. Ready for a blocklist, a `diff` or `xargs`.

```
eic.service.lgtvcommon.com
it.info.lgsmartad.com
```

**`csv`** — `domain[,client],hits,status,last_seen`, sorted by hits, timestamps in UTC ISO-8601.

```csv
domain,hits,status,last_seen
"nrdp25.logs.netflix.com",807,"GRAVITY","2026-09-11T21:35:28Z"
```

**`json`** — the same records as an array, for a script downstream.

```json
[{ "domain": "nrdp25.logs.netflix.com", "hits": 807, "status": "GRAVITY", "last_seen": "2026-09-11T21:35:28Z" }]
```

**`html`** — a single self-contained file to open in a browser. See the next section.

```sh
pihole-peek -f html > report.html && xdg-open report.html
```

**`raw`** — the API answers untouched, for your own `jq`: query type, upstream, reply time, DNSSEC
state, CNAME chain. A window needing several requests prints one JSON document per page, and `jq`
reads them in sequence, so `-f raw | jq '.queries[]'` still sees everything.

With `--top N` the summary counts the rows that are shown, not the whole window.

## The HTML report

One file, no CDN, no build step: the data is in the page, so the report works offline, on a USB
stick or in an email. `-f html` always keeps the client of every row, so the client filter works
even when `--client` already narrowed the export.

* **live filters** — free text on the domain, plus drop-downs for client, category and FTL status.
  The counter and the bar scale follow the selection.
* **sortable columns** — click a header, click again to reverse.
* **a state and a category on every row** — a coloured square and its wording for what the Pi-hole
  did, a dot and its name for what the domain is. Both tables are below.
* **a look-up panel** — click a row for first and last seen, the statuses, the registrable name,
  the rule that chose the category, a **Whois** button and links to Google, VirusTotal,
  urlscan.io, Netify and crt.sh.
* **export what you filtered** — *Copy domains* to the clipboard, *Download CSV* with the state,
  the readable status and the category added.
* **a legend at the foot** — every status and category with what it means and how many queries it
  holds here; the ones this export does not contain stay greyed out.
* **light and dark** — the sun/moon button forces one, otherwise the page follows the system theme.

The header carries the version that made the report, so one found in a folder still says where it
came from.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/detail-dark.png">
  <img alt="A row opened: first and last seen, the statuses, the registrable name, the rule that chose the category, then the Whois button and the look-up links"
       src="docs/detail-light.png">
</picture>

`--alias` gives the client a name you recognise: the header reads *192.0.2.70 **living room TV***,
the browser tab carries it, and *Download CSV* uses it in the file name. An address says which
device answered; the alias says which device it is.

### The state of a row

The export holds every status by default, so each row says what the Pi-hole did. The square is
only a second encoding: the wording is always there.

| Square | State | What the row says |
|---|---|---|
| red | `blocked` | `blocked · blocklist`, `· your rule`, `· your regex`, `· CNAME …`, `· by the upstream` |
| green | `forwarded` | `forwarded · asked the upstream`, `· retried`, `· DNSSEC retry` |
| grey | `cached` | `cached · answered locally`, `· stale answer` |
| amber | `mixed` | the domain had more than one state in the window, e.g. `forwarded + cached` |
| grey | `other` | `in progress`, `database busy`, `unknown` |

The status drop-down filters on either level: a state, or an exact FTL status. Hovering a square
shows the raw statuses behind the row.

### The domain categories

**The script ships no taxonomy of its own.** Every category, its colour and its wording live in
the `categories` file next to it. Change the file and the next report follows; delete it and the
report drops the category column.

```sh
# <category> <regex>            classify a domain; the FIRST match wins
# @color <category> <light> [dark]
# @about <category> <text>      the sentence shown in the legend

@color ads        #eb6834 #d95926
@about ads        ad exchanges and ad SDKs
ads               doubleclick|googleads|applovin|criteo|openx|(^|\.)ads?[.-]
```

A line starting with `#` is a comment; anywhere else a `#` belongs to the value, so a regex or a
colour can hold one. The regex is case insensitive and tested against the whole domain.

<details>
<summary>The 18 categories the shipped file carries</summary>

| Category | What lands there |
|---|---|
| `ads` | ad exchanges and ad SDKs: doubleclick, applovin, moloco, vungle, criteo, openx … |
| `acr` | automatic content recognition, the "what is on the screen" services of a smart TV: alphonso, samba.tv, inscape, gracenote |
| `tracking` | third-party analytics, attribution and monitoring: google-analytics, segment, appsflyer, sentry, onetrust … |
| `telemetry` | the device talking about itself: `logs.*`, `*.telemetry.*`, `*.metrics.*`, beacons, crash reports |
| `connectivity` | captive-portal and "am I online" checks |
| `pki` | certificate validation: OCSP, CRL, timestamping |
| `ntp` | clock synchronisation |
| `dns` | public resolvers, DNS over HTTPS, DNS services |
| `update` | firmware, packages and mirrors |
| `smarthome` | connected devices and home automation: hue, tuya, shelly, sonos, smartthings … |
| `gaming` | game platforms and stores |
| `social` | social networks and messaging |
| `ai` | assistants and language models |
| `shopping` | shops and marketplaces |
| `streaming` | the media services themselves: netflix, amazonvideo, youtube, spotify, twitch |
| `vendor` | services of the device maker: lgtvcommon, samsung, tizen, roku, apple, microsoft |
| `cdn` | content delivery networks |
| `cloud` | generic cloud, hosting and platform APIs |
| `other` | no rule matched |

</details>

**The order of the lines is the specification**: the first match wins, so `logs.ads.vungle.com` is
`ads` and not `telemetry`, because the `ads` line comes first. Hovering a category shows the rule
that chose it — that is how a wrong one gets found.

Only four categories are coloured: `ads` orange, `acr` aqua, `tracking` and `telemetry` sharing the
blue because they mean the same thing, data about the device leaving the network. Three hues is
what passes the colour-blindness and contrast checks in both themes; every other category keeps a
neutral dot and relies on its name, which is what lets the list grow.

### Your own categories

Do not edit `categories`: a later `git pull` would fight you. Write your rules in
**`categories.local`** next to it — ignored by git, read first, so your rules win:

```sh
# extend a category that already exists
smarthome    my-thermostat|my-doorbell\.local
# or invent one, with a colour and a description of its own
@color printer    #4a3aa7 #9085e9
@about printer    the printers on this network
printer           brother|epsonconnect|hpeprint
# force a domain the shipped rules read the wrong way
streaming         ^cdn-0\.example-video\.com$
```

A regex that does not compile is reported in the legend instead of breaking the page.

The shipped rules are opinions, not facts: written against one home network, they will put some
domain in the wrong box on yours. A pull request that fixes one is welcome.

### The Whois button

It asks [rdap.org](https://rdap.org) about the **registrable** name
(`eic.service.lgtvcommon.com` → `lgtvcommon.com`) and shows the registrar, the registration date
with the age of the domain, the expiry and the name servers. RDAP answers JSON and sends
`Access-Control-Allow-Origin: *`, so the page reads it with no API key and no proxy.

It fires **only when you press the button** — opening the report sends nothing. A young domain
behind a privacy-proxy registrar is a useful signal next to a name you do not know. Some registries
answer nothing useful to a browser, `.de` and `.it` among them; the panel then says so and links
you to the answer.

## Authentication

`pihole-peek` asks `GET /api/auth` first and adapts:

* **no password** — nothing to do.
* **password** — put it in `PIHOLE_PASSWORD`, in the environment or in the config file. An **app
  password** (*Settings → Web interface / API*) is better: revocable, and it does not unlock the
  web interface.
* **two-factor** — add `--totp 123456`.
* **self-signed certificate** — add `--insecure`.

The session lasts the single run and is closed with `DELETE /api/auth`, so it never eats a session
slot.

## Large windows

The API returns **at most 10000 queries per request**, whatever `length` asks for, and does not
say so: `recordsFiltered` keeps reporting the real total. `pihole-peek` walks the window page by
page with `start` and folds each page in as it arrives, so the result covers the whole range.

Memory does not grow with the window. Each page is reduced on arrival and only one entry per domain
is kept — a few thousand — so a day and a week cost the same. On a week of real traffic, 57755
queries in six requests, the bash script peaks at **34 MB** and the Python one at **45 MB**, of
which 22 MB is the interpreter. `--page-size 2000` makes each request smaller if a box is very
small: more pages, lower peak, 12 MB and 30 MB.

When the pages do not add up to `recordsFiltered` — new queries can land during a long run — the
script says so on stderr instead of reporting a short total in silence.

## The 24-hour limit

By default the API refuses to look further back than 24 hours, whatever `--since` says, because of
`webserver.api.maxHistory` — the long-term database usually holds much more. Raise it, here to one
week:

```sh
curl -X PATCH http://pihole.example.lan/api/config \
  -H 'content-type: application/json' \
  -d '{"config":{"webserver":{"api":{"maxHistory":604800}}}}'
```

Or set `maxHistory` in `/etc/pihole/pihole.toml` and restart FTL. How far the data really goes
back is the `earliest_timestamp_disk` field of a `-f raw` answer.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | error — bad option, no address, no connection, authentication refused |
| `2` | no query matches the filters |

So a cron job can tell "nothing matched" from "the Pi-hole is down".


## Versions

| Version | What changed |
|---|---|
| **2.4.0** | `--client-names` shows each client's DHCP/DNS name in place of its address, falling back to the address for a client the Pi-hole cannot name. Off by default. Rows stay grouped by address, so two unnamed clients stay apart. Thanks to [@gbarwis](https://github.com/gbarwis). |
| 2.3.1 | `pihole-peek.py` no longer stops on a byte that is not valid UTF-8, which FTL can log for a malformed query and which used to end a whole run. The byte becomes `U+FFFD`, as `jq` has always done for the bash script. Thanks to [@gbarwis](https://github.com/gbarwis). |
| 2.3.0 | `pihole-peek.py`, a Python port that needs no `jq` and runs on Windows. Four fixes in the bash script: a stable row order on every `awk`, `-f count` three times faster, the environment winning over the config file as documented, and `categories.local` winning for colours and wording as it already did for rules. |
| 2.2.0 | Reads the whole window. Earlier versions stopped at the 10000 queries the API returns per request and reported the short total in silence. |
| 2.1.0 | Runs on a stock macOS: no `bash` 4, no GNU `date`. |

## License

MIT — see [LICENSE](LICENSE).
