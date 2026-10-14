"""Импорт и валидация прокси из JSON-файла (по умолчанию ./proxies_data.json)."""
import asyncio
import json
import os
import sys
import time
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import init_db, get_db
from app.proxy_pool import normalize_proxy_string, mask_proxy_url, ensure_schema

PROXIES_DATA_PATH = os.getenv("PROXIES_DATA_PATH", "./proxies_data.json")


async def _raw_test_proxy(url: str):
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(proxy=url, timeout=3.5, verify=False) as client:
            try:
                resp = await client.get("https://id.twitch.tv/oauth2/validate")
                if resp.status_code in {200, 401, 400}:
                    lat = (time.perf_counter() - t0) * 1000
                    return {"url": url, "status": "ok" if lat < 1500 else "slow", "latency_ms": round(lat, 1)}
            except Exception:
                pass
            resp2 = await client.get("https://httpbin.org/ip")
            if resp2.status_code == 200:
                lat = (time.perf_counter() - t0) * 1000
                return {"url": url, "status": "ok" if lat < 1500 else "slow", "latency_ms": round(lat, 1)}
    except Exception:
        return None
    return None


async def test_proxy(url: str, sem: asyncio.Semaphore):
    async with sem:
        try:
            return await asyncio.wait_for(_raw_test_proxy(url), timeout=4.0)
        except Exception:
            return None


async def main():
    await init_db()
    await ensure_schema()

    if not os.path.exists(PROXIES_DATA_PATH):
        print(f"❌ Файл не найден: {PROXIES_DATA_PATH}")
        return

    with open(PROXIES_DATA_PATH, "r", encoding="utf-8") as f:
        d = json.load(f)

    proxies = d.get("proxies", [])
    alive = [p for p in proxies if p.get("alive")]
    alive.sort(key=lambda x: x.get("ping", 9999))
    print(f"📂 Загружено из файла: {len(proxies)} всего, {len(alive)} живых в кэше.")

    # Приоритет: сначала все живые HTTP (они надежнее для Twitch API), затем топ-1500 быстрых SOCKS
    http_alive = [p for p in alive if p.get("proto") in ("http", "https")]
    socks_alive = [p for p in alive if p.get("proto") in ("socks5", "socks4")]

    candidates_list = http_alive + socks_alive[:1500]
    candidates = []
    for p in candidates_list:
        proto = p.get("proto", "http")
        ip = p.get("ip")
        port = p.get("port")
        url = f"{proto}://{ip}:{port}"
        norm = normalize_proxy_string(url)
        if norm and norm not in candidates:
            candidates.append(norm)

    print(f"⚡ Запуск глубокой проверки {len(candidates)} кандидатов (HTTP: {len(http_alive)}, SOCKS: {len(candidates) - len(http_alive)})...")
    sem = asyncio.Semaphore(80)
    tasks = [test_proxy(u, sem) for u in candidates]
    t_start = time.time()
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - t_start

    confirmed = [r for r in results if r]
    confirmed.sort(key=lambda x: x["latency_ms"])
    print(f"✅ Подтверждено живых к Twitch: {len(confirmed)} за {elapsed:.1f} сек!")

    db = await get_db()
    now = time.time()
    saved = 0
    try:
        for c in confirmed:
            try:
                await db.execute("""
                    INSERT INTO proxy_pool (url, label, status, latency_ms, last_checked_at, created_at)
                    VALUES (?, 'pro_finder', ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        status = excluded.status,
                        latency_ms = excluded.latency_ms,
                        last_checked_at = excluded.last_checked_at
                """, (c["url"], c["status"], c["latency_ms"], now, now))
                saved += 1
            except Exception:
                pass
        await db.commit()
    finally:
        await db.close()

    print(f"💾 Сохранено/обновлено в пуле панели: {saved} прокси!")
    print("\nТоп-15 лучших прокси из файла:")
    for i, x in enumerate(confirmed[:15], 1):
        u = x["url"]
        ms = x["latency_ms"]
        st = x["status"]
        print(f"  {i:2d}. {u} — {ms} ms ({st})")


if __name__ == "__main__":
    asyncio.run(main())
