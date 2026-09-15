#!/usr/bin/env python3
#
# pihole-peek — report the DNS queries of a Pi-hole v6 client, grouped by domain.
# https://github.com/nightwatch75/pihole-peek
# SPDX-License-Identifier: MIT
#
# A port of the shell script to the Python standard library: same options, same
# output, and nothing to install — no curl, no jq, no awk, no GNU date.

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = "2.3.0"
PROG = os.path.basename(sys.argv[0]) or "pihole-peek"
SELF = os.path.realpath(os.path.abspath(__file__))
SELF_DIR = os.path.dirname(SELF)


def die(msg, code=1):
    sys.stderr.write("%s: %s\n" % (PROG, msg))
    sys.exit(code)


# --------------------------------------------------------------------------
# JSON that keeps the numbers as the API wrote them
#
# FTL prints every timestamp with 17 significant digits (1789140988.3536811).
# Python prints the shortest text that reads back as the same double
# (1789140988.353681), so a report made here would not match the one the shell
# script makes, although the instant is the same. Lit keeps the original text,
# and the two writers below print it back unchanged.
# --------------------------------------------------------------------------
class Lit(str):
    """A JSON number, kept as the text it arrived in."""
    __slots__ = ()


def _safe_text(raw):
    """Bytes from the API, decoded leniently.

    A malformed DNS query can make FTL log bytes that are not valid UTF-8,
    and the JSON response carries them as-is. json.loads() on bytes decodes
    strictly and would abort a whole run over one bad byte among tens of
    thousands of queries; swap the invalid bytes for U+FFFD instead.
    """
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", "replace")
    return raw


def jload(data):
    return json.loads(_safe_text(data), parse_float=Lit)


def _query_hook(pairs):
    """Keep four fields of a query, drop the rest before it is ever built.

    json.loads would otherwise make one dict per query and three more inside it
    (reply, client, ede): ten thousand of those, the size of a page, live at
    once. This hook runs on every object the parser finishes, so a query leaves
    it as a four-item tuple and nothing else is kept. A page then costs its own
    text, not a tree.
    """
    dom = st = t = None
    ip = ""
    for k, v in pairs:
        if k == "domain":
            dom = v
        elif k == "status":
            st = v
        elif k == "time":
            t = v
        elif k == "client":
            ip = (v or {}).get("ip") or ""
    if dom is None:
        return dict(pairs)          # reply, client, ede, or the page itself
    return (dom, ip, st, t)


def jload_queries(data):
    return json.loads(_safe_text(data), parse_float=Lit, object_pairs_hook=_query_hook)


def _jstr(s):
    return json.dumps(s, ensure_ascii=False)


def jcompact(v, out):
    """Write v with no spaces, like `jq -c`."""
    if isinstance(v, Lit):
        out.append(str(v))
    elif isinstance(v, str):
        out.append(_jstr(v))
    elif v is True:
        out.append("true")
    elif v is False:
        out.append("false")
    elif v is None:
        out.append("null")
    elif isinstance(v, dict):
        out.append("{")
        first = True
        for k, val in v.items():
            if not first:
                out.append(",")
            first = False
            out.append(_jstr(k))
            out.append(":")
            jcompact(val, out)
        out.append("}")
    elif isinstance(v, (list, tuple)):
        out.append("[")
        first = True
        for val in v:
            if not first:
                out.append(",")
            first = False
            jcompact(val, out)
        out.append("]")
    else:
        out.append(repr(v) if isinstance(v, float) else str(v))
    return out


def jpretty(v, out, level=0):
    """Write v with two-space indents, like `jq .`."""
    pad = "  " * level
    if isinstance(v, dict):
        if not v:
            out.append("{}")
            return out
        out.append("{\n")
        items = list(v.items())
        for i, (k, val) in enumerate(items):
            out.append(pad + "  " + _jstr(k) + ": ")
            jpretty(val, out, level + 1)
            out.append(",\n" if i < len(items) - 1 else "\n")
        out.append(pad + "}")
    elif isinstance(v, (list, tuple)):
        if not v:
            out.append("[]")
            return out
        out.append("[\n")
        for i, val in enumerate(v):
            out.append(pad + "  ")
            jpretty(val, out, level + 1)
            out.append(",\n" if i < len(v) - 1 else "\n")
        out.append(pad + "]")
    else:
        jcompact(v, out)
    return out


# --------------------------------------------------------------------------
# dates. Only the portable formats: the shell script needs GNU date for the
# rest, and half the machines it runs on do not have one.
# --------------------------------------------------------------------------
def fmt_epoch(epoch, fmt="%Y-%m-%d %H:%M"):
    return datetime.fromtimestamp(float(epoch)).strftime(fmt)


def parse_date(s):
    """Return the epoch of a date string, or None."""
    s = s.strip()
    if s.startswith("@"):
        try:
            return int(float(s[1:]))
        except ValueError:
            return None
    try:
        return int(datetime.fromisoformat(s.replace("T", " ")).timestamp())
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# status groups
# --------------------------------------------------------------------------
BLOCKED_SET = ["GRAVITY", "GRAVITY_CNAME", "DENYLIST", "DENYLIST_CNAME",
               "REGEX", "REGEX_CNAME", "EXTERNAL_BLOCKED_IP",
               "EXTERNAL_BLOCKED_NULL", "EXTERNAL_BLOCKED_NXRA",
               "EXTERNAL_BLOCKED_EDE15", "SPECIAL_DOMAIN"]
ALLOWED_SET = ["FORWARDED", "RETRIED", "RETRIED_DNSSEC"]
CACHED_SET = ["CACHE", "CACHE_STALE"]
KNOWN_SET = BLOCKED_SET + ALLOWED_SET + CACHED_SET + ["UNKNOWN", "IN_PROGRESS", "DBBUSY"]

USAGE = """{prog} {version} — report the DNS queries of a Pi-hole v6 client, grouped by domain.

Usage:
  {prog} [options]

Options:
  -u, --url URL        Pi-hole base URL, e.g. http://pihole.lan or
                       https://pihole.lan:8443 (the API is at URL/api)
  -c, --client ADDR    client IP or hostname; without it every client is
                       reported and a CLIENT column is added
  -a, --all-clients    report every client, even if the config file or the
                       environment sets a default client
  -A, --alias NAME     friendly name of the client, written next to its address
                       in the html report (needs --client)
  -s, --status SET     all (default) | blocked | allowed | cached,
                       or a comma separated list of FTL statuses
                       (e.g. GRAVITY,DENYLIST)
  -t, --hours N        time window, hours back from now (default: 24)
      --since TS       absolute start: YYYY-MM-DD[ HH:MM[:SS]] or @EPOCH
      --until TS       absolute end (default: now)
  -d, --domain REGEX   keep only the domains that match REGEX
  -n, --top N          keep only the first N rows
      --page-size N    queries per API request (default: 10000, the server cap;
                       lower it on a small box to use less memory)
  -f, --format FMT     count (default) | list | csv | json | html | raw
      --categories F   category rules for the html report (default: a file named
                       'categories' next to this script; the rules in F.local,
                       when it exists, are tried first and win)
      --list-clients   list the clients known to the Pi-hole and exit
  -k, --insecure       accept a self-signed TLS certificate
      --totp CODE      two-factor code, if the Pi-hole asks for it
  -V, --version        print the version and exit
  -h, --help           print this help and exit

Environment:
  PIHOLE_URL           same as --url
  PIHOLE_CLIENT        same as --client
  PIHOLE_ALIAS         same as --alias
  PIHOLE_PASSWORD      web password or app password (no flag, to keep it out
                       of the shell history)
  PIHOLE_PEEK_CONFIG   path of the config file (default: a file named
                       'config' next to this script)
  PIHOLE_PEEK_CATEGORIES  same as --categories
  PIHOLE_PAGE_SIZE     same as --page-size

Precedence: command line > environment > config file.

Exit codes: 0 success · 1 error · 2 no query matches the filters.
"""


