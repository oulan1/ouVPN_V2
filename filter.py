import asyncio
import base64
from datetime import datetime, timezone, timedelta
import re
import socket
import time
import urllib.parse
import urllib.request

# Проверенные стабильные источники с кучей европейских нод
SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/vless",
    "https://raw.githubusercontent.com/ndsphon/v2ray-collector/main/vless.txt",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2"
]

# Список флагов и кодов стран Европы
EU_FLAGS = {
    "🇩🇪": "DE", "🇳🇱": "NL", "🇫🇮": "FI", "🇸🇪": "SE", "🇵🇱": "PL",
    "🇫🇷": "FR", "🇬🇧": "GB", "🇦🇹": "AT", "🇨🇭": "CH", "🇨🇿": "CZ",
    "🇳🇴": "NO", "🇪🇪": "EE", "🇱🇻": "LV", "🇱🇹": "LT", "🇮🇹": "IT",
    "🇪🇸": "ES", "🇮🇸": "IS", "🇮🇪": "IE", "🇩🇰": "DK", "🇧🇪": "BE"
}

# Регулярка для быстрого поиска флага или буквенного кода страны в названии
COUNTRY_REGEX = re.compile(r"(🇩🇪|🇳🇱|🇫🇮|🇸🇪|🇵🇱|🇫🇷|🇬🇧|🇦🇹|🇨🇭|🇨🇿|🇳🇴|🇪🇪|🇱🇻|🇱🇹|🇮🇹|🇪🇸|🇮🇸|🇮🇪|🇩🇰|🇧🇪|\b(DE|NL|FI|SE|PL|FR|GB|AT|CH|CZ|NO|EE|LV|LT|IT|ES|IS|IE|DK|BE)\b)", re.IGNORECASE)

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
        return {
            "uuid": uuid, 
            "host": host, 
            "port": port, 
            "params": params, 
            "name": raw_name
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
        return (time.perf_counter() - start) * 1000  # мс
    except Exception:
        return None

def extract_country_info(raw_name: str):
    match = COUNTRY_REGEX.search(raw_name)
    if not match:
        return None, None
    found = match.group(0)
    # Если найден эмодзи-флаг
    if found in EU_FLAGS:
        return EU_FLAGS[found], found
    # Если найден текстовый код (DE, NL и т.д.)
    code = found.upper()
    for flag, c_code in EU_FLAGS.items():
        if c_code == code:
            return code, flag
    return None, None

async def main():
    raw_urls = []
    for src in SOURCES:
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as res:
                raw_urls.extend(decode_sub(res.read().decode("utf-8", errors="ignore")))
        except Exception:
            continue

    # Парсим и удаляем дубликаты
    parsed_nodes = []
    seen = set()
    for u in raw_urls:
        p = parse_vless(u)
        if p:
            key = (p["host"], p["port"])
            if key not in seen:
                seen.add(key)
                parsed_nodes.append(p)

    # 1. Отбираем ноды, у которых в названии ЕСТЬ европейские флаги/коды
    eu_candidates = []
    other_candidates = []

    for node in parsed_nodes:
        code, flag = extract_country_info(node["name"])
        if code and flag:
            node["country_code"] = code
            node["flag"] = flag
            eu_candidates.append(node)
        else:
            other_candidates.append(node)

    # Пингуем кандидатов пачкой (до 150 европейских + 50 на резерв)
    test_pool = eu_candidates[:150] + other_candidates[:50]
    tasks = [check_tcp_ping(n["host"], n["port"]) for n in test_pool]
    pings = await asyncio.gather(*tasks)

    valid_nodes = []
    for node, ping in zip(test_pool, pings):
        if ping is not None and ping < 500:
            node["ping"] = ping
            valid_nodes.append(node)

    # Сортируем строго от минимального пинга к большему
    valid_nodes.sort(key=lambda x: x["ping"])

    final_links = []
    fallback_links = []
    country_counters = {}

    for node in valid_nodes:
        query_str = urllib.parse.urlencode(node["params"])

        if "country_code" in node:
            code = node["country_code"]
            flag = node["flag"]
            count = country_counters.get(code, 0) + 1
            country_counters[code] = count

            new_title = f"{code} {flag} ouVPN #{count} ({int(node['ping'])}ms)"
            encoded_title = urllib.parse.quote(new_title)
            final_links.append(f"vless://{node['uuid']}@{node['host']}:{node['port']}?{query_str}#{encoded_title}")
        else:
            f_title = f"⚡ ouVPN Fast ({int(node['ping'])}ms)"
            fallback_links.append(f"vless://{node['uuid']}@{node['host']}:{node['port']}?{query_str}#{urllib.parse.quote(f_title)}")

        if len(final_links) >= 30:
            break

    # СТРАХОВКА: если чистых европейских серверов меньше 10, добираем из резервных быстрых
    if len(final_links) < 10:
        needed = 15 - len(final_links)
        final_links.extend(fallback_links[:needed])

    # Время по Москве (UTC+3)
    msk_tz = timezone(timedelta(hours=3))
    now_msk = datetime.now(msk_tz)
    
    date_formatted = now_msk.strftime("%Y-%m-%d / %H:%M (Moscow)")
    announce_date = now_msk.strftime("%y.%m.%d - %H:%M МСК")
    total_count = len(final_links)

    # Метаданные шапки
    header = [
        "# profile-title: 🎒 𝗼𝘂𝗩𝗣𝗡",
        "# profile-update-interval: 3",
        "#subscription-userinfo: download=14293651161088; total=0;",
        f"# Date/Time: {date_formatted}",
        f"# Количество: {total_count}",
        "# profile-web-page-url: https://oulan1.github.io/ouVPN/",
        "# support-url: https://t.me/oulanGift",
        f"# announce: 🌐 Дата последнего обновления: {announce_date}",
        ""
    ]

    full_content = "\n".join(header) + "\n" + "\n".join(final_links)

    with open("sub.txt", "w", encoding="utf-8") as f:
        f.write(full_content)

if __name__ == "__main__":
    asyncio.run(main())
