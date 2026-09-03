import base64
from datetime import datetime, timezone, timedelta
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

# СТРОГО ТВОИ 5 ИСТОЧНИКОВ
SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/1.txt",
    "https://raw.githubusercontent.com/Hidashimora/free-vpn-anti-rkn/refs/heads/main/configs/1.1.txt",
    "https://raw.githubusercontent.com/pog7x/vpn-configs/refs/heads/master/githubmirror/1.txt",
    "https://raw.githubusercontent.com/FLAT447/v2ray-lists/refs/heads/main/BLACK_FULL.txt"
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
    "KZ": ("🇰🇿", [r"kazakhstan", r"almaty", r"astana", r"\bkz\b", r"🇰🇿"])
}

def decode_data(raw: str) -> list[str]:
    try:
        decoded = base64.b64decode(raw.strip()).decode("utf-8", errors="ignore")
        return [line.strip() for line in decoded.splitlines() if line.strip().startswith("vless://")]
    except Exception:
        return [line.strip() for line in raw.splitlines() if line.strip().startswith("vless://")]

def detect_country(text: str):
    t = text.lower()
    for code, (flag, patterns) in COUNTRY_PATTERNS.items():
        for p in patterns:
            if re.search(p, t):
                return code, flag
    return "EU", "🌐"

def parse_vless(url: str):
    try:
        p = urllib.parse.urlparse(url)
        uuid = p.username
        host, port = p.hostname, p.port
        if not uuid or not host or not port:
            return None
        params = dict(urllib.parse.parse_qsl(p.query))
        pbk = params.get("pbk")
        sni = params.get("sni") or params.get("peer")
        if not pbk or not sni:
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

def test_proxy_get(node: dict, local_port: int = 10808) -> int:
    """Тестирует реальный выход в интернет через sing-box (Proxy GET до Google)"""
    sni = node["params"].get("sni") or node["params"].get("peer")
    pbk = node["params"].get("pbk", "")
    sid = node["params"].get("sid", "")
    flow = node["params"].get("flow", "")

    sb_config = {
        "inbounds": [{
            "type": "socks",
            "tag": "socks-in",
            "listen": "127.0.0.1",
            "listen_port": local_port
        }],
        "outbounds": [{
            "type": "vless",
            "tag": "proxy",
            "server": node["host"],
            "server_port": node["port"],
            "uuid": node["uuid"],
            "flow": flow,
            "tls": {
                "enabled": True,
                "server_name": sni,
                "reality": {
                    "enabled": True,
                    "public_key": pbk,
                    "short_id": sid
                }
            }
        }]
    }

    config_path = f"temp_{local_port}.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(sb_config, f)

    proc = subprocess.Popen(
        ["sing-box", "run", "-c", config_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(0.5)

    start = time.perf_counter()
    ping_ms = None

    try:
        proxy_support = urllib.request.ProxyHandler({
            "http": f"socks5h://127.0.0.1:{local_port}",
            "https": f"socks5h://127.0.0.1:{local_port}"
        })
        opener = urllib.request.build_opener(proxy_support)
        req = urllib.request.Request(
            "https://www.gstatic.com/generate_204",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with opener.open(req, timeout=2.5) as resp:
            if resp.status in (200, 204):
                ping_ms = int((time.perf_counter() - start) * 1000)
    except Exception:
        ping_ms = None
    finally:
        proc.terminate()
        proc.kill()
        if os.path.exists(config_path):
            os.remove(config_path)

    return ping_ms

def main():
    collected_urls = []
    for url in SOURCES:
        try:
            req = urllib.request.Request(
                url, 
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                collected_urls.extend(decode_data(content))
        except Exception:
            continue

    parsed_nodes = []
    seen = set()

    for raw_url in collected_urls:
        node = parse_vless(raw_url)
        if node:
            key = (node["host"], node["port"], node["uuid"])
            if key not in seen:
                seen.add(key)
                parsed_nodes.append(node)

    print(f"Собрано {len(parsed_nodes)} уникальных Reality нод. Тестируем реальный трафик...")

    alive_nodes = []
    country_counts = {}

    # Проверяем кандидатов реальным Proxy GET запросом
    for i, node in enumerate(parsed_nodes[:120]):
        c_code, flag = detect_country(node["name"] + " " + node["host"])
        
        # Не больше 4 серверов на одну страну
        if country_counts.get(c_code, 0) >= 4:
            continue

        ping = test_proxy_get(node, local_port=10808 + (i % 10))
        if ping is not None and ping < 3000:
            node["ping"] = ping
            node["code"] = c_code
            node["flag"] = flag
            country_counts[c_code] = country_counts.get(c_code, 0) + 1
            alive_nodes.append(node)
            print(f"[OK] {c_code} {node['host']} - {ping}ms")

        if len(alive_nodes) >= 20:
            break

    # Сортируем по реальной скорости
    alive_nodes.sort(key=lambda x: x["ping"])

    final_links = []
    node_counters = {}
    for node in alive_nodes:
        c = node["code"]
        flag = node["flag"]
        idx = node_counters.get(c, 0) + 1
        node_counters[c] = idx

        new_title = f"{c} {flag} ouVPN #{idx} ({node['ping']}ms)"
        encoded_title = urllib.parse.quote(new_title)
        query_str = urllib.parse.urlencode(node["params"])
        final_links.append(f"vless://{node['uuid']}@{node['host']}:{node['port']}?{query_str}#{encoded_title}")

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

    with open("sub.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n" + "\n".join(final_links))

if __name__ == "__main__":
    main()