def usage(stream=sys.stdout):
    stream.write(USAGE.format(prog=PROG, version=VERSION))


# --------------------------------------------------------------------------
# the config file. The shell script sources it; here it is read, so a line
# that is not NAME=value is simply ignored and nothing in it can run.
# --------------------------------------------------------------------------
CONFIG_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def read_config(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = CONFIG_LINE.match(line)
                if not m:
                    continue
                key, val = m.group(1), m.group(2).strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                out[key] = val
    except OSError as e:
        die("cannot read %s: %s" % (path, e.strerror))
    return out


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Api:
    def __init__(self, base, insecure=False, timeout=60):
        self.base = base
        self.timeout = timeout
        self.sid = None
        ctx = ssl.create_default_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    def _open(self, url, method="GET", body=None):
        req = urllib.request.Request(url, data=body, method=method)
        if self.sid:
            req.add_header("sid", self.sid)
        if body is not None:
            req.add_header("content-type", "application/json")
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            # the Pi-hole answers 4xx with a JSON body that says why
            return e.read()
        except Exception as e:
            die("cannot reach %s — %s" % (self.base, e))

    @staticmethod
    def error_of(doc):
        if isinstance(doc, dict) and isinstance(doc.get("error"), dict):
            err = doc["error"]
            msg = err.get("message") or "error"
            hint = err.get("hint")
            return "%s (%s)" % (msg, hint) if hint else msg
        return None

    def get(self, path):
        raw = self._open(self.base + path)
        try:
            doc = jload(raw)
        except ValueError:
            die("%s does not answer like a Pi-hole v6 API (v5 is not supported)" % self.base)
        err = self.error_of(doc)
        if err:
            die("API: " + err)
        return doc

    def get_raw(self, path):
        """The bytes of an answer, checked for an error but not parsed twice."""
        raw = self._open(self.base + path)
        if raw[:40].lstrip()[:8] == b'{"error"':
            try:
                err = self.error_of(jload(raw))
            except ValueError:
                err = None
            die("API: " + (err or "the API refused the request"))
        return raw

    def authenticate(self, password, totp):
        raw = self._open(self.base + "/auth")
        try:
            doc = jload(raw)
        except ValueError:
            doc = None
        if not isinstance(doc, dict) or "session" not in doc:
            die("%s does not answer like a Pi-hole v6 API (v5 is not supported)" % self.base)
        if doc["session"].get("valid") is True:
            return                                  # the Pi-hole has no password
        if not password:
            die("this Pi-hole asks for a password: set PIHOLE_PASSWORD")
        body = {"password": password}
        if totp:
            body["totp"] = totp
        doc = jload(self._open(self.base + "/auth", "POST",
                               json.dumps(body).encode("utf-8")))
        sid = (doc.get("session") or {}).get("sid") if isinstance(doc, dict) else None
        if not sid:
            die("authentication failed: " + (self.error_of(doc) or "wrong password"))
        self.sid = sid

    def logout(self):
        if self.sid:
            try:
                self._open(self.base + "/auth", "DELETE")
            except SystemExit:
                pass
            self.sid = None


# --------------------------------------------------------------------------
# category rules. The script holds no taxonomy of its own: everything comes
# from the rules file, plus an optional "<file>.local" that is read first and
# wins: its rules are tried before the others, and its colours and wording
# replace them. A line whose first non-blank character is '#' is a comment; a
# '#' anywhere else belongs to the value, so a regex or a colour can hold one.
# --------------------------------------------------------------------------
RE_COLOR = re.compile(r"^@color[ \t]+(\S+)[ \t]+(#[0-9A-Fa-f]{3,8})(?:[ \t]+(#[0-9A-Fa-f]{3,8}))?$")
RE_ABOUT = re.compile(r"^@about[ \t]+(\S+)[ \t]+(.+)$")
RE_RULE = re.compile(r"^(\S+)[ \t]+(.+)$")


def rules_payload(base):
    colours, about, rules = {}, {}, []
    files = [f for f in (base + ".local", base) if os.access(f, os.R_OK)]
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n").rstrip("\r")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                line = line.strip()
                m = RE_COLOR.match(line)
                if m:
                    colours.setdefault(m.group(1), [m.group(2), m.group(3) or m.group(2)])
                    continue
                m = RE_ABOUT.match(line)
                if m:
                    about.setdefault(m.group(1), m.group(2))
                    continue
                if line.startswith("@"):
                    continue
                m = RE_RULE.match(line)
                if m:
                    rules.append([m.group(1), m.group(2)])
    return {"colours": colours, "about": about, "rules": rules}


# --------------------------------------------------------------------------
# options
# --------------------------------------------------------------------------
def parse_args(argv, cfg, env):
    def setting(name, default=""):
        v = env.get(name)
        if v:
            return v
        v = cfg.get(name)
        if v:
            return v
        return default

    o = {
        "url": setting("PIHOLE_URL"),
        "client": setting("PIHOLE_CLIENT"),
        "alias": setting("PIHOLE_ALIAS"),
        "password": setting("PIHOLE_PASSWORD"),
        "status": setting("PIHOLE_STATUS", "all"),
        "hours": setting("PIHOLE_HOURS", "24"),
        "format": setting("PIHOLE_FORMAT", "count"),
        "insecure": setting("PIHOLE_INSECURE", "0") == "1",
        "page_size": setting("PIHOLE_PAGE_SIZE", "10000"),
        "categories": setting("PIHOLE_PEEK_CATEGORIES"),
        "since": "", "until": "", "domain": "", "top": "0",
        "list_clients": False, "totp": "",
    }

    def value(flag, args, allow_empty=False):
        if not args:
            die("%s needs a value" % flag)
        v = args.pop(0)
        if not v and not allow_empty:
            die("%s needs a value" % flag)
        return v

    args = list(argv)
    while args:
        a = args.pop(0)
        if a in ("-u", "--url"):
            o["url"] = value(a, args)
        elif a in ("-c", "--client"):
            o["client"] = value(a, args, True)
        elif a in ("-a", "--all-clients"):
            o["client"] = ""
            o["alias"] = ""
        elif a in ("-A", "--alias"):
            o["alias"] = value(a, args, True)
        elif a in ("-s", "--status"):
            o["status"] = value(a, args)
        elif a in ("-t", "--hours"):
            o["hours"] = value(a, args)
        elif a == "--since":
            o["since"] = value(a, args)
        elif a == "--until":
            o["until"] = value(a, args)
        elif a in ("-d", "--domain"):
            o["domain"] = value(a, args)
        elif a in ("-n", "--top"):
            o["top"] = value(a, args)
        elif a == "--page-size":
            o["page_size"] = value(a, args)
        elif a in ("-f", "--format"):
            o["format"] = value(a, args)
        elif a == "--categories":
            o["categories"] = value(a, args)
        elif a == "--list-clients":
            o["list_clients"] = True
        elif a in ("-k", "--insecure"):
            o["insecure"] = True
        elif a == "--totp":
            o["totp"] = value(a, args)
        elif a in ("-V", "--version"):
            sys.stdout.write("%s %s\n" % (PROG, VERSION))
            sys.exit(0)
        elif a in ("-h", "--help"):
            usage()
            sys.exit(0)
        elif a == "--":
            break
        else:
            usage(sys.stderr)
            die("unknown option: " + a)
    return o


def resolve_status(want):
    low = want.lower()
    if low == "blocked":
        return list(BLOCKED_SET)
    if low in ("allowed", "forwarded"):
        return list(ALLOWED_SET)
    if low == "cached":
        return list(CACHED_SET)
    if low == "all":
        return []
    out = []
    for s in want.replace(",", " ").split():
        s = s.upper()
        if s not in KNOWN_SET:
            die("unknown status: %s (try: blocked, allowed, cached, all, or an FTL status)" % s)
        out.append(s)
    return out


# --------------------------------------------------------------------------
# read the window
#
# The API answers with at most 10000 queries per request, whatever `length`
# asks for, and says nothing about it: recordsFiltered still reports the real
# total. So walk the window page by page with `start`, and fold every page into
# the aggregate as it arrives. What is kept is bounded by the number of
# distinct domains, not by the number of queries, so a week of traffic costs
# the same memory as an hour.
# --------------------------------------------------------------------------
def collect(api, query, want, domain_re, byclient, page_size, raw_out):
    agg = {}
    wanted = set(want)
    rx = re.compile(domain_re, re.I) if domain_re else None
    total = None
    got = 0
    tty = sys.stderr.isatty()
    start = 0
    while True:
        rawd = api.get_raw("%s&length=%d&start=%d" % (query, page_size, start))
        page = json.loads(_safe_text(rawd)) if raw_out else jload_queries(rawd)
        if total is None:
            total = page.get("recordsFiltered")
            if not isinstance(total, int):
                die("the API answered without recordsFiltered — is %s really a Pi-hole v6?" % api.base)
        queries = page.get("queries") or []
        n = len(queries)

        if raw_out:
            # raw means raw: the bytes the API sent, not a reformat of them
            sys.stdout.buffer.write(rawd)
            sys.stdout.buffer.write(b"\n")
        else:
            for dom, ip, st, t in queries:
                if wanted and st not in wanted:
                    continue
                if rx is not None and not rx.search(dom):
                    continue
                key = (dom, ip) if byclient else dom
                tf = float(t)
                e = agg.get(key)
                if e is None:
                    agg[key] = [dom, ip, 1, {st}, tf, t, tf, t]
                else:
                    e[2] += 1
                    e[3].add(st)
                    if tf < e[4]:
                        e[4], e[5] = tf, t
                    elif tf > e[6]:
                        e[6], e[7] = tf, t

        got += n
        if tty and total > page_size:
            sys.stderr.write("\r%s: reading %d of %d queries..." % (PROG, got, total))
            sys.stderr.flush()
        if n < page_size or got >= total:
            break
        start += page_size

    if tty and total > page_size:
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()
    if got != total:
        sys.stderr.write("%s: read %d queries but the API counted %d — the window may have moved\n"
                         % (PROG, got, total))
    return agg


def to_rows(agg, byclient):
    rows = []
    for e in agg.values():
        rows.append({
            "domain": e[0],
            "client": e[1] if byclient else None,
            "hits": e[2],
            "status": "|".join(sorted(e[3])),
            "first": e[5],
            "last": e[7],
        })
    # the client is part of the key: without it, rows tied on hits and domain
    # come out in whatever order the aggregate was walked in
    rows.sort(key=lambda r: (-r["hits"], r["domain"], r["client"] or ""))
    return rows


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def todate(epoch):
    return datetime.fromtimestamp(int(float(epoch)), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def csv_field(v):
    if isinstance(v, int):
        return str(v)
    return '"%s"' % str(v).replace('"', '""')


def render_count(rows, byclient, client, status, window, out):
    if byclient:
        out.write("%-52s %-16s %7s  %s\n" % ("DOMAIN", "CLIENT", "HITS", "LAST SEEN"))
    else:
        out.write("%-52s %7s  %s\n" % ("DOMAIN", "HITS", "LAST SEEN"))
    for r in rows:
        seen = fmt_epoch(str(r["last"]).split(".")[0])
        if byclient:
            out.write("%-52s %-16s %7s  %s\n" % (r["domain"], r["client"] or "-", r["hits"], seen))
        else:
            out.write("%-52s %7s  %s\n" % (r["domain"], r["hits"], seen))
    ndom = len(set(r["domain"] for r in rows))
    nhit = sum(r["hits"] for r in rows)
    out.write("\n%s · %s · %d domain%s · %d quer%s · %s\n"
              % (client or "all clients", status,
                 ndom, "" if ndom == 1 else "s",
                 nhit, "y" if nhit == 1 else "ies", window))


def render(fmt, rows, byclient, o, window, url, out):
    if fmt == "list":
        for d in sorted(set(r["domain"] for r in rows)):
            out.write(d + "\n")
    elif fmt == "json":
        doc = []
        for r in rows:
            if byclient:
                doc.append({"domain": r["domain"], "client": r["client"], "hits": r["hits"],
                            "status": r["status"], "last_seen": todate(r["last"])})
            else:
                doc.append({"domain": r["domain"], "hits": r["hits"],
                            "status": r["status"], "last_seen": todate(r["last"])})
        out.write("".join(jpretty(doc, [])))
        out.write("\n")
    elif fmt == "csv":
        if byclient:
            out.write("domain,client,hits,status,last_seen\n")
            for r in rows:
                out.write(",".join(csv_field(v) for v in
                                   (r["domain"], r["client"], r["hits"], r["status"],
                                    todate(r["last"]))) + "\n")
        else:
            out.write("domain,hits,status,last_seen\n")
            for r in rows:
                out.write(",".join(csv_field(v) for v in
                                   (r["domain"], r["hits"], r["status"],
                                    todate(r["last"]))) + "\n")
    elif fmt == "html":
        cats = o["categories"] or os.path.join(SELF_DIR, "categories")
        meta = {
            "host": url, "window": window, "status": o["status"],
            "client": o["client"], "alias": o["alias"], "domain": o["domain"],
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "version": VERSION, "categories": cats,
        }
        data = []
        for r in rows:
            data.append({"domain": r["domain"], "client": r["client"], "hits": r["hits"],
                         "status": r["status"], "first": r["first"], "last": r["last"]})
        out.write(HTML_HEAD)
        out.write("const DATA = %s;\n" % "".join(jcompact(data, [])))
        out.write("const META = %s;\n" % "".join(jcompact(meta, [])))
        out.write("const TAXONOMY = %s;\n" % "".join(jcompact(rules_payload(cats), [])))
        out.write(HTML_TAIL)
    else:
        render_count(rows, byclient, o["client"], o["status"], window, out)


# --------------------------------------------------------------------------
def main():
    # Windows would write CRLF and encode the page in the console code page,
    # which breaks the · and — the report is full of. Ask for the bytes the
    # other two systems already write.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass

    env = os.environ
    cfg_path = env.get("PIHOLE_PEEK_CONFIG") or os.path.join(SELF_DIR, "config")
    cfg = read_config(cfg_path) if os.path.isfile(cfg_path) else {}
    o = parse_args(sys.argv[1:], cfg, env)

    url = o["url"]
    if not url:
        usage(sys.stderr)
        die("no Pi-hole address: use --url, PIHOLE_URL or the config file")
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "http://" + url
    url = url.rstrip("/")
    if url.endswith("/admin"):
        url = url[:-6]

    if not o["hours"].isdigit():
        die("--hours needs a whole number: " + o["hours"])
    if not o["top"].isdigit():
        die("--top needs a whole number: " + o["top"])
    if not o["page_size"].isdigit() or int(o["page_size"]) <= 0:
        die("--page-size needs a whole number above zero: " + o["page_size"])
    if o["format"] not in ("count", "list", "csv", "json", "html", "raw"):
        die("unknown format: " + o["format"])
    if o["alias"] and not o["client"]:
        die("--alias names one client, so it needs --client too")

    api = Api(url + "/api", o["insecure"])
    try:
        api.authenticate(o["password"], o["totp"])

        if o["list_clients"]:
            doc = api.get("/stats/top_clients?count=1000&blocked=false")
            out = sys.stdout
            out.write("CLIENT           NAME                           QUERIES\n")
            for c in doc.get("clients") or []:
                ip = c.get("ip") or ""
                name = c.get("name") or "-"
                out.write("%s%s%s%s%s\n" % (ip, " " * max(1, 17 - len(ip)),
                                            name, " " * max(1, 31 - len(name)), c.get("count")))
            return 0

        want = resolve_status(o["status"])

        now = int(datetime.now().timestamp())
        if o["until"]:
            to = parse_date(o["until"])
            if to is None:
                die("--until is not a readable date: " + o["until"])
        else:
            to = now
        if o["since"]:
            frm = parse_date(o["since"])
            if frm is None:
                die("--since is not a readable date: " + o["since"])
            window = "from %s to %s" % (fmt_epoch(frm), fmt_epoch(to))
        else:
            frm = to - int(o["hours"]) * 3600
            window = "last %s h" % o["hours"]
        if frm >= to:
            die("the time window is empty: --since is not before --until")

        query = "/queries?from=%d&until=%d" % (frm, to)
        if o["client"]:
            query += "&client_ip=" + urllib.parse.quote(o["client"], safe="")
        if len(want) == 1:
            query += "&status=" + want[0]

        byclient = not (o["client"] and o["format"] != "html")
        raw_out = o["format"] == "raw"

        agg = collect(api, query, want, o["domain"], byclient,
                      int(o["page_size"]), raw_out)
        if raw_out:
            return 0
    finally:
        api.logout()

    rows = to_rows(agg, byclient)
    if int(o["top"]) > 0:
        rows = rows[:int(o["top"])]
    if not rows:
        sys.stderr.write("%s: no query matches the filters (%s)\n" % (PROG, window))
        return 2

    render(o["format"], rows, byclient, o, window, url, sys.stdout)
    return 0


# --------------------------------------------------------------------------
# the report page: one self-contained file, no CDN, no network until you click.
# The two blocks below are the PEEK_HTML_HEAD and PEEK_HTML_TAIL heredocs of
# the shell script, character for character, so both tools write the same page.
# --------------------------------------------------------------------------
HTML_HEAD = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pihole-peek report</title>
<style>
:root {
  color-scheme: light;
  --surface:      #fcfcfb;
  --card:         #ffffff;
  --line:         #e4e3df;
  --line-soft:    #efeeea;
  --ink:          #0b0b0b;
  --ink-2:        #52514e;
  --ink-3:        #86847d;
  --accent:       #2a78d6;
  --cat-ads:      #eb6834;
  --cat-tel:      #2a78d6;
  --cat-acr:      #1baf7a;
  --cat-none:     #86847d;
  --bar:          #2a78d6;
  --bar-track:    #efeeea;
  --shadow:       0 1px 2px rgba(11,11,11,.06), 0 4px 16px rgba(11,11,11,.04);
  /* status palette: fixed, never themed - it means state, not identity */
  --st-blocked:   #d03b3b;
  --st-forwarded: #0ca30c;
  --st-mixed:     #fab219;
  --st-quiet:     #86847d;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface:    #1a1a19;
    --card:       #232322;
    --line:       #35342f;
    --line-soft:  #2b2b29;
    --ink:        #ffffff;
    --ink-2:      #c3c2b7;
    --ink-3:      #8f8e85;
    --accent:     #3987e5;
    --cat-ads:    #d95926;
    --cat-tel:    #3987e5;
    --cat-acr:    #199e70;
    --cat-none:   #8f8e85;
    --bar:        #3987e5;
    --bar-track:  #2b2b29;
    --shadow:     0 1px 2px rgba(0,0,0,.4), 0 4px 16px rgba(0,0,0,.25);
    --st-quiet:   #8f8e85;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface:    #1a1a19;
  --card:       #232322;
  --line:       #35342f;
  --line-soft:  #2b2b29;
  --ink:        #ffffff;
  --ink-2:      #c3c2b7;
  --ink-3:      #8f8e85;
  --accent:     #3987e5;
  --cat-ads:    #d95926;
  --cat-tel:    #3987e5;
  --cat-acr:    #199e70;
  --cat-none:   #8f8e85;
  --bar:        #3987e5;
  --bar-track:  #2b2b29;
  --shadow:     0 1px 2px rgba(0,0,0,.4), 0 4px 16px rgba(0,0,0,.25);
  --st-quiet:   #8f8e85;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--surface);
  color: var(--ink);
  font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1180px; margin: 0 auto; padding: 28px 16px 64px; }

header { display: flex; align-items: flex-start; gap: 16px; flex-wrap: wrap; margin-bottom: 22px; }
h1 { font-size: 19px; font-weight: 650; letter-spacing: -.01em; margin: 0 0 4px; }
h1 span { color: var(--ink-3); font-weight: 400; }
h1 .ver { font-size: 10.5px; font-weight: 500; color: var(--ink-3); letter-spacing: 0;
          vertical-align: super; margin-left: 3px; font-variant-numeric: tabular-nums; }
h1 em { font-style: normal; font-weight: 700; font-size: 1.08em; margin-left: 9px; letter-spacing: -.015em; }
#theme {
  width: 36px; height: 36px; padding: 0; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 15px; line-height: 1;
}
#theme:hover { background: var(--line-soft); }
#theme:active { transform: scale(.94); }
.meta { margin: 0; color: var(--ink-2); font-size: 12.5px; }
.meta b { font-weight: 550; color: var(--ink); }
.spacer { flex: 1 1 auto; }

button, select, input {
  font: inherit; color: inherit;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 7px 10px;
}
button { cursor: pointer; }
button:hover { border-color: var(--ink-3); }
.ghost { background: transparent; }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 18px; }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 13px 15px; box-shadow: var(--shadow); }
.kpi .n { font-size: 25px; font-weight: 620; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.kpi .l { color: var(--ink-3); font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; margin-top: 2px; }

.controls { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 14px; }
.controls input[type=search] { flex: 1 1 220px; min-width: 160px; }
.controls .count { color: var(--ink-3); font-size: 12.5px; margin-left: auto; font-variant-numeric: tabular-nums; }

.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow); overflow: hidden; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 810px; }
th, td { text-align: left; padding: 9px 14px; border-bottom: 1px solid var(--line-soft); vertical-align: middle; }
thead th {
  position: sticky; top: 0; z-index: 2;
  background: var(--card);
  border-bottom: 1px solid var(--line);
  font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em;
  color: var(--ink-3); white-space: nowrap; cursor: pointer; user-select: none;
}
thead th:hover { color: var(--ink); }
thead th .arrow { opacity: 0; font-size: 10px; }
thead th.sorted .arrow { opacity: 1; }
tbody tr { cursor: pointer; }
tbody tr:hover { background: var(--line-soft); }
tbody tr.open { background: var(--line-soft); }
td.dom { font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; font-size: 12.5px; word-break: break-all; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.time, td.client { color: var(--ink-2); font-size: 12.5px; white-space: nowrap; }
td.client { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

.chip { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; font-size: 12.5px; color: var(--ink-2); }
.st { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; font-size: 12.5px; color: var(--ink-2); }
.sw { display: inline-block; width: 11px; height: 11px; border-radius: 3px;
      flex: none; background: var(--st-quiet); }
.sw.blocked { background: var(--st-blocked); }
.sw.forwarded { background: var(--st-forwarded); }
.sw.mixed { background: var(--st-mixed); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
       background: var(--cat-none); flex: none; }

.hits { display: flex; align-items: center; justify-content: flex-end; gap: 9px; }
.bar { width: 74px; height: 6px; background: var(--bar-track); border-radius: 3px; overflow: hidden; flex: none; }
.bar i { display: block; height: 100%; background: var(--bar); border-radius: 0 3px 3px 0; }

tr.detail td { background: var(--surface); padding: 0; border-bottom: 1px solid var(--line); }
.panel { padding: 14px 16px 16px; display: grid; gap: 12px; }
.facts { display: flex; flex-wrap: wrap; gap: 8px 26px; font-size: 12.5px; color: var(--ink-2); }
.facts b { color: var(--ink); font-weight: 550; }
.links { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; }
.links a, .links button { font-size: 12.5px; padding: 5px 10px; border-radius: 7px; text-decoration: none; color: var(--ink-2); border: 1px solid var(--line); background: var(--card); }
.links a:hover, .links button:hover { color: var(--ink); border-color: var(--ink-3); }
.links .lbl { border: 0; background: none; color: var(--ink-3); padding-left: 0; font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; }
.whois { font-size: 12.5px; color: var(--ink-2); border-left: 2px solid var(--line); padding-left: 12px; min-height: 0; }
.whois b { color: var(--ink); font-weight: 550; }
.whois .err { color: var(--ink-3); }

.legend { margin-top: 26px; background: var(--card); border: 1px solid var(--line);
          border-radius: 12px; box-shadow: var(--shadow); padding: 4px 18px 18px; }
.legend > summary { cursor: pointer; padding: 14px 0 12px; font-size: 13px; font-weight: 600;
                    letter-spacing: -.005em; list-style: none; }
.legend > summary::-webkit-details-marker { display: none; }
.legend > summary::before { content: "\25b8"; display: inline-block; width: 14px; color: var(--ink-3); }
.legend[open] > summary::before { transform: rotate(90deg); }
.legend h3 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em;
             color: var(--ink-3); margin: 16px 0 8px; font-weight: 600; }
.legend .cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 4px 34px; }
.legend table { border-collapse: collapse; width: 100%; min-width: 0; font-size: 12.5px; }
.legend td { padding: 4px 10px 4px 0; border: 0; vertical-align: baseline; color: var(--ink-2); }
.legend td.k { white-space: nowrap; color: var(--ink); font-weight: 550; }
.legend td.c { width: 1px; padding-right: 8px; }
.legend tr.off { opacity: .45; }
.legend .n { color: var(--ink-3); font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }
.legend p { font-size: 12.5px; color: var(--ink-2); margin: 14px 0 0; }
.legend code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.legend .warn { color: var(--st-blocked); }
footer { margin-top: 20px; color: var(--ink-3); font-size: 12px; }
footer a { color: var(--ink-2); }
.empty { padding: 40px 16px; text-align: center; color: var(--ink-3); }
@media (max-width: 560px) { .wrap { padding: 18px 12px 48px; } h1 { font-size: 17px; } }
</style>
</head>
<body>
<div class="wrap">

