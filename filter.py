import base64
from datetime import datetime, timezone, timedelta
import re
import urllib.parse
import urllib.request

# Твои проверенные источники под РФ
SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/1.txt",
    "https://raw.githubusercontent.com/Hidashimora/free-vpn-anti-rkn/refs/heads/main/configs/1.1.txt",
    "https://raw.githubusercontent.com/pog7x/vpn-configs/refs/heads/master/githubmirror/1.txt",
    "https://raw.githubusercontent.com/FLAT447/v2ray-lists/refs/heads/main/BLACK_FULL.txt"
]

# Карта стран, флагов и паттернов поиска
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

def main():
    collected_urls = []
    
    # 1. Скачиваем ссылки из твоих источников
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

    reality_nodes = []
    seen = set()

    # 2. Фильтруем строго рабочие Reality конфиги
    for raw_url in collected_urls:
        try:
            parsed = urllib.parse.urlparse(raw_url)
            uuid = parsed.username
            host, port = parsed.hostname, parsed.port
            if not uuid or not host or not port:
                continue

            params = dict(urllib.parse.parse_qsl(parsed.query))
            
            # Строгий отбор: только Reality с публичным ключом и SNI
            security = params.get("security", "").lower()
            pbk = params.get("pbk")
            sni = params.get("sni") or params.get("peer")
            
            if security != "reality" and not pbk:
                continue
            if not pbk or not sni:
                continue

            # Исключаем дубли
            key = (host, port, uuid)
            if key in seen:
                continue
            seen.add(key)

            raw_name = urllib.parse.unquote(parsed.fragment)
            country_code, flag = detect_country(raw_name + " " + host)

            reality_nodes.append({
                "uuid": uuid,
                "host": host,
                "port": port,
                "params": params,
                "code": country_code,
                "flag": flag
            })
        except Exception:
            continue

    # 3. Балансировка: не больше 5 нод на одну страну
    country_counts = {}
    balanced_nodes = []
    extra_nodes = []

    for node in reality_nodes:
        c = node["code"]
        count = country_counts.get(c, 0)
        if count < 5:
            country_counts[c] = count + 1
            balanced_nodes.append(node)
        else:
            extra_nodes.append(node)

    # Если европейских набралось меньше 25, добираем из запаса
    if len(balanced_nodes) < 25:
        balanced_nodes.extend(extra_nodes[: (25 - len(balanced_nodes))])

    # Итоговый лимит 30 серверов
    final_nodes = balanced_nodes[:30]

    # 4. Сборка ссылок с нумерацией
    final_links = []
    node_counters = {}
    for node in final_nodes:
        c = node["code"]
        flag = node["flag"]
        idx = node_counters.get(c, 0) + 1
        node_counters[c] = idx

        new_title = f"{c} {flag} ouVPN #{idx} [Reality]"
        encoded_title = urllib.parse.quote(new_title)
        query_str = urllib.parse.urlencode(node["params"])
        
        final_links.append(f"vless://{node['uuid']}@{node['host']}:{node['port']}?{query_str}#{encoded_title}")

    # Москва UTC+3
    msk_tz = timezone(timedelta(hours=3))
    now_msk = datetime.now(msk_tz)
    date_formatted = now_msk.strftime("%Y-%m-%d / %H:%M (Moscow)")
    announce_date = now_msk.strftime("%y.%m.%d - %H:%M МСК")

    # Шапка без счетчиков байт и с короной
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
