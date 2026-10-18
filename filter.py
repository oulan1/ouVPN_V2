import asyncio
import base64
from datetime import datetime, timezone, timedelta
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

# Ensure stdout and stderr handle utf-8 safely on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Sources with high-quality, frequently updated VLESS Reality configs
SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/Hidashimora/free-vpn-anti-rkn/refs/heads/main/configs/1.1.txt",
    "https://raw.githubusercontent.com/pog7x/vpn-configs/refs/heads/master/githubmirror/1.txt",
    "https://raw.githubusercontent.com/FLAT447/v2ray-lists/refs/heads/main/BLACK_FULL.txt",
    "https://raw.githubusercontent.com/Leon406/SubCrawler/main/sub/share/vless",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub"
]

COUNTRY_PATTERNS = {
    "DE": ("🇩🇪", [r"germany", r"deutschland", r"frankfurt", r"falkenstein", r"\bde\b", r"🇩🇪"]),
    "NL": ("🇳🇱", [r"netherlands", r"holland", r"amsterdam", r"\bnl\b", r"🇳🇱"]),
    "FI": ("🇫🇮", [r"finland", r"helsinki", r"\bfi\b", r"🇫🇮"]),
    "SE": ("🇸🇪", [r"sweden", r"stockholm", r"\bse\b", r"🇸🇪"]),
    "PL": ("🇵🇱", [r"poland", r"warsaw", r"\bpl\b", r"🇵🇱"]),
    "FR": ("🇫🇷", [r"france", r"paris", r"\bfr\b", r"🇫🇷"]),
    "GB": ("🇬🇧", [r"united kingdom", r"london", r"\bgb\b", r"\buk\b", r"🇬🇧"]),
    "AT": ("🇦🇹", [r"austria", r"vienna", r"\bat\b", r"🇦🇹"]),
    "CH": ("🇨🇭", [r"switzerland", r"zurich", r"\bch\b", r"🇨🇭"]),
    "US": ("🇺🇸", [r"united states", r"usa", r"\bus\b", r"🇺🇸"]),
    "TR": ("🇹🇷", [r"turkey", r"istanbul", r"\btr\b", r"🇹🇷"]),
    "KZ": ("🇰🇿", [r"kazakhstan", r"almaty", r"astana", r"\bkz\b", r"🇰🇿"]),
    "SG": ("🇸🇬", [r"singapore", r"\bsg\b", r"🇸🇬"]),
    "JP": ("🇯🇵", [r"japan", r"tokyo", r"\bjp\b", r"🇯🇵"]),
    "EE": ("🇪🇪", [r"estonia", r"tallinn", r"\bee\b", r"🇪🇪"]),
    "LV": ("🇱🇻", [r"latvia", r"riga", r"\blv\b", r"🇱🇻"]),
    "LT": ("🇱🇹", [r"lithuania", r"vilnius", r"\blt\b", r"🇱🇹"])
}

def country_code_to_flag(code: str) -> str:
    if len(code) == 2 and code.isalpha():
        return "".join(chr(127397 + ord(c)) for c in code.upper())
    return "⚡"