<header>
  <div>
    <h1>pihole-peek<span class="ver" id="h-ver"></span> <span id="h-sub"></span></h1>
    <p class="meta" id="h-meta"></p>
  </div>
  <div class="spacer"></div>
  <button class="ghost" id="theme" aria-label="Switch the theme"></button>
</header>

<section class="kpis">
  <div class="kpi"><div class="n" id="k-queries">0</div><div class="l">Queries</div></div>
  <div class="kpi"><div class="n" id="k-domains">0</div><div class="l">Domains</div></div>
  <div class="kpi"><div class="n" id="k-clients">0</div><div class="l">Clients</div></div>
  <div class="kpi"><div class="n" id="k-blocked">-</div><div class="l">Blocked</div></div>
  <div class="kpi" id="kpi-cat"><div class="n" id="k-top">-</div><div class="l">Main category</div></div>
</section>

<div class="controls">
  <input type="search" id="q" placeholder="Filter the domains..." autocomplete="off">
  <select id="f-client"></select>
  <select id="f-cat"></select>
  <select id="f-status"></select>
  <button class="ghost" id="reset">Reset</button>
  <button class="ghost" id="copy">Copy domains</button>
  <button class="ghost" id="csv">Download CSV</button>
  <span class="count" id="count"></span>
</div>

