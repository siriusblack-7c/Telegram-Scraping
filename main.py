import aiohttp
import asyncio
from re import search, compile
from argparse import ArgumentParser
from datetime import datetime
from fake_useragent import UserAgent
from aiohttp_socks import ProxyConnector

# Regular expression for matching proxy patterns
REGEX = compile(
    r"(?:^|\D)?(("+ r"(?:[1-9]|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    + r"\." + r"(?:\d|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    + r"\." + r"(?:\d|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    + r"\." + r"(?:\d|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    + r"):" + (r"(?:\d|[1-9]\d{1,3}|[1-5]\d{4}|6[0-4]\d{3}"
    + r"|65[0-4]\d{2}|655[0-2]\d|6553[0-5])")
    + r")(?:\D|$)"
)

def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

class Telegram:
    def __init__(self, channel: str, post: int, concurrency: int = 100) -> None:
        self.channel = channel
        self.post = post
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)
        log(f"Initialized with channel: @{channel}, post: {post}, concurrency: {concurrency}")

    async def request(self, proxy: str, proxy_type: str):
        proxy_url = f"{proxy_type}://{proxy}"
        try:
            async with self.semaphore:
                connector = ProxyConnector.from_url(proxy_url)
                jar = aiohttp.CookieJar(unsafe=True)
                async with aiohttp.ClientSession(cookie_jar=jar, connector=connector) as session:
                    user_agent = UserAgent().random
                    headers = {
                        "referer": f"https://t.me/{self.channel}/{self.post}",
                        "user-agent": user_agent,
                    }
                    async with session.get(
                        f"https://t.me/{self.channel}/{self.post}?embed=1&mode=tme",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as embed_response:
                        if jar.filter_cookies(embed_response.url).get("stel_ssid"):
                            views_token = search(
                                'data-view="([^"]+)"', await embed_response.text()
                            )
                            if views_token:
                                views_response = await session.post(
                                    "https://t.me/v/?views=" + views_token.group(1),
                                    headers={
                                        "referer": f"https://t.me/{self.channel}/{self.post}?embed=1&mode=tme",
                                        "user-agent": user_agent,
                                        "x-requested-with": "XMLHttpRequest",
                                    },
                                    timeout=aiohttp.ClientTimeout(total=5),
                                )
                                if (
                                    await views_response.text() == "true"
                                    and views_response.status == 200
                                ):
                                    log("SUCCESS: View sent")
                                else:
                                    log("FAILED: View not registered")
                            else:
                                log("ERROR: No view token found")
                        else:
                            log("ERROR: No cookies received")
        except Exception as e:
            log(f"ERROR: Proxy connection failed - {proxy_type}://{proxy} - {str(e)[:50]}...")
        finally:
            if 'jar' in locals():
                jar.clear()

    async def run_proxies_continuous(self, lines: list, proxy_type: str):
        log(f"Starting continuous mode with {len(lines)} proxies of type {proxy_type}")
        
        tasks = []
        for proxy in lines:
            task = asyncio.create_task(self.continuous_request(proxy, proxy_type))
            tasks.append(task)
        
        await asyncio.gather(*tasks)

    async def continuous_request(self, proxy: str, proxy_type: str):
        
        while True:
            await self.request(proxy, proxy_type)

    async def run_auto_continuous(self):
        log("Starting continuous auto mode")
        while True:
            auto = Auto()
            await auto.init()
            
            if not auto.proxies:
                log("No proxies found, retrying in 60 seconds...")
                await asyncio.sleep(60)
                continue
                
            log(f"Auto scraping complete. Found {len(auto.proxies)} proxies")
            
            tasks = []
            for proxy_type, proxy in auto.proxies:
                task = asyncio.create_task(self.continuous_request(proxy, proxy_type))
                tasks.append(task)
            
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                log(f"Error in auto mode: {str(e)}")
                log("All proxy tasks failed, rescanning...")

    async def run_rotated_continuous(self, proxy: str, proxy_type: str):
        log(f"Starting continuous rotated mode with proxy {proxy_type}://{proxy}")
        
        tasks = []
        for _ in range(self.concurrency * 5):
            task = asyncio.create_task(self.continuous_request(proxy, proxy_type))
            tasks.append(task)
        
        await asyncio.gather(*tasks)

class Auto:
    def __init__(self):
        self.proxies = []
        try:
            with open("auto/http.txt", "r") as file:
                self.http_sources = file.read().splitlines()
                log(f"Loaded {len(self.http_sources)} HTTP proxy sources")
                
            with open("auto/socks4.txt", "r") as file:
                self.socks4_sources = file.read().splitlines()
                log(f"Loaded {len(self.socks4_sources)} SOCKS4 proxy sources")
                
            with open("auto/socks5.txt", "r") as file:
                self.socks5_sources = file.read().splitlines()
                log(f"Loaded {len(self.socks5_sources)} SOCKS5 proxy sources")
                
        except FileNotFoundError as e:
            log(f"ERROR: Auto file not found - {str(e)}")
            exit()
        
        log("Starting proxy scraping from sources...")

    async def scrap(self, source_url, proxy_type):
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"user-agent": UserAgent().random}
                log(f"Scraping {proxy_type} proxies from {source_url}")
                async with session.get(
                    source_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    html = await response.text()
                    matches = REGEX.finditer(html)
                    found_proxies = [(proxy_type, match.group(1)) for match in matches]
                    self.proxies.extend(found_proxies)
                    log(f"Found {len(found_proxies)} {proxy_type} proxies from {source_url}")
        except Exception as e:
            log(f"ERROR: Failed to scrape from {source_url} - {str(e)[:100]}")
            with open("error.txt", "a", encoding="utf-8", errors="ignore") as f:
                f.write(f"{source_url} -> {e}\n")

    async def init(self):
        tasks = []
        self.proxies.clear()
        sources_list = [
            (self.http_sources, "http"),
            (self.socks4_sources, "socks4"),
            (self.socks5_sources, "socks5"),
        ]
        for sources, proxy_type in sources_list:
            tasks.extend([self.scrap(source_url, proxy_type) for source_url in sources])
        await asyncio.gather(*tasks)
        log(f"Proxy scraping complete. Total proxies found: {len(self.proxies)}")

async def main():
    parser = ArgumentParser()
    parser.add_argument("-c", "--channel", dest="channel", help="Channel user", type=str, required=True)
    parser.add_argument("-pt", "--post", dest="post", help="Post number", type=int, required=True)
    parser.add_argument("-t", "--type", dest="type", help="Proxy type", type=str, required=False)
    parser.add_argument("-m", "--mode", dest="mode", help="Proxy mode", type=str, required=True)
    parser.add_argument("-p", "--proxy", dest="proxy", help="Proxy file path or user:password@host:port", type=str, required=False)
    parser.add_argument("-cc", "--concurrency", dest="concurrency", help="Maximum concurrent requests", type=int, default=200)
    args = parser.parse_args()
    
    log(f"Telegram Auto Views started with mode: {args.mode}")
    api = Telegram(args.channel, args.post, args.concurrency if hasattr(args, 'concurrency') else 200)
    
    if args.mode[0] == "l":
        with open(args.proxy, "r") as file:
            lines = file.read().splitlines()
        log(f"Loaded {len(lines)} proxies from file {args.proxy}")
        await api.run_proxies_continuous(lines, args.type)
    elif args.mode[0] == "r":
        log(f"Starting rotated mode with single proxy: {args.proxy}")
        await api.run_rotated_continuous(args.proxy, args.type)
    else:
        await api.run_auto_continuous()

if __name__ == "__main__":
    log("Program started")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Program terminated by user")
    except Exception as e:
        log(f"Unhandled exception: {str(e)}")