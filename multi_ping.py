#!/usr/bin/env python3
"""
multi_ping.py — Publish-time notifier for:
  1) Google Search Console URL Inspection API (READ-ONLY status check)
  2) IndexNow (Bing, Yandex, Seznam, Naver, etc.)
  3) Pingomatic XML-RPC (legacy blog ping)

Notes
-----
- This script intentionally DOES NOT call Google's Indexing API.
- URL Inspection API only checks indexing status; it does not request indexing.

Setup
-----
1) Python deps:
   pip install google-api-python-client google-auth google-auth-httplib2 requests

2) Google Search Console URL Inspection API:
   - Create a Google Cloud project, enable the "Search Console API".
   - Create a Service Account and download its JSON key.
   - In Search Console, add the SERVICE ACCOUNT EMAIL as a user (at least "Restricted") on your property.
   - Set env vars:
       SERVICE_ACCOUNT_FILE=/path/to/sa.json
       PROPERTY_URL=https://example.com  (must match your Search Console property exactly)

3) IndexNow:
   - Generate a key and host it at https://YOUR_DOMAIN/indexnow.txt (per IndexNow spec).
   - Set env vars:
       INDEXNOW_KEY=YOUR_KEY_STRING
       INDEXNOW_KEY_LOCATION=https://YOUR_DOMAIN/indexnow.txt

4) Pingomatic:
   - No credentials required. You must provide BLOG_NAME and BLOG_URL if you want to ping it.
   - Set env vars (optional):
       BLOG_NAME="My Blog"
       BLOG_URL="https://example.com"

Usage
-----
  # Read URLs from a file (one per line)
  python multi_ping.py --file urls.txt --gsc --indexnow --pingomatic

  # Or pass URLs directly
  python multi_ping.py --urls https://example.com/a https://example.com/b --gsc --indexnow

  # Only IndexNow + GSC, no Pingomatic
  python multi_ping.py --file urls.txt --gsc --indexnow

  # Show help
  python multi_ping.py -h
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Iterable, List, Dict, Any, Tuple

import requests

# Google API imports (lazy)
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
except Exception:
    service_account = None
    build = None

# -----------------------------
# Helpers
# -----------------------------

def read_urls(file_path: str) -> List[str]:
    urls = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            u = line.strip()
            if u and not u.startswith("#"):
                urls.append(u)
    return urls

def unique_keep_order(seq: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

# -----------------------------
# Google Search Console — URL Inspection API (READ-ONLY)
# -----------------------------

def gsc_inspect(url: str, property_url: str, service_account_file: str) -> Dict[str, Any]:
    """
    Calls Search Console URL Inspection API for a single URL.
    Returns the inspection result dict (or error info).
    """
    if not (service_account and build):
        raise RuntimeError("Google libraries not installed. Install: pip install google-api-python-client google-auth google-auth-httplib2")

    scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]
    creds = service_account.Credentials.from_service_account_file(service_account_file, scopes=scopes)

    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    body = {
        "inspectionUrl": url,
        "siteUrl": property_url,
        "languageCode": "en-US"
    }
    try:
        resp = service.urlInspection().index().inspect(body=body).execute()
        return resp
    except Exception as e:
        return {"error": str(e)}

def summarize_gsc(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a compact summary from the URL Inspection response."""
    out = {
        "indexed": None,
        "lastCrawl": None,
        "canonical": None,
        "verdict": None,
        "coverageState": None,
        "mobileUsability": None,
    }
    try:
        result = resp.get("inspectionResult", {})
        idx = result.get("indexStatusResult", {})
        mob = result.get("mobileUsabilityResult", {})
        out["indexed"] = idx.get("coverageState") in ("Indexed", "Submitted and indexed")
        out["lastCrawl"] = idx.get("lastCrawlTime")
        out["canonical"] = idx.get("googleCanonical")
        out["verdict"] = idx.get("verdict")
        out["coverageState"] = idx.get("coverageState")
        out["mobileUsability"] = mob.get("verdict")
    except Exception:
        pass
    return out

# -----------------------------
# IndexNow
# -----------------------------

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
INDEXNOW_BULK_ENDPOINT = "https://api.indexnow.org/indexnow"

def indexnow_submit_single(url: str, key: str, key_location: str, timeout: int = 15) -> Tuple[int, str]:
    """
    Submit a single URL via GET.
    Returns (status_code, text).
    """
    params = {
        "url": url,
        "key": key,
        "keyLocation": key_location,
    }
    r = requests.get(INDEXNOW_ENDPOINT, params=params, timeout=timeout)
    return r.status_code, r.text

def indexnow_submit_bulk(urls: List[str], host: str, key: str, key_location: str, timeout: int = 20) -> Tuple[int, str]:
    """
    Bulk submit up to 10,000 URLs in one JSON POST.
    'host' must be your domain (e.g., "example.com").
    """
    payload = {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }
    headers = {"Content-Type": "application/json"}
    r = requests.post(INDEXNOW_BULK_ENDPOINT, headers=headers, data=json.dumps(payload), timeout=timeout)
    return r.status_code, r.text

# -----------------------------
# Pingomatic (XML-RPC)
# -----------------------------
import xmlrpc.client

PINGOMATIC_RPC = "http://rpc.pingomatic.com/"