<div class="card">
  <div class="scroll">
    <table>
      <thead>
        <tr>
          <th data-k="domain">Domain <span class="arrow"></span></th>
          <th data-k="statusLabel">Status <span class="arrow"></span></th>
          <th data-k="category">Category <span class="arrow"></span></th>
          <th data-k="client">Client <span class="arrow"></span></th>
          <th data-k="hits" class="num" style="text-align:right">Hits <span class="arrow"></span></th>
          <th data-k="last">Last seen <span class="arrow"></span></th>
        </tr>
      </thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
  <div class="empty" id="empty" hidden>No domain matches the filters.</div>
</div>

<details class="legend" id="legend" open>
  <summary>Legend — what the columns mean</summary>
  <div class="cols">
    <div>
      <h3>Status — what the Pi-hole did with the query</h3>
      <table id="lg-status"></table>
    </div>
    <div>
      <h3>Category — what the domain is</h3>
      <table id="lg-cats"></table>
    </div>
  </div>
  <p id="lg-note"></p>
</details>

<footer>
  Generated by <a href="https://github.com/nightwatch75/pihole-peek">pihole-peek</a>
  <span id="f-ver"></span>. The category is guessed locally from the domain name; Whois asks
  <a href="https://rdap.org">rdap.org</a> only when you click it.
