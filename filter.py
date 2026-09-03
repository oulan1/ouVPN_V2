import asyncio
import base64
from datetime import datetime, timezone, timedelta
import re
import socket
import time
import urllib.parse
import urllib.request

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

async def check_tcp_ping(host: str, port: int, timeout: float = 1.5):
    loop = asyncio.get_running_loop()
    start = time.perf_counter()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        await asyncio.wait_for(loop.sock_connect(sock, (host, port)), timeout=timeout)
        sock.close()
        return (time.perf_counter() - start) * 1000  # ms
    except Exception:
        return None

async def main():
    collected_urls = []
    for url in SOURCES:
        try:
            req = urllib.request.Request(
                url, 
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
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

    # Параллельный замер пинга
    test_pool = parsed_nodes[:300]
    tasks = [check_tcp_ping(n["host"], n["port"]) for n in test_pool]
    pings = await asyncio.gather(*tasks)

    alive_nodes = []
    for node, ping in zip(test_pool, pings):
        if ping is not None:
            node["ping"] = ping
            c_code, flag = detect_country(node["name"] + " " + node["host"])
            node["code"] = c_code
            node["flag"] = flag
            alive_nodes.append(node)

    # Сортировка от минимального пинга
    alive_nodes.sort(key=lambda x: x["ping"])

    TARGET_COUNT = 25
    MAX_PER_COUNTRY = 4
    selected_nodes = []
    country_counts = {}

    # Пошаговая лесенка по 10 мс: 20ms -> 30ms -> 40ms -> ... -> 300ms
    current_limit = 20
    max_threshold = 500

    while current_limit <= max_threshold and len(selected_nodes) < TARGET_COUNT:
        for node in alive_nodes:
            if node in selected_nodes:
                continue
            
            # Попадает ли узел в текущий порог
            if node["ping"] <= current_limit:
                c = node["code"]
                if country_counts.get(c, 0) < MAX_PER_COUNTRY:
                    country_counts[c] = country_counts.get(c, 0) + 1
                    selected_nodes.append(node)

            if len(selected_nodes) >= TARGET_COUNT:
                break

        current_limit += 10

    # Если даже после 500 мс не набралось 25, добираем любые живые оставшиеся
    if len(selected_nodes) < TARGET_COUNT:
        for node in alive_nodes:
            if node not in selected_nodes:
                selected_nodes.append(node)
            if len(selected_nodes) >= TARGET_COUNT:
                break

    # Итоговая сортировка отобранных серверов
    selected_nodes.sort(key=lambda x: x["ping"])

    final_links = []
    node_counters = {}
    for node in selected_nodes:
        c = node["code"]
        flag = node["flag"]
        idx = node_counters.get(c, 0) + 1
        node_counters[c] = idx

        new_title = f"{c} {flag} ouVPN #{idx} ({int(node['ping'])}ms)"
        encoded_title = urllib.parse.quote(new_title)
        query_str = urllib.parse.urlencode(node["params"])
        final_links.append(f"vless://{node['uuid']}@{node['host']}:{node['port']}?{query_str}#{encoded_title}")

    # Москва UTC+3
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
    asyncio.run(main())
