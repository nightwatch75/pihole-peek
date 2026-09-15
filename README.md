# pihole-peek

**Version 2.4.0** · Pi-hole v6 · MIT · [what changed](#versions)

A small tool that asks the **Pi-hole v6 REST API** which domains a client resolved, and groups the
answer by domain. It tells you what a device on your network talks to — the smart TV that phones
home, the phone that runs an ad SDK, the IoT box that never stops — and it exports the result as a
table, a plain domain list, CSV, JSON or a self-contained **HTML report** with live filters,
sortable columns and a per-domain look-up.

It comes twice: `pihole-peek`, a bash script, and `pihole-peek.py`, a Python script. Same options,
same files, same bytes out. Use whichever suits the machine you are on.

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

A Pi-hole v6, and one of the two scripts:

- **`pihole-peek`** — `bash` 3.2 or later, `curl`, `jq` 1.6 or later (it uses `$ARGS.named`), and
  the POSIX `awk`, `mktemp` and `dd` that every Unix already ships. It runs on a stock macOS
  install once `jq` is there.
- **`pihole-peek.py`** — Python 3.8 or later. Standard library only: nothing to install, and no
  `curl`, `jq`, `awk` or `date`.

[Two implementations, one behaviour](#two-implementations-one-behaviour) says which to pick.

**Tested on Pi-hole core v6.4.3 with FTL v6.7.** That is the only build it has been run against. The
v6 API is stable across the 6.x line, so other builds should work, but if one does not, open an
issue with the output of `pihole-peek -f raw | jq '.queries[0]'` and the version the Pi-hole reports
at `/api/info/version`.

## Install

```sh
git clone https://github.com/nightwatch75/pihole-peek.git
cd pihole-peek
ln -s "$PWD/pihole-peek" ~/.local/bin/pihole-peek        # the bash script
ln -s "$PWD/pihole-peek.py" ~/.local/bin/pihole-peek     # or the Python one, same name
```

Both follow their own symlink, so the `config` and `categories` files next to the real script are
always found.

On Windows there is no symlink to make. Install Python, then run the script where it lies:

```powershell
py pihole-peek.py -u http://pihole.example.lan -f html > report.html
```

Every example below uses the name `pihole-peek`. They all hold for `pihole-peek.py` as well: the
options are the same.

## Two implementations, one behaviour

|  | `pihole-peek` | `pihole-peek.py` |
|---|---|---|
| Needs | `bash`, `curl`, `jq`, `awk` | Python 3.8 or later, nothing else |
| Linux | yes | yes |
| macOS | yes, once `jq` is installed | yes, with the Python the Command Line Tools install |
| Windows | only inside WSL or Git Bash, and neither ships `jq` | yes |
| CPU for a week of traffic | 1.0 s | 0.3 s |
| Peak memory | 34 MB | 45 MB, and 22 MB of that is the interpreter |

Both read the same `config` and `categories` files and write the same bytes. Every format is
compared file by file before a release — a 343 KB HTML report of 57755 queries comes out identical
from the two.

One difference is on purpose. With `-f raw` the bash script pipes the answer through `jq`, which
rewrites a number such as `5.79e-05` as `0.0000579`; the Python script writes the bytes the API
sent, untouched.

So: the Python script is the easier install, it is the only one that runs on Windows as it is, and
it uses about a third of the CPU. The bash script has the smaller memory floor, which is what
counts on a very small box. Neither is faster in practice on a whole run — the Pi-hole itself takes
about eleven seconds to hand over a week of queries, and that is most of the wait either way.

## Configuration

Three sources, in this order — **the command line wins over the environment, and the environment
wins over the config file**:

| Source | Where |
|---|---|
| command line | `--url`, `--client`, … |
| environment | `PIHOLE_URL`, `PIHOLE_CLIENT`, `PIHOLE_ALIAS`, `PIHOLE_PASSWORD` |
| config file | a file named `config` next to the script, or the path in `PIHOLE_PEEK_CONFIG` |

Copy the example and edit it:

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

`config` is in `.gitignore`: your address and your password stay on your machine.
If the config file sets a default client, `--all-clients` puts the report back on every client.

Keep the file to plain `NAME="value"` lines. The bash script sources it, so anything else in it
runs as a shell command; the Python script only reads assignments and ignores the rest. A line such
as `PIHOLE_PASSWORD="$(pass show pihole)"` therefore works in one and not in the other.

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

Without `--status` the export holds **every** query of the window. Narrow it with a **group name**
or a **comma separated list of FTL statuses**.

| Value | Statuses it covers | Use it for |
|---|---|---|
| `blocked` | `GRAVITY`, `GRAVITY_CNAME`, `DENYLIST`, `DENYLIST_CNAME`, `REGEX`, `REGEX_CNAME`, `EXTERNAL_BLOCKED_IP`, `EXTERNAL_BLOCKED_NULL`, `EXTERNAL_BLOCKED_NXRA`, `EXTERNAL_BLOCKED_EDE15`, `SPECIAL_DOMAIN` | what the Pi-hole stopped |
| `allowed` | `FORWARDED`, `RETRIED`, `RETRIED_DNSSEC` | what really went out to the upstream resolver |
| `cached` | `CACHE`, `CACHE_STALE` | what was answered from the cache |
| `all` *(default)* | every status | the full picture, blocked and allowed together |
| a list | e.g. `GRAVITY,DENYLIST` or `FORWARDED` | one exact status, or your own mix |

`GRAVITY` means a blocklist stopped it, `DENYLIST` an exact rule of yours, `REGEX` one of your
regular expressions. The `*_CNAME` variants are deep CNAME inspection: the domain itself is clean,
but it points at a blocked one.

> The API accepts one `status` value per request. `pihole-peek` therefore asks for the whole window
> and filters the group locally, so `--status blocked` is still a single HTTP request.

## Output formats

**`count`** (default) — a table sorted by hits, timestamps in your local time, and a summary line.
A `CLIENT` column appears when no client is selected.

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

**`raw`** — the API answers with no processing, for your own `jq`. Every field is there: query type,
upstream, reply time, DNSSEC state, CNAME chain. A window that needs several requests prints one
JSON document per page; `jq` reads them in sequence, so `-f raw | jq '.queries[]'` still sees
everything.

With `--top N` the summary counts the rows that are shown, not the whole window.

## The HTML report

One file, no CDN, no build step: the data is embedded in the page, so the report keeps working
offline, on a USB stick or in an email. `--format html` always keeps the client of every row, so the
client filter works even when `--client` already narrowed the export.

What the page gives you:

* **live filters** — free text on the domain, plus a drop-down for client, category and FTL status.
  The counter and the bar scale follow the selection.
* **sortable columns** — click a header to sort by domain, status, category, client, hits or last
  seen; click again to turn the order around.
* **a state for every row** — a coloured square and the wording that says what happened to that
  domain, so a full export stays readable; see the table below.
* **a category for every domain** — matched locally against the rules in the `categories` file,
  see the table below.
* **a look-up panel** — click a row: first seen, last seen, the statuses, the registrable name, the
  category with the rule that chose it, then a **Whois** button and links to Google, VirusTotal,
  urlscan.io, Netify and crt.sh.
* **export what you filtered** — *Copy domains* puts the visible list in the clipboard, *Download
  CSV* saves it with the state, the readable status and the category added.
* **the version that made it** — the header carries the `pihole-peek` version next to the name, so a
  report that travels by mail or sits in a folder still says what produced it.
* **a legend at the foot of the page** — every FTL status with the sentence that explains it, every
  category with what it covers, and the number of queries each one holds in this export. Values the
  export does not contain stay greyed out, so the legend doubles as a reference.
* **light and dark** — the sun/moon button forces either one, otherwise the page follows the system
  theme and the button follows with it.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/detail-dark.png">
  <img alt="A row opened: first and last seen, the statuses, the registrable name, the rule that chose the category, then the Whois button and the look-up links"
       src="docs/detail-light.png">
</picture>

`--alias` gives the client a name you recognise. The report then reads *pihole-peek v2.1.0 ·
192.0.2.70 **living room TV***, the browser tab carries the name, and *Download CSV* uses it in the
file name.
An address tells you which device answered; the alias tells you which device it is.

### The state of a row

Since the export holds every status by default, each row says what the Pi-hole did with that
domain. The square is only a second encoding — the wording is always there.

| Square | State | What the row says |
|---|---|---|
| red | `blocked` | `blocked · blocklist`, `· your rule`, `· your regex`, `· CNAME …`, `· by the upstream` |
| green | `forwarded` | `forwarded · asked the upstream`, `· retried`, `· DNSSEC retry` |
| grey | `cached` | `cached · answered locally`, `· stale answer` |
| amber | `mixed` | the domain had more than one state in the window, e.g. `forwarded + cached` |
| grey | `other` | `in progress`, `database busy`, `unknown` |

The status drop-down filters on either level: a **state** (blocked, forwarded, cached, mixed) or an
**exact FTL status** (`GRAVITY`, `DENYLIST`, `CACHE_STALE` …). Hovering a square shows the raw
statuses behind the row.

### The domain categories

**The script ships no taxonomy of its own.** Every category, its colour and its wording live in the
`categories` file next to it, and the report is built from that. Change the file, and the next
report follows. Delete it, and the report simply drops the category column.

```sh
# <category> <regex>            classify a domain; the FIRST match wins
# @color <category> <light> [dark]
# @about <category> <text>      the sentence shown in the legend

@color ads        #eb6834 #d95926
@about ads        ad exchanges and ad SDKs
ads               doubleclick|googleads|applovin|criteo|openx|(^|\.)ads?[.-]
```

A line whose first non-blank character is `#` is a comment. Anywhere else a `#` belongs to the
value, so a regex or a colour can hold one. The regex is case insensitive and it is tested against
the whole domain.

The file that ships with the project carries 18 categories:

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

The rules are an **ordered list and the first match wins**, so the order of the lines is the
specification: `logs.ads.vungle.com` is `ads`, not `telemetry`, because the `ads` line comes first.
Hovering a category in the table shows the rule that chose it, and the detail panel writes it out —
that is how a wrong category gets found and corrected.

Four categories are coloured: `ads` orange, `acr` aqua, and `tracking` and `telemetry` sharing the
blue, because they mean the same thing — data about the device leaving the network. Three hues is
what clears the colour-blindness and contrast checks on both surfaces, so every other category keeps
a neutral dot and relies on its written name. A category with no `@color` is neutral, which scales
to any number of categories.

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

The shipped rules are opinions, not facts: they were written against one home network and they will
put some domain in the wrong box on yours. That is what the rule shown on hover is for. A pull
request that fixes a rule, or adds a category, is welcome.

### The Whois button

It asks [rdap.org](https://rdap.org) for the **registrable** name (`eic.service.lgtvcommon.com` →
`lgtvcommon.com`) and shows the registrar, the registration date with the age of the domain, the
expiry and the name servers. RDAP is the successor of whois: it answers JSON and it sends
`Access-Control-Allow-Origin: *`, so the page reads it with no API key and no proxy.

The call happens **only when you press the button** — opening the report sends nothing. A young
domain behind a privacy-proxy registrar is a useful signal next to a name you do not know.

Some registries answer nothing useful to a browser (`.de` and `.it` among them). The panel then
says so and gives you the link to open the answer yourself.

## Authentication

`pihole-peek` asks `GET /api/auth` first and adapts:

* **no password** — nothing to do, the API answers `"no password set"`.
* **password** — put it in `PIHOLE_PASSWORD`, in the environment or in the config file. An **app
  password** (*Settings → Web interface / API*) is the better choice: it is revocable and it does
  not unlock the web interface.
* **two-factor** — add `--totp 123456`.
* **HTTPS with a self-signed certificate** — add `--insecure`.

The session is opened for the single run and closed with `DELETE /api/auth` when the script ends,
so it does not eat a session slot.

## Large windows

The API returns **at most 10000 queries per request**, whatever `length` asks for, and it does not
say so: `recordsFiltered` keeps reporting the real total. `pihole-peek` therefore walks the window
page by page with the `start` parameter and reduces each page as it arrives, so the result covers
every query in the range.

Memory does not grow with the window. The bash script writes each page to a temporary file and
never into a shell variable; the Python script throws away every field it does not need while the
page is still being parsed. Both then hold one entry per domain — a few thousand — instead of one
per query, so a day of traffic and a week of traffic cost the same.

Measured on a week of real traffic, 57755 queries in six requests: the bash script peaks at
**34 MB** and the Python one at **45 MB**, of which 22 MB is the interpreter itself. Under
`ulimit -v` they still finish inside 48 MB and 64 MB. On a window of 300000 queries the bash script
stays inside 64 MB; keeping the same data in memory as one JSON document, which is what version
2.1.0 did, needs more than 512 MB.

If a run still feels heavy on a very small machine, `--page-size 2000` makes each request smaller.
The count of pages goes up, the peak goes down — to 12 MB for the bash script and 30 MB for the
Python one.

When the pages do not add up to `recordsFiltered` — new queries can land while a long run is in
flight — the script says so on stderr rather than reporting a short total in silence.

## The 24-hour limit

By default the API refuses to look further back than 24 hours, whatever `--since` says, because of
`webserver.api.maxHistory`. The long-term database usually holds much more. Raise the limit — one
week in this example:

```sh
curl -X PATCH http://pihole.example.lan/api/config \
  -H 'content-type: application/json' \
  -d '{"config":{"webserver":{"api":{"maxHistory":604800}}}}'
```

Or set `maxHistory` in `/etc/pihole/pihole.toml` and restart FTL. How far the data really goes back
is the `earliest_timestamp_disk` field of a `--format raw` answer.

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
| **2.4.0** | `--client-names` writes each client's DHCP/DNS name in place of its address, in the CLIENT column and in the HTML report's client filter, and falls back to the address for a client the Pi-hole has no name for. Off by default, so nothing that reads the `client` field of the csv or the json changes until you ask for it. Rows are still grouped by address, so two clients with no name stay apart. Thanks to [@gbarwis](https://github.com/gbarwis). |
| 2.3.1 | `pihole-peek.py` no longer stops on a byte that is not valid UTF-8. A malformed DNS query can make FTL log one, and strict decoding then ended a whole run of a hundred thousand queries with `UnicodeDecodeError`. The byte becomes `U+FFFD` in that one domain instead, which is what the bash script has always done through `jq`. Thanks to [@gbarwis](https://github.com/gbarwis). The `count` table also lines its columns up the same way in both scripts when a domain is not plain ASCII. |
| 2.3.0 | `pihole-peek.py`: a Python port that needs no `jq` and runs on Windows as it is. Four fixes in the bash script — rows tied on hits and domain now come out in the same order on every `awk`; `-f count` no longer starts `date` once per row, which made that format three times faster; the environment now wins over the config file for every documented variable, as the help text always promised; `@color` and `@about` in `categories.local` now win over the shipped file, as its rules already did. |
| 2.2.0 | Reads the whole window. Earlier versions stopped at the 10000 queries the API returns per request, and reported the short total in silence. |
| 2.1.0 | Runs on a stock macOS: no `bash` 4, no GNU `date`. |

## License

MIT — see [LICENSE](LICENSE).