</footer>

</div>
<script>
"""

HTML_TAIL = r"""</script>
<script>
"use strict";

/* ---- category rules: first match wins; the label is always shown, the colour
   is only a second encoding for the three groups that matter on a home network. */
/* The taxonomy is data, not code: rules, colours and wording all come from the
   categories file. With no file the report simply drops the category column. */
const RULE_ERRORS = [];
const RULES = (TAXONOMY.rules || []).map(([name, src]) => {
  try { return [name, new RegExp(src, "i"), src]; }
  catch (e) { RULE_ERRORS.push(name + " " + src + " — " + e.message); return null; }
}).filter(Boolean);
const ABOUT = TAXONOMY.about || {};
const COLOURS = TAXONOMY.colours || {};
const HAS_CATS = RULES.length > 0;
const CATS = [...new Set([...RULES.map(r => r[0]), "other"])];

/* one <style> for the category dots, so a colour in the file reaches both themes */
function paintCategories() {
  const safe = /^[A-Za-z0-9_-]+$/, hex = /^#[0-9A-Fa-f]{3,8}$/;
  const css = Object.keys(COLOURS).map(c => {
    const [light, dark] = COLOURS[c];
    if (!safe.test(c) || !hex.test(light) || !hex.test(dark)) return "";
    const sel = '.dot[data-c="' + c + '"]';
    return sel + "{background:" + light + "}" +
      '@media (prefers-color-scheme: dark){:root:not([data-theme="light"])' + sel + "{background:" + dark + "}}" +
      ':root[data-theme="dark"]' + sel + "{background:" + dark + "}";
  }).join("");
  if (!css) return;
  const el = document.createElement("style");
  el.textContent = css;
  document.head.appendChild(el);
}

