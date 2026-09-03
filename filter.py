import asyncio
import base64
from datetime import datetime, timezone, timedelta
import re
import socket
import ssl
import time
import urllib.parse
import urllib.request

# Расширенные проверенные источники (с упором на Reality и свежие VLESS)
SOURCES = [
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/vless",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/ndsphon/v2ray-collector/main/vless.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2"
]

# Европа: флаги и коды стран
EU_FLAGS = {
    "NL": "🇳🇱", "DE": "🇩🇪", "FI": "🇫🇮", "SE": "🇸🇪", "FR": "🇫🇷",
    "PL": "🇵🇱", "GB": "🇬🇧", "AT": "🇦🇹", "CH": "🇨🇭", "CZ": "🇨🇿",
    "NO": "🇳🇴", "EE": "🇪🇪", "LV": "🇱🇻", "LT": "🇱🇹", "IT": "🇮🇹",
    "ES": "🇪🇸", "IS": "🇮🇸", "IE": "🇮🇪", "DK": "🇩🇰", "BE": "🇧🇪"
}

# Регулярка для извлечения кода страны или эмодзи флага из имени
FLAG_TO_CODE = {v: k for k, v in EU_FLAGS.items()}
COUNTRY_REGEX = re.compile(
    r"(🇳🇱|🇩🇪|🇫🇮|🇸🇪|🇫🇷|🇵🇱|🇬🇧|🇦🇹|🇨🇭|🇨🇿|🇳🇴|🇪🇪|🇱🇻|🇱🇹|🇮🇹|🇪🇸|🇮🇸|🇮🇪|🇩🇰|🇧🇪|\b(NL|DE|FI|SE|FR|PL|GB|AT|CH|CZ|NO|EE|LV|LT|IT|ES|IS|IE|DK|BE)\b)",
    re.IGNORECASE
)

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
        security = params.get("security", "").lower()

        # Отсекаем заведомо нерабочие связки с фейковыми заголовками
        if params.get("headerType") == "http":
            return None

        raw_name = urllib.parse.unquote(parsed.fragment)
        return {
            "uuid": uuid,
            "host": host,
            "port": port,
            "params": params,
            "security": security,
            "name": raw_name,
            "raw": url
        }
    except Exception:
        return None

def extract_country(name: str):
    match = COUNTRY_REGEX.search(name)
    if not match:
        return None, None
    val = match.group(0)
    if val in FLAG_TO_CODE:
        code = FLAG_TO_CODE[val]
        return code, val
    code = val.upper()
    if code in EU_FLAGS:
        return code, EU_FLAGS[code]
    return None, None

async def verify_socket(host: str, port: int, sni: str = None, is_tls: bool = False, timeout: float = 1.6):
    """Проверяет не просто TCP-порт, но и базовый TLS-отклик, если нода с TLS/Reality"""
    loop = asyncio.get_running_loop()
    start = time.perf_counter()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        await asyncio.wait_for(loop.sock_connect(sock, (host, port)), timeout=timeout)
        
        # Если нода заявляет TLS/Reality, проверяем, отвечает ли сервер на TLS ClientHello
        if is_tls and port in [443, 8443, 2053, 2083, 2087, 2096]:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            server_hostname = sni if sni else host
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: ctx.wrap_socket(sock, server_hostname=server_hostname)),
                    timeout=1.2
                )
            except Exception:
                # Если порт открыт, но TLS-сертификат/хэндшейк сброшен — нода мертва
                sock.close()
                return None

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

    # Приоритет Reality и современным протоколам над старым незашифрованным TCP
    eu_nodes = []
    for node in parsed_nodes:
        code, flag = extract_country(node["name"])
        if code:
            node["country"] = code
            node["flag"] = flag
            # Даем бонус Reality серверам
            node["is_reality"] = (node["security"] == "reality")
            eu_nodes.append(node)

    # Сначала проверяем ноды Reality, затем остальные
    eu_nodes.sort(key=lambda x: not x["is_reality"])
    pool_to_test = eu_nodes[:160]

    # Параллельное тестирование сокетов с валидацией TLS
    tasks = []
    for n in pool_to_test:
        is_tls = n["security"] in ["tls", "reality"]
        sni = n["params"].get("sni") or n["params"].get("peer")
        tasks.append(verify_socket(n["host"], n["port"], sni=sni, is_tls=is_tls))

    pings = await asyncio.gather(*tasks)

    alive_nodes = []
    for node, ping in zip(pool_to_test, pings):
        if ping is not None and ping < 450:
            node["ping"] = ping
            alive_nodes.append(node)

    # Сортировка по задержке
    alive_nodes.sort(key=lambda x: x["ping"])

    # Балансировка стран: не больше 4 серверов от одной страны, чтобы не забивать всё Германией
    MAX_PER_COUNTRY = 4
    country_distribution = {}
    selected_nodes = []

    for node in alive_nodes:
        c = node["country"]
        if country_distribution.get(c, 0) < MAX_PER_COUNTRY:
            country_distribution[c] = country_distribution.get(c, 0) + 1
            selected_nodes.append(node)
        if len(selected_nodes) >= 28:
            break

    # Если лимит не набрался, добираем остальные выжившие
    if len(selected_nodes) < 20:
        for node in alive_nodes:
            if node not in selected_nodes:
                selected_nodes.append(node)
            if len(selected_nodes) >= 25:
                break

    # Формируем финальные VLESS ссылки с нумерацией
    final_links = []
    country_counters = {}
    for node in selected_nodes:
        c = node["country"]
        flag = node["flag"]
        cnt = country_counters.get(c, 0) + 1
        country_counters[c] = cnt

        type_tag = "Reality" if node.get("is_reality") else "VLESS"
        new_title = f"{c} {flag} ouVPN #{cnt} [{type_tag}] ({int(node['ping'])}ms)"
        encoded_title = urllib.parse.quote(new_title)

        query_str = urllib.parse.urlencode(node["params"])
        final_links.append(f"vless://{node['uuid']}@{node['host']}:{node['port']}?{query_str}#{encoded_title}")

    # Время МСК (UTC+3)
    msk_tz = timezone(timedelta(hours=3))
    now_msk = datetime.now(msk_tz)
    date_formatted = now_msk.strftime("%Y-%m-%d / %H:%M (Moscow)")
    announce_date = now_msk.strftime("%y.%m.%d - %H:%M МСК")

    # Обновленная шапка: удален userinfo со счетчиком байт, иконка заменена на корону
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
