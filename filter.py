import asyncio
import base64
from datetime import datetime, timezone, timedelta
import re
import socket
import time
import urllib.parse
import urllib.request

# Рабочие и свежие базы с обилием Reality
SOURCES = [
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/vless",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/ndsphon/v2ray-collector/main/vless.txt",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt"
]

# Соответствие кодов, флагов и вариантов написания
EU_MAP = {
    "DE": ("🇩🇪", ["germany", "deutschland", "frankfurt", "falkenstein"]),
    "NL": ("🇳🇱", ["netherlands", "holland", "amsterdam"]),
    "FI": ("🇫🇮", ["finland", "helsinki"]),
    "SE": ("🇸🇪", ["sweden", "stockholm"]),
    "PL": ("🇵🇱", ["poland", "warsaw"]),
    "FR": ("🇫🇷", ["france", "paris"]),
    "GB": ("🇬🇧", ["united kingdom", "britain", "england", "london", "uk"]),
    "AT": ("🇦🇹", ["austria", "vienna"]),
    "CH": ("🇨🇭", ["switzerland", "zurich"]),
    "CZ": ("🇨🇿", ["czech", "prague"]),
    "NO": ("🇳🇴", ["norway", "oslo"]),
    "IT": ("🇮🇹", ["italy", "milan", "rome"]),
    "ES": ("🇪🇸", ["spain", "madrid"])
}

def decode_sub(content: str) -> list[str]:
    lines = []
    try:
        decoded = base64.b64decode(content.strip()).decode("utf-8", errors="ignore")
        lines = decoded.splitlines()
    except Exception:
        lines = content.splitlines()
    return [l.strip() for l in lines if l.startswith("vless://")]

def parse_vless(url: str):
    try:
        parsed = urllib.parse.urlparse(url)
        uuid = parsed.username
        host, port = parsed.hostname, parsed.port
        if not uuid or not host or not port:
            return None
            
        params = dict(urllib.parse.parse_qsl(parsed.query))
        raw_name = urllib.parse.unquote(parsed.fragment)
        
        # Отсекаем мертвый устаревший мусор с HTTP-заголовками
        if params.get("headerType") == "http":
            return None

        security = params.get("security", "").lower()
        is_reality = (security == "reality") or ("pbk" in params)

        return {
            "uuid": uuid,
            "host": host,
            "port": port,
            "params": params,
            "is_reality": is_reality,
            "name": raw_name
        }
    except Exception:
        return None

def detect_country(name: str):
    name_lower = name.lower()
    for code, (flag, keywords) in EU_MAP.items():
        # Поиск эмодзи флага
        if flag in name:
            return code, flag
        # Поиск кода страны типа [DE] или отдельным словом DE
        if re.search(rf"\b{code}\b", name, re.IGNORECASE):
            return code, flag
        # Поиск по городам и названиям (Frankfurt, Amsterdam...)
        for kw in keywords:
            if kw in name_lower:
                return code, flag
    return None, None

async def check_tcp(host: str, port: int, timeout: float = 1.2):
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
    raw_urls = []
    for src in SOURCES:
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as res:
                raw_urls.extend(decode_sub(res.read().decode("utf-8", errors="ignore")))
        except Exception:
            continue

    parsed_nodes = []
    seen = set()
    for u in raw_urls:
        node = parse_vless(u)
        if node:
            key = (node["host"], node["port"])
            if key not in seen:
                seen.add(key)
                parsed_nodes.append(node)

    # Разделяем на кандидатов с определенной страной и общие Reality
    eu_pool = []
    fallback_pool = []

    for node in parsed_nodes:
        code, flag = detect_country(node["name"])
        if code:
            node["country"] = code
            node["flag"] = flag
            eu_pool.append(node)
        elif node["is_reality"]:
            fallback_pool.append(node)

    # Приоритет Reality внутри европейских
    eu_pool.sort(key=lambda x: not x["is_reality"])
    
    # Берем пачку до 150 европейских + 50 на запас
    test_batch = eu_pool[:150] + fallback_pool[:50]
    tasks = [check_tcp(n["host"], n["port"]) for n in test_batch]
    pings = await asyncio.gather(*tasks)

    alive = []
    for node, ping in zip(test_batch, pings):
        if ping is not None and ping < 450:
            node["ping"] = ping
            alive.append(node)

    # Сортировка по задержке
    alive.sort(key=lambda x: x["ping"])

    final_nodes = []
    country_counts = {}
    MAX_PER_COUNTRY = 5  # Не больше 5 штук на страну

    # Сначала набираем сбалансированную Европу
    for node in alive:
        if "country" in node:
            c = node["country"]
            if country_counts.get(c, 0) < MAX_PER_COUNTRY:
                country_counts[c] = country_counts.get(c, 0) + 1
                final_nodes.append(node)
        if len(final_nodes) >= 25:
            break

    # Если набралось меньше 15 серверов, добираем любые живые выжившие
    if len(final_nodes) < 15:
        for node in alive:
            if node not in final_nodes:
                final_nodes.append(node)
            if len(final_nodes) >= 20:
                break

    # Сборка ссылок
    final_links = []
    counters = {}
    for node in final_nodes:
        c = node.get("country", "EU")
        flag = node.get("flag", "⚡")
        cnt = counters.get(c, 0) + 1
        counters[c] = cnt

        type_tag = "Reality" if node["is_reality"] else "VLESS"
        new_title = f"{c} {flag} ouVPN #{cnt} [{type_tag}] ({int(node['ping'])}ms)"
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