/* what every FTL status means, and which state it belongs to. The swatch is a
   second encoding only: the wording next to it always says what happened. */
const STATUS = {
  GRAVITY:                ["blocked",   "blocked · blocklist"],
  GRAVITY_CNAME:          ["blocked",   "blocked · CNAME in a blocklist"],
  DENYLIST:               ["blocked",   "blocked · your rule"],
  DENYLIST_CNAME:         ["blocked",   "blocked · CNAME of your rule"],
  REGEX:                  ["blocked",   "blocked · your regex"],
  REGEX_CNAME:            ["blocked",   "blocked · CNAME of your regex"],
  EXTERNAL_BLOCKED_IP:    ["blocked",   "blocked · by the upstream"],
  EXTERNAL_BLOCKED_NULL:  ["blocked",   "blocked · by the upstream"],
  EXTERNAL_BLOCKED_NXRA:  ["blocked",   "blocked · by the upstream"],
  EXTERNAL_BLOCKED_EDE15: ["blocked",   "blocked · by the upstream"],
  SPECIAL_DOMAIN:         ["blocked",   "blocked · special domain"],
  FORWARDED:              ["forwarded", "forwarded · asked the upstream"],
  RETRIED:                ["forwarded", "forwarded · retried"],
  RETRIED_DNSSEC:         ["forwarded", "forwarded · DNSSEC retry"],
  CACHE:                  ["cached",    "cached · answered locally"],
  CACHE_STALE:            ["cached",    "cached · stale answer"],
  IN_PROGRESS:            ["other",     "in progress"],
  DBBUSY:                 ["other",     "database busy"],
  UNKNOWN:                ["other",     "unknown"]
};
const KINDS = ["blocked", "forwarded", "cached", "mixed", "other"];

/* one sentence per FTL status, for the legend */
const STATUS_WHY = {
  GRAVITY:                "the domain is on one of your blocklists",
  GRAVITY_CNAME:          "the domain is clean, but its CNAME points to a blocked one",
  DENYLIST:               "one of your own exact rules stopped it",
  DENYLIST_CNAME:         "its CNAME target matches one of your own rules",
  REGEX:                  "one of your regular expressions stopped it",
  REGEX_CNAME:            "its CNAME target matches one of your regular expressions",
  EXTERNAL_BLOCKED_IP:    "the upstream resolver answered with a blocking address",
  EXTERNAL_BLOCKED_NULL:  "the upstream resolver answered 0.0.0.0 or ::",
  EXTERNAL_BLOCKED_NXRA:  "the upstream answered NXDOMAIN with no recursion available",
  EXTERNAL_BLOCKED_EDE15: "the upstream said “blocked” with EDNS error 15",
  SPECIAL_DOMAIN:         "a special-use domain the Pi-hole answers by itself",
  FORWARDED:              "the Pi-hole asked the upstream resolver",
  RETRIED:                "the query was sent again",
  RETRIED_DNSSEC:         "the query was sent again to validate DNSSEC",
  CACHE:                  "answered from the local cache, nothing left the network",
  CACHE_STALE:            "answered from an expired cache entry while it was refreshed",
  IN_PROGRESS:            "the same query was already on its way",
  DBBUSY:                 "the database was busy, the query was not stored",
  UNKNOWN:                "FTL did not classify it"
};

function statusOf(raw) {
  const parts = raw.split("|");
  const kinds = [...new Set(parts.map(p => (STATUS[p] || ["other"])[0]))];
  if (kinds.length > 1)
    return ["mixed", KINDS.filter(k => kinds.includes(k)).join(" + ")];
  if (parts.length === 1) return STATUS[parts[0]] || ["other", parts[0].toLowerCase()];
  /* same state, several reasons: name them all, e.g. blocked · blocklist + your rule */
  const why = [...new Set(parts.map(p => ((STATUS[p] || [, p.toLowerCase()])[1])
                                         .replace(/^[a-z]+ · /, "")))];
  return [kinds[0], kinds[0] + " · " + why.join(" + ")];
}


function classify(d) {
  for (const [name, re, src] of RULES) if (re.test(d)) return [name, "rule: /" + src + "/"];
  return ["other", "no rule matched this domain"];
}

/* registrable name: what Whois and Netify want, e.g. eic.x.lgtvcommon.com -> lgtvcommon.com */
const TWO_LEVEL = /\.(co|com|net|org|gov|edu|ac|or|ne|go)\.[a-z]{2}$/i;
function registrable(d) {
  const p = d.split(".");
  if (p.length <= 2) return d;
  return p.slice(TWO_LEVEL.test(d) ? -3 : -2).join(".");
}

