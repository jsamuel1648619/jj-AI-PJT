"""Selenium collection following references/crawling's headless/wait/finally pattern."""
import ipaddress
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


class CollectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    url: str = Field(default='', max_length=2000)
    company: str = Field(default='', max_length=100)
    division: str = Field(default='', max_length=100)
    role: str = Field(default='', max_length=100)

    @model_validator(mode='after')
    def has_query(self):
        if not self.url and not (self.company and self.role):
            raise ValueError('URL 또는 기업명과 직무명이 필요합니다.')
        return self


class CollectionFailure(Exception):
    pass


def public_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('공개 HTTP(S) URL을 입력하세요.')
    if parts.port not in (None, 80, 443):
        raise ValueError('기본 웹 포트만 지원합니다.')
    try:
        addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise CollectionFailure('출처 주소를 확인할 수 없습니다.') from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('로컬·내부 네트워크 주소는 수집할 수 없습니다.')
    return url


@contextmanager
def browser():
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1440,1000')
    options.add_argument('--disable-notifications')
    options.page_load_strategy = 'eager'
    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(25)
        driver.set_script_timeout(10)
        yield driver
    finally:
        if driver is not None:
            try:
                driver.quit()
            except WebDriverException:
                pass


def collect_posting(data):
    try:
        url = public_url(data.url) if data.url else None
        with browser() as driver:
            if url is None:
                query = ' '.join(filter(None, [data.company, data.division, data.role, '채용 공고']))
                search_url = 'https://html.duckduckgo.com/html/?q=' + quote_plus(query)
                driver.get(search_url)
                links = WebDriverWait(driver, 12).until(lambda d: d.find_elements(By.CSS_SELECTOR, 'a.result__a'))
                candidates, seen = [], set()
                for link in links[:15]:
                    href = link.get_attribute('href') or ''
                    if 'duckduckgo.com/l/' in href:
                        href = parse_qs(urlsplit(href).query).get('uddg', [''])[0]
                    if not href or href in seen:
                        continue
                    try:
                        public_url(href)
                    except (ValueError, CollectionFailure):
                        continue
                    seen.add(href)
                    candidates.append({'title': link.text[:300], 'url': href})
                    if len(candidates) == 5:
                        break
                if not candidates:
                    raise CollectionFailure('검색 결과를 찾지 못했습니다.')
                return {'kind': 'candidates', 'query': query, 'source_url': search_url, 'candidates': candidates}
            driver.get(url)
            WebDriverWait(driver, 12).until(lambda d: d.find_elements(By.TAG_NAME, 'body'))
            # Some postings render their text after the body has appeared.
            text = WebDriverWait(driver, 12).until(lambda d: d.execute_script(r"""
                const nodes = [...document.querySelectorAll('main, article, [role="main"]')];
                const root = nodes.sort((a,b)=>(b.innerText||'').length-(a.innerText||'').length)[0] || document.body;
                const copy = root.cloneNode(true);
                copy.querySelectorAll('script,style,nav,footer,header,button').forEach(n=>n.remove());
                // Detached nodes lose rendered innerText line breaks: preserve section boundaries.
                copy.querySelectorAll('br').forEach(n=>n.replaceWith('\n'));
                copy.querySelectorAll('p,div,li,h1,h2,h3,h4,section,article,tr').forEach(n=>n.append('\n'));
                const text = (copy.textContent || '').replace(/\n{3,}/g, '\n\n').trim();
                return text.length >= 80 ? text : null;
            """))
            final_url = public_url(driver.current_url)
            return {'kind': 'posting', 'title': driver.title[:300], 'body': text[:30000],
                    'source_url': final_url, 'requested_url': url, 'truncated': len(text) > 30000,
                    'collected_at': datetime.now(timezone.utc).isoformat()}
    except WebDriverException as exc:
        raise CollectionFailure('브라우저 실행 또는 페이지 수집에 실패했습니다. 본문을 직접 입력하세요.') from exc