def ensure_xray() -> str:
    """Finds or downloads Xray-core binary for the current OS."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(base_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)

    is_windows = platform.system() == "Windows"
    exe_name = "xray.exe" if is_windows else "xray"
    local_path = os.path.join(bin_dir, exe_name)

    if os.path.isfile(local_path):
        return local_path

    which_path = shutil.which("xray")
    if which_path:
        return which_path

    print(f"[*] Xray binary not found. Downloading for {platform.system()}...")
    version = "v26.3.27"
    zip_name = "Xray-windows-64.zip" if is_windows else "Xray-linux-64.zip"
    url = f"https://github.com/XTLS/Xray-core/releases/download/{version}/{zip_name}"
    zip_path = os.path.join(bin_dir, zip_name)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp, open(zip_path, "wb") as out:
        shutil.copyfileobj(resp, out)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extract(exe_name, bin_dir)

    try:
        os.remove(zip_path)
    except Exception:
        pass

    if not is_windows:
        os.chmod(local_path, 0o755)

    print(f"[+] Xray installed successfully to {local_path}")
    return local_path

def decode_data(raw: str) -> list[str]:
    try:
        decoded = base64.b64decode(raw.strip()).decode("utf-8", errors="ignore")
        return [line.strip() for line in decoded.splitlines() if line.strip().startswith("vless://")]
    except Exception:
        return [line.strip() for line in raw.splitlines() if line.strip().startswith("vless://")]

def detect_country_by_pattern(text: str) -> tuple[str, str]:
    t = text.lower()
    for code, (flag, patterns) in COUNTRY_PATTERNS.items():
        for p in patterns:
            if re.search(p, t):
                return code, flag
    return "EU", "⚡"

def parse_vless(url: str):
    try:
        p = urllib.parse.urlparse(url)
        uuid = p.username
        host, port = p.hostname, p.port
        if not uuid or not host or not port:
            return None
        params = dict(urllib.parse.parse_qsl(p.query))
        pbk = params.get("pbk")
        security = params.get("security", "").lower()
        if not pbk and security != "reality":
            return None
        if params.get("headerType") == "http":
            return None

        return {
            "uuid": uuid,
            "host": host,
            "port": int(port),
            "params": params,
            "name": urllib.parse.unquote(p.fragment),
            "raw": url
        }
    except Exception:
        return None

def build_xray_outbound(tag: str, node: dict) -> dict:
    params = node["params"]
    net = params.get("type", "tcp").lower()
    sec = params.get("security", "none").lower()
    flow = params.get("flow", "")

    stream: dict = {"network": net, "security": sec}

    if sec == "reality":
        stream["realitySettings"] = {
            "serverName": params.get("sni", ""),
            "publicKey": params.get("pbk", ""),
            "shortId": params.get("sid", ""),
            "spiderX": params.get("spx", "/"),
            "fingerprint": params.get("fp", "chrome") or "chrome"
        }
    elif sec == "tls":
        stream["tlsSettings"] = {
            "serverName": params.get("sni", node["host"]),
            "fingerprint": params.get("fp", "chrome") or "chrome",
            "allowInsecure": params.get("allowInsecure", "0") in ("1", "true")
        }

    if net == "grpc":
        stream["grpcSettings"] = {
            "serviceName": params.get("serviceName", params.get("path", "")).lstrip("/"),
            "multiMode": params.get("mode") == "multi"
        }
    elif net in ("ws", "websocket"):
        stream["network"] = "ws"
        stream["wsSettings"] = {
            "path": params.get("path", "/"),
            "headers": {"Host": params.get("host", params.get("sni", node["host"]))}
        }
    elif net in ("xhttp", "splithttp"):
        stream["network"] = "xhttp"
        stream["xhttpSettings"] = {
            "path": params.get("path", "/"),
            "host": params.get("host", params.get("sni", node["host"])),
            "mode": params.get("mode", "auto")
        }
    elif net == "httpupgrade":
        stream["network"] = "httpupgrade"
        stream["httpupgradeSettings"] = {
            "path": params.get("path", "/"),
            "host": params.get("host", params.get("sni", node["host"]))
        }

    user: dict = {
        "id": node["uuid"],
        "encryption": params.get("encryption", "none")
    }
    if flow:
        user["flow"] = flow

    return {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": node["host"],
                "port": node["port"],
                "users": [user]
            }]
        },
        "streamSettings": stream
    }

async def check_tcp_ping(host: str, port: int, sem: asyncio.Semaphore, timeout: float = 0.8):
    """Fast preliminary check to discard offline / DNS-failed hosts."""
    async with sem:
        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)
            await asyncio.wait_for(loop.sock_connect(sock, (host, port)), timeout=timeout)
            sock.close()
            return (time.perf_counter() - start) * 1000
        except Exception:
            return None

async def check_http_proxy(port: int, timeout: float = 3.0) -> int | None:
    """
    Sends an actual HTTP GET request through the local Xray proxy inbound.
    Verifies that the proxy can perform the Reality handshake and reach the Internet.
    """
    start = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port),
            timeout=timeout
        )
        req = (
            b"GET http://cp.cloudflare.com/generate_204 HTTP/1.1\r\n"
            b"Host: cp.cloudflare.com\r\n"
            b"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n"
            b"Connection: close\r\n\r\n"
        )
        writer.write(req)
        await writer.drain()

        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        writer.close()

        if b"204" in line or b"200" in line:
            return round((time.perf_counter() - start) * 1000)
        return None
    except Exception:
        return None

async def test_nodes_real_internet(xray_exe: str, candidate_nodes: list[dict], batch_size: int = 35) -> list[dict]:
    """
    Tests candidates in parallel batches using Xray.
    Returns nodes that successfully route traffic to the Internet, with real latency.
    """
    verified_nodes = []
    base_port = 15000

    for batch_idx in range(0, len(candidate_nodes), batch_size):
        batch = candidate_nodes[batch_idx : batch_idx + batch_size]
        inbounds = []
        outbounds = []
        rules = []

        for i, node in enumerate(batch):
            port = base_port + i
            in_tag = f"in-{i}"
            out_tag = f"out-{i}"
            inbounds.append({
                "tag": in_tag,
                "port": port,
                "listen": "127.0.0.1",
                "protocol": "http"
            })
            outbounds.append(build_xray_outbound(out_tag, node))
            rules.append({
                "type": "field",
                "inboundTag": [in_tag],
                "outboundTag": out_tag
            })

        config = {
            "log": {"loglevel": "none"},
            "inbounds": inbounds,
            "outbounds": outbounds,
            "routing": {"rules": rules}
        }

        tmp_config_path = f"tmp_xray_{batch_idx}.json"
        with open(tmp_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)

        proc = subprocess.Popen(
            [xray_exe, "run", "-c", tmp_config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        await asyncio.sleep(0.8)

        try:
            tasks = [check_http_proxy(base_port + i, timeout=3.0) for i in range(len(batch))]
            results = await asyncio.gather(*tasks)

            for i, latency in enumerate(results):
                if latency is not None:
                    node = batch[i]
                    node["latency"] = latency
                    verified_nodes.append(node)
                    print(f"  [+] REAL Internet OK: {latency:4d}ms -> {node['host']}:{node['port']}")

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
            if os.path.exists(tmp_config_path):
                try:
                    os.remove(tmp_config_path)
                except Exception:
                    pass

        # Stop early if we have collected enough verified servers
        if len(verified_nodes) >= 35:
            break

    return verified_nodes

def enrich_countries_geoip(nodes: list[dict]):
    """Resolves ISO country codes for verified nodes in a single batch request."""
    ip_to_nodes: dict[str, list[dict]] = {}
    for n in nodes:
        host = n["host"]
        # Check if host is an IP
        try:
            socket.inet_aton(host)
            ip = host
        except Exception:
            try:
                ip = socket.gethostbyname(host)
            except Exception:
                ip = None

        if ip:
            ip_to_nodes.setdefault(ip, []).append(n)
        else:
            c, flag = detect_country_by_pattern(n["name"] + " " + n["host"])
            n["code"] = c
            n["flag"] = flag

    ips = list(ip_to_nodes.keys())
    if ips:
        try:
            req = urllib.request.Request(
                "http://ip-api.com/batch",
                data=json.dumps(ips[:100]).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for item in data:
                    if item.get("status") == "success":
                        ip = item.get("query")
                        code = item.get("countryCode", "EU")
                        flag = country_code_to_flag(code)
                        for n in ip_to_nodes.get(ip, []):
                            n["code"] = code
                            n["flag"] = flag
        except Exception:
            pass

    # Ensure all nodes have code and flag
    for n in nodes:
        if "code" not in n or not n["code"]:
            c, flag = detect_country_by_pattern(n["name"] + " " + n["host"])
            n["code"] = c
            n["flag"] = flag

async def main():
    print("=" * 60)
    print("[*] ouVPN_V2: Real Internet Connectivity Filter")
    print("=" * 60)

    xray_exe = ensure_xray()

    print("[*] Downloading configurations from sources...")
    collected_urls = []
    for url in SOURCES:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                decoded = decode_data(content)
                collected_urls.extend(decoded)
                print(f"  + Loaded {len(decoded):4d} configs from {url[:50]}...")
        except Exception as e:
            print(f"  - Failed {url[:50]} ({e})")

    # Deduplicate and validate
    parsed_nodes = []
    seen = set()
    for raw_url in collected_urls:
        node = parse_vless(raw_url)
        if node:
            key = (node["host"], node["port"], node["uuid"])
            if key not in seen:
                seen.add(key)
                parsed_nodes.append(node)

    print(f"\n[*] Unique valid VLESS candidates: {len(parsed_nodes)}")

    # Stage 1: Fast TCP Ping Pre-Filter (prunes offline / dead hosts in ~2s)
    print("[*] Stage 1: Fast TCP Ping Pre-Filter...")
    sem = asyncio.Semaphore(150)
    test_pool = parsed_nodes[:1500]
    tasks = [check_tcp_ping(n["host"], n["port"], sem) for n in test_pool]
    pings = await asyncio.gather(*tasks)

    tcp_alive = []
    for node, ping in zip(test_pool, pings):
        if ping is not None:
            node["tcp_ping"] = ping
            c_code, flag = detect_country_by_pattern(node["name"] + " " + node["host"])
            node["code"] = c_code
            node["flag"] = flag
            tcp_alive.append(node)

    tcp_alive.sort(key=lambda x: x["tcp_ping"])
    print(f"[+] TCP-alive servers: {len(tcp_alive)} of {len(test_pool)}")

    # Candidate selection with country diversity for testing
    by_country: dict[str, list[dict]] = {}
    for n in tcp_alive:
        by_country.setdefault(n["code"], []).append(n)

    diverse_candidates = []
    round_idx = 0
    while len(diverse_candidates) < min(260, len(tcp_alive)):
        added = False
        for c, nodes_list in by_country.items():
            if round_idx < len(nodes_list):
                diverse_candidates.append(nodes_list[round_idx])
                added = True
        if not added:
            break
        round_idx += 1

    # Stage 2: REAL HTTP Internet Access Test via Xray
    print(f"\n[*] Stage 2: REAL Internet Access Test via Xray ({len(diverse_candidates)} candidates)...")
    verified_nodes = await test_nodes_real_internet(xray_exe, diverse_candidates, batch_size=40)
    print(f"[+] Verified servers with confirmed Internet access: {len(verified_nodes)}")

    if not verified_nodes:
        print("[!] Warning: No servers passed real Internet check! Fallback to lowest TCP alive.")
        verified_nodes = tcp_alive[:25]
        for n in verified_nodes:
            n["latency"] = n.get("tcp_ping", 999)

    # Stage 3: Precise GeoIP Lookup
    print("[*] Stage 3: Resolving exact server countries...")
    enrich_countries_geoip(verified_nodes)

    # Stage 4: Selection by lowest REAL latency with country diversity
    verified_nodes.sort(key=lambda x: x["latency"])

    TARGET_COUNT = 25
    MAX_PER_COUNTRY = 4
    selected_nodes = []
    country_counts: dict[str, int] = {}

    for node in verified_nodes:
        c = node["code"]
        if country_counts.get(c, 0) < MAX_PER_COUNTRY:
            country_counts[c] = country_counts.get(c, 0) + 1
            selected_nodes.append(node)
        if len(selected_nodes) >= TARGET_COUNT:
            break

    # If still below target count, backfill with remaining verified nodes
    if len(selected_nodes) < TARGET_COUNT:
        for node in verified_nodes:
            if node not in selected_nodes:
                selected_nodes.append(node)
            if len(selected_nodes) >= TARGET_COUNT:
                break

    # Final sort by latency
    selected_nodes.sort(key=lambda x: x["latency"])

    final_links = []
    node_counters: dict[str, int] = {}
    for node in selected_nodes:
        c = node["code"]
        flag = node["flag"]
        idx = node_counters.get(c, 0) + 1
        node_counters[c] = idx

        new_title = f"{c} {flag} ouVPN #{idx} ({int(node['latency'])}ms)"
        encoded_title = urllib.parse.quote(new_title)
        query_str = urllib.parse.urlencode(node["params"])
        final_links.append(f"vless://{node['uuid']}@{node['host']}:{node['port']}?{query_str}#{encoded_title}")

    # Moscow UTC+3
    msk_tz = timezone(timedelta(hours=3))
    now_msk = datetime.now(msk_tz)
    date_formatted = now_msk.strftime("%Y-%m-%d / %H:%M (Moscow)")
    announce_date = now_msk.strftime("%y.%m.%d - %H:%M МСК")

    header = [
        "# profile-title: 👑 𝗼𝘂𝗩𝗣𝗡",
        "# profile-update-interval: 3",
        f"# Date/Time: {date_formatted}",
        f"# Количество: {len(final_links)}",
        "# profile-web-page-url: https://oulan1.github.io/ouVPN/",
        "# support-url: https://t.me/oulanGift",
        f"# announce: 🌐 Дата последнего обновления: {announce_date}",
        ""
    ]

    sub_content = "\n".join(header) + "\n" + "\n".join(final_links)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sub_path = os.path.join(base_dir, "sub.txt")
    with open(sub_path, "w", encoding="utf-8") as f:
        f.write(sub_content)

    print(f"\n[SUCCESS] Done! Saved {len(final_links)} fast, confirmed WORKING servers to sub.txt")

if __name__ == "__main__":
    asyncio.run(main())