const fmtN = n => n.toLocaleString();
const fmtT = t => {
  const d = new Date(t * 1000);
  return d.toLocaleString(undefined, { year: "numeric", month: "2-digit", day: "2-digit",
                                       hour: "2-digit", minute: "2-digit" });
};
const esc = s => String(s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---- state ---------------------------------------------------------- */
DATA.forEach(r => {
  [r.category, r.rule] = classify(r.domain);
  [r.kind, r.statusLabel] = statusOf(r.status);
});
let sortKey = "hits", sortDir = -1, openKey = null;

const $ = id => document.getElementById(id);
const rowKey = r => r.domain + "|" + (r.client || "");

function view() {
  const q = $("q").value.trim().toLowerCase();
  const c = $("f-client").value, k = $("f-cat").value, st = $("f-status").value;
  let rows = DATA.filter(r =>
    (!q || r.domain.toLowerCase().includes(q)) &&
    (!c || r.client === c) &&
    (!k || r.category === k) &&
    (!st || (st.startsWith("kind:") ? r.kind === st.slice(5) : r.status.split("|").includes(st))));
  const dir = sortDir;
  rows.sort((a, b) => {
    let x = a[sortKey], y = b[sortKey];
    if (typeof x === "string") { const o = x.localeCompare(y); return o ? o * dir * -1 : 0; }
    return (x - y) * dir;
  });
  return rows;
}

function render() {
  const rows = view();
  const tbody = $("rows");
  const max = rows.reduce((m, r) => Math.max(m, r.hits), 0) || 1;
  tbody.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    const key = rowKey(r);
    tr.dataset.key = key;
    if (key === openKey) tr.className = "open";
    tr.innerHTML =
      '<td class="dom">' + esc(r.domain) + '</td>' +
      '<td><span class="st" title="' + esc(r.status) + '"><span class="sw ' + r.kind + '"></span>' +
        esc(r.statusLabel) + '</span></td>' +
      (HAS_CATS ? '<td><span class="chip" title="' + esc(r.rule) + '"><span class="dot" data-c="' +
        esc(r.category) + '"></span>' + esc(r.category) + "</span></td>" : "") +
      '<td class="client">' + esc(r.client || "-") + '</td>' +
      '<td class="num"><span class="hits"><span class="bar"><i style="width:' +
        Math.max(2, Math.round(r.hits / max * 100)) + '%"></i></span>' + fmtN(r.hits) + '</span></td>' +
      '<td class="time">' + fmtT(r.last) + '</td>';
    tbody.appendChild(tr);
    if (key === openKey) tbody.appendChild(detailRow(r));
  }
  $("empty").hidden = rows.length > 0;
  $("count").textContent = fmtN(rows.length) + " of " + fmtN(DATA.length) + " rows · " +
                           fmtN(rows.reduce((s, r) => s + r.hits, 0)) + " queries";
  document.querySelectorAll("thead th").forEach(th => {
    const on = th.dataset.k === sortKey;
    th.classList.toggle("sorted", on);
    th.querySelector(".arrow").textContent = on ? (sortDir === -1 ? "▼" : "▲") : "";
  });
}

function detailRow(r) {
  const tr = document.createElement("tr");
  tr.className = "detail";
  const td = document.createElement("td");
  td.colSpan = HAS_CATS ? 6 : 5;
  const reg = registrable(r.domain), full = r.domain;
  td.innerHTML =
    '<div class="panel">' +
      '<div class="facts">' +
        '<span>first seen <b>' + fmtT(r.first) + '</b></span>' +
        '<span>last seen <b>' + fmtT(r.last) + '</b></span>' +
        '<span>queries <b>' + fmtN(r.hits) + '</b></span>' +
        '<span>status <b>' + esc(r.status) + '</b></span>' +
        '<span>registrable name <b>' + esc(reg) + '</b></span>' +
        (HAS_CATS ? '<span title="' + esc(r.rule) + '">category <b>' + esc(r.category) +
                    "</b> \u2014 " + esc(r.rule.length > 72 ? r.rule.slice(0, 70) + "\u2026/" : r.rule) +
                    "</span>" : "") +
      '</div>' +
      '<div class="links">' +
        '<span class="lbl">Look up</span>' +
        '<button data-whois="' + esc(reg) + '">Whois</button>' +
        '<a target="_blank" rel="noreferrer noopener" href="https://www.google.com/search?q=' + encodeURIComponent('"' + full + '"') + '">Google</a>' +
        '<a target="_blank" rel="noreferrer noopener" href="https://www.virustotal.com/gui/domain/' + encodeURIComponent(full) + '">VirusTotal</a>' +
        '<a target="_blank" rel="noreferrer noopener" href="https://urlscan.io/domain/' + encodeURIComponent(full) + '">urlscan.io</a>' +
        '<a target="_blank" rel="noreferrer noopener" href="https://www.netify.ai/resources/domains/' + encodeURIComponent(reg) + '">Netify</a>' +
        '<a target="_blank" rel="noreferrer noopener" href="https://crt.sh/?q=' + encodeURIComponent("%." + reg) + '">crt.sh</a>' +
      '</div>' +
      '<div class="whois" hidden></div>' +
    '</div>';
  tr.appendChild(td);
  return tr;
}

/* ---- Whois over RDAP: no key, no proxy, only when the button is pressed ---- */
async function whois(btn, name, box) {
  box.hidden = false;
  box.innerHTML = "asking rdap.org about <b>" + esc(name) + "</b>...";
  btn.disabled = true;
  try {
    const res = await fetch("https://rdap.org/domain/" + encodeURIComponent(name),
                            { headers: { accept: "application/rdap+json" } });
    if (res.status === 404) { box.innerHTML = '<span class="err">' + esc(name) + ' is not in any RDAP registry.</span>'; return; }
    if (!res.ok) throw new Error("HTTP " + res.status);
    const j = await res.json();
    const ev = {};
    (j.events || []).forEach(e => { ev[e.eventAction] = e.eventDate; });
    const rg = (j.entities || []).find(e => (e.roles || []).includes("registrar"));
    let rgName = "unknown";
    if (rg && Array.isArray(rg.vcardArray)) {
      const fn = rg.vcardArray[1].find(v => v[0] === "fn");
      if (fn) rgName = fn[3];
    }
    const day = d => d ? String(d).slice(0, 10) : "unknown";
    const ns = (j.nameservers || []).map(n => n.ldhName.toLowerCase());
    let age = "";
    if (ev.registration) {
      const years = (Date.now() - Date.parse(ev.registration)) / 31557600000;
      age = " (" + (years < 1 ? Math.round(years * 12) + " months" : years.toFixed(1) + " years") + " old)";
    }
    box.innerHTML =
      "registrar <b>" + esc(rgName) + "</b> · registered <b>" + day(ev.registration) + "</b>" + esc(age) +
      " · expires <b>" + day(ev.expiration) + "</b>" +
      (ev["last changed"] ? " · last change <b>" + day(ev["last changed"]) + "</b>" : "") +
      (ns.length ? "<br>name servers " + esc(ns.slice(0, 4).join(", ")) : "");
  } catch (e) {
    box.innerHTML = '<span class="err">RDAP did not answer (' + esc(e.message) +
      '). Some registries block the browser: <a target="_blank" rel="noreferrer noopener" href="https://rdap.org/domain/' +
      encodeURIComponent(name) + '">open the answer directly</a>.</span>';
  } finally {
    btn.disabled = false;
  }
}

/* ---- wiring --------------------------------------------------------- */
function fill(sel, label, values) {
  const el = $(sel);
  el.innerHTML = '<option value="">' + label + '</option>' +
    values.map(v => '<option value="' + esc(v) + '">' + esc(v) + "</option>").join("");
}