def pingomatic_ping(blog_name: str, blog_url: str, feed_url: str | None = None, timeout: int = 15) -> Dict[str, Any]:
    """
    Calls weblogUpdates.ping or extendedPing if feed_url provided.
    Returns the XML-RPC response.
    """
    transport = xmlrpc.client.Transport()
    transport.user_agent = "multi-ping-script/1.0"
    server = xmlrpc.client.ServerProxy(PINGOMATIC_RPC, transport=transport, allow_none=True)
    try:
        if feed_url:
            resp = server.weblogUpdates.extendedPing(blog_name, blog_url, feed_url)
        else:
            resp = server.weblogUpdates.ping(blog_name, blog_url)
        return {"ok": True, "response": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -----------------------------
# CLI
# -----------------------------

def main():
    ap = argparse.ArgumentParser(description="Notify search engines & check indexing status.")
    ap.add_argument("--file", help="Path to a text file with URLs (one per line).")
    ap.add_argument("--urls", nargs="*", help="URLs provided directly on the command line.")
    ap.add_argument("--gsc", action="store_true", help="Call Google Search Console URL Inspection API (read-only).")
    ap.add_argument("--indexnow", action="store_true", help="Submit to IndexNow.")
    ap.add_argument("--bulk", action="store_true", help="Use IndexNow bulk JSON POST (requires --host).")
    ap.add_argument("--host", help="Your site host (e.g., example.com) for IndexNow bulk requests.")
    ap.add_argument("--pingomatic", action="store_true", help="Ping Pingomatic (requires BLOG_NAME & BLOG_URL env).")
    ap.add_argument("--feed", help="Optional feed URL for Pingomatic extendedPing.")
    ap.add_argument("--sleep", type=float, default=0.5, help="Sleep seconds between calls to be polite.")
    args = ap.parse_args()

    # Collect URLs
    urls: List[str] = []
    if args.file:
        urls += read_urls(args.file)
    if args.urls:
        urls += args.urls
    urls = unique_keep_order(urls)

    if not urls and not args.pingomatic:
        print("No URLs provided. Use --file or --urls, or just --pingomatic for a blog-level ping.", file=sys.stderr)
        sys.exit(1)

    # Env vars
    svc_file = os.getenv("SERVICE_ACCOUNT_FILE")
    property_url = os.getenv("PROPERTY_URL")
    indexnow_key = os.getenv("INDEXNOW_KEY")
    indexnow_key_loc = os.getenv("INDEXNOW_KEY_LOCATION")
    blog_name = os.getenv("BLOG_NAME")
    blog_url = os.getenv("BLOG_URL")

    # Sanity checks
    if args.gsc:
        if not (svc_file and property_url):
            print("GSC: Please set SERVICE_ACCOUNT_FILE and PROPERTY_URL env vars.", file=sys.stderr)
            sys.exit(2)
        if not os.path.isfile(svc_file):
            print(f"GSC: SERVICE_ACCOUNT_FILE not found at {svc_file}", file=sys.stderr)
            sys.exit(2)

    if args.indexnow:
        if args.bulk:
            if not (args.host and indexnow_key and indexnow_key_loc):
                print("IndexNow bulk: require --host and env INDEXNOW_KEY, INDEXNOW_KEY_LOCATION", file=sys.stderr)
                sys.exit(3)
        else:
            if not (indexnow_key and indexnow_key_loc):
                print("IndexNow single: set env INDEXNOW_KEY and INDEXNOW_KEY_LOCATION", file=sys.stderr)
                sys.exit(3)

    if args.pingomatic:
        if not (blog_name and blog_url):
            print("Pingomatic: set env BLOG_NAME and BLOG_URL", file=sys.stderr)
            sys.exit(4)

    # Run
    report: List[Dict[str, Any]] = []

    # Pingomatic (blog-level) first if requested
    if args.pingomatic:
        print("== Pingomatic ==")
        po = pingomatic_ping(blog_name, blog_url, feed_url=args.feed)
        if po.get("ok"):
            print("Pingomatic: OK", po.get("response"))
        else:
            print("Pingomatic: ERROR", po.get("error"))
        print()

    # IndexNow
    if args.indexnow and urls:
        print("== IndexNow ==")
        if args.bulk:
            status, text = indexnow_submit_bulk(urls, host=args.host, key=indexnow_key, key_location=indexnow_key_loc)
            print(f"Bulk POST: HTTP {status} — {text[:300]}")
        else:
            for u in urls:
                status, text = indexnow_submit_single(u, key=indexnow_key, key_location=indexnow_key_loc)
                print(f"{u} -> HTTP {status}")
                time.sleep(args.sleep)
        print()

    # GSC URL Inspection
    if args.gsc and urls:
        print("== Google URL Inspection (read-only) ==")
        for u in urls:
            resp = gsc_inspect(u, property_url=property_url, service_account_file=svc_file)
            summary = summarize_gsc(resp) if isinstance(resp, dict) else {"error": "unexpected response"}
            report.append({"url": u, "gsc": summary})
            status_txt = (
                f"indexed={summary.get('indexed')} "
                f"coverage={summary.get('coverageState')} "
                f"canonical={summary.get('canonical')} "
                f"lastCrawl={summary.get('lastCrawl')} "
                f"mobile={summary.get('mobileUsability')}"
            )
            print(f"{u}\n  {status_txt}")
            time.sleep(args.sleep)

    # Optional: write JSON report
    if report:
        out_path = "multi_ping_report.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nSaved report -> {out_path}")

if __name__ == "__main__":
    main()
