# pihole-peek

A small shell tool that asks the **Pi-hole v6 REST API** which domains a client resolved, and
groups the answer by domain. It tells you what a device on your network talks to — the smart TV
that phones home, the phone that runs an ad SDK, the IoT box that never stops — and it exports the
result as a table, a plain domain list, CSV, JSON or a self-contained **HTML report** with live
filters, sortable columns and a per-domain look-up.

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

`bash` 3.2 or later, `curl`, and `jq` 1.6 or later (it uses `$ARGS.named`). It runs on a stock
macOS install. With GNU `date` (Linux, or Homebrew `coreutils`) the `--since` and `--until`
options take anything `date -d` understands; with BSD `date` they take `YYYY-MM-DD`, optionally
followed by ` HH:MM` or ` HH:MM:SS`, or `@EPOCH`.

**Tested on Pi-hole core v6.4.3 with FTL v6.7.** That is the only build it has been run against. The
v6 API is stable across the 6.x line, so other builds should work, but if one does not, open an
issue with the output of `pihole-peek -f raw | jq '.queries[0]'` and the version the Pi-hole reports
at `/api/info/version`.

## Install

```sh
git clone https://github.com/nightwatch75/pihole-peek.git
cd pihole-peek
ln -s "$PWD/pihole-peek" ~/.local/bin/pihole-peek     # any directory in your PATH
```

The script follows its own symlink, so the `config` and `categories` files next to the real script
are always found.

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
#PIHOLE_FORMAT="count"
#PIHOLE_INSECURE="0"
```

`config` is in `.gitignore`: your address and your password stay on your machine.
If the config file sets a default client, `--all-clients` puts the report back on every client.

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
| `--since TS` | — | — | absolute start, in any format GNU `date -d` reads |
| `--until TS` | — | now | absolute end |
| `-d`, `--domain REGEX` | — | — | keep only the domains that match the regex (case insensitive) |
| `-n`, `--top N` | — | every row | keep only the first N rows |
| `-f`, `--format FMT` | `PIHOLE_FORMAT` | `count` | `count`, `list`, `csv`, `json`, `html` or `raw` |
| `--categories F` | `PIHOLE_PEEK_CATEGORIES` | a file named `categories` next to the script | the category rules of the HTML report; the rules in `F.local` are read first and win |
| `--list-clients` | — | — | list the clients the Pi-hole knows, with their query count, and exit |
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

**`raw`** — the API answer with no processing, for your own `jq`. Every field is there: query type,
upstream, reply time, DNSSEC state, CNAME chain.

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

## License

MIT — see [LICENSE](LICENSE).