function init() {
  $("h-ver").textContent = "v" + META.version;
  $("h-sub").textContent = META.client ? "· " + META.client : "· all clients";
  if (META.alias) {
    const em = document.createElement("em");
    em.textContent = META.alias;
    $("h-sub").after(em);
    document.title = "pihole-peek · " + META.alias;
  } else if (META.client) {
    document.title = "pihole-peek · " + META.client;
  }
  $("h-meta").innerHTML =
    "<b>" + esc(META.host) + "</b> · " + esc(META.window) + " · status <b>" + esc(META.status) + "</b>" +
    (META.domain ? " · domain filter <b>" + esc(META.domain) + "</b>" : "") +
    " · generated " + esc(META.generated);
  $("f-ver").textContent = META.version;

  const clients = [...new Set(DATA.map(r => r.client).filter(Boolean))].sort();
  const cats = CATS.filter(c => DATA.some(r => r.category === c));
  const stats = [...new Set(DATA.flatMap(r => r.status.split("|")))].sort();
  const kinds = KINDS.filter(k => DATA.some(r => r.kind === k));
  fill("f-client", "All clients (" + clients.length + ")", clients);
  fill("f-cat", "All categories", cats);
  $("f-status").innerHTML =
    '<option value="">All statuses</option>' +
    '<optgroup label="State">' +
      kinds.map(k => '<option value="kind:' + k + '">' + k + "</option>").join("") +
    "</optgroup>" +
    '<optgroup label="Exact FTL status">' +
      stats.map(v => '<option value="' + esc(v) + '">' + esc(v) + "</option>").join("") +
    "</optgroup>";

  $("k-queries").textContent = fmtN(DATA.reduce((s, r) => s + r.hits, 0));
  $("k-domains").textContent = fmtN(new Set(DATA.map(r => r.domain)).size);
  $("k-clients").textContent = fmtN(clients.length);
  const byCat = {};
  DATA.forEach(r => { byCat[r.category] = (byCat[r.category] || 0) + r.hits; });
  const top = Object.entries(byCat).sort((a, b) => b[1] - a[1])[0];
  $("k-top").textContent = top ? top[0] : "-";
  const blocked = DATA.filter(r => r.kind === "blocked").reduce((s2, r) => s2 + r.hits, 0);
  const all = DATA.reduce((s2, r) => s2 + r.hits, 0);
  $("k-blocked").textContent = all ? Math.round(blocked / all * 100) + "%" : "-";
  $("k-blocked").title = fmtN(blocked) + " of " + fmtN(all) + " queries";

  ["q", "f-client", "f-cat", "f-status"].forEach(id =>
    $(id).addEventListener("input", () => { openKey = null; render(); }));
  $("reset").addEventListener("click", () => {
    $("q").value = ""; $("f-client").value = ""; $("f-cat").value = ""; $("f-status").value = "";
    openKey = null; render();
  });
  $("copy").addEventListener("click", e => {
    const list = [...new Set(view().map(r => r.domain))].sort().join("\n");
    navigator.clipboard.writeText(list).then(() => {
      e.target.textContent = "Copied";
      setTimeout(() => { e.target.textContent = "Copy domains"; }, 1200);
    });
  });
  $("csv").addEventListener("click", () => {
    const q = s => '"' + String(s).replace(/"/g, '""') + '"';
    const body = view().map(r => [r.domain, r.kind, r.statusLabel, r.category, r.client || "",
                                  r.hits, r.status,
                                  new Date(r.last * 1000).toISOString()].map(q).join(","));
    const blob = new Blob(["domain,state,status_label,category,client,hits,status,last_seen\n" +
                           body.join("\n") + "\n"],
                          { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "pihole-peek" +
      (META.alias ? "-" + META.alias.replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-|-$/g, "") : "") + ".csv";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  document.querySelectorAll("thead th").forEach(th => th.addEventListener("click", () => {
    const k = th.dataset.k;
    if (k === sortKey) sortDir = -sortDir;
    else { sortKey = k; sortDir = (k === "hits" || k === "last") ? -1 : 1; }
    openKey = null; render();
  }));

  $("rows").addEventListener("click", ev => {
    const btn = ev.target.closest("button[data-whois]");
    if (btn) {
      whois(btn, btn.dataset.whois, btn.closest(".panel").querySelector(".whois"));
      return;
    }
    if (ev.target.closest("a") || ev.target.closest(".detail")) return;
    const tr = ev.target.closest("tr[data-key]");
    if (!tr) return;
    openKey = (openKey === tr.dataset.key) ? null : tr.dataset.key;
    render();
  });

  const sysDark = matchMedia("(prefers-color-scheme: dark)");
  const isDark = () => (document.documentElement.dataset.theme || (sysDark.matches ? "dark" : "light")) === "dark";
  const paintTheme = () => {
    const dark = isDark();
    $("theme").textContent = dark ? "\u2600\uFE0F" : "\uD83C\uDF19";
    $("theme").title = dark ? "Switch to the light theme" : "Switch to the dark theme";
  };
  try {
    const saved = localStorage.getItem("pihole-peek-theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch (e) {}
  sysDark.addEventListener("change", paintTheme);
  $("theme").addEventListener("click", () => {
    document.documentElement.dataset.theme = isDark() ? "light" : "dark";
    try { localStorage.setItem("pihole-peek-theme", document.documentElement.dataset.theme); } catch (e) {}
    paintTheme();
  });
  paintTheme();

  paintCategories();
  if (!HAS_CATS) {
    $("f-cat").hidden = true;
    $("kpi-cat").hidden = true;
    document.querySelector('thead th[data-k="category"]').remove();
    document.querySelector("#lg-cats").closest("div").hidden = true;
  }
  legend();
  render();
}

function legend() {
  const hits = {}, catHits = {};
  DATA.forEach(r => {
    r.status.split("|").forEach(st => { hits[st] = (hits[st] || 0) + r.hits; });
    catHits[r.category] = (catHits[r.category] || 0) + r.hits;
  });

  $("lg-status").innerHTML = Object.keys(STATUS).map(st => {
    const [kind, label] = STATUS[st];
    const n = hits[st] || 0;
    return '<tr class="' + (n ? "" : "off") + '">' +
      '<td class="c"><span class="sw ' + kind + '"></span></td>' +
      '<td class="k">' + st + "</td>" +
      "<td>" + esc(label.replace(/^[a-z]+ \u00b7 /, "")) + " \u2014 " + esc(STATUS_WHY[st] || "") + "</td>" +
      '<td class="n">' + (n ? fmtN(n) : "\u2013") + "</td></tr>";
  }).join("") +
    '<tr><td class="c"><span class="sw mixed"></span></td><td class="k">mixed</td>' +
    "<td>the domain had more than one state inside the window; the row lists them</td>" +
    '<td class="n">\u2013</td></tr>';

  const seen = new Set(DATA.map(r => r.category));
  const known = [...new Set([...RULES.map(r => r[0]), ...Object.keys(ABOUT), "other"])];
  $("lg-cats").innerHTML = known.map(name => {
    const what = ABOUT[name] || "a rule of your own";
    const n = catHits[name] || 0;
    return '<tr class="' + (seen.has(name) ? "" : "off") + '">' +
      '<td class="c"><span class="dot" data-c="' + esc(name) + '"></span></td>' +
      '<td class="k">' + esc(name) + "</td><td>" + esc(what) + "</td>" +
      '<td class="n">' + (n ? fmtN(n) : "\u2013") + "</td></tr>";
  }).join("");

  $("lg-note").innerHTML =
    "A grey row is a value this export does not contain. Status colours are fixed and say what " +
    "happened; category colours come from the rules file and say what the domain is. Both always " +
    "carry their name in writing, so neither leans on colour alone, and hovering a category shows " +
    "the rule that chose it." +
    (HAS_CATS
      ? "<br>The " + fmtN(RULES.length) + " category rules come from <code>" +
        esc(META.categories || "categories") + "</code>. Put yours in <code>" +
        esc((META.categories || "categories") + ".local") + "</code>: same format, tried first, " +
        "and git will not fight you over it."
      : "<br>No category rules were found, so the report has no category column.") +
    (RULE_ERRORS.length
      ? '<br><span class="warn">Rules that did not compile: ' + esc(RULE_ERRORS.join("; ")) + "</span>"
      : "");
}

init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        os._exit(0)
