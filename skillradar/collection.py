"""Selenium collection following references/crawling's headless/wait/finally pattern."""
import ipaddress
import re
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, urlsplit, urlunsplit

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


def search_links(driver, query):
    search_url = 'https://html.duckduckgo.com/html/?q=' + quote_plus(query)
    driver.get(search_url)
    links = WebDriverWait(driver, 12).until(lambda d: d.find_elements(By.CSS_SELECTOR, 'a.result__a'))
    results, seen = [], set()
    for link in links[:15]:
        href = link.get_attribute('href') or ''
        parts = urlsplit(href)
        if parts.hostname in ('duckduckgo.com', 'www.duckduckgo.com', 'html.duckduckgo.com') and parts.path == '/l/':
            href = parse_qs(parts.query).get('uddg', [''])[0]
        try:
            public_url(href)
        except (ValueError, CollectionFailure):
            continue
        parts = urlsplit(href)
        href = urlunsplit((parts.scheme, parts.netloc, parts.path or '/', parts.query, ''))
        if href not in seen:
            seen.add(href)
            results.append({'title': link.text[:300], 'url': href})
    return search_url, results


def source_matches(url, base, subdomains=False):
    target, source = urlsplit(url), urlsplit(base)
    host = source.hostname.removeprefix('www.')
    if subdomains:
        return target.hostname == host or target.hostname.endswith('.' + host)
    # An external recruitment service is trusted only under the linked path.
    source_query, target_query = parse_qs(source.query), parse_qs(target.query)
    return (target.hostname == source.hostname and
            all(target_query.get(key) == value for key, value in source_query.items()) and
            (target.path == source.path or target.path.startswith(source.path.rstrip('/') + '/')))


def search_official_postings(driver, data):
    compact = lambda value: re.sub(r'\s+', '', value).casefold()
    company = compact(data.company)
    _, homepages = search_links(driver, data.company + ' 공식 홈페이지 official website')
    sources = []
    for item in homepages[:5]:
        parts = urlsplit(item['url'])
        # A search title alone is insufficient: inspect the corporate homepage.
        homepage_path = re.fullmatch(r'/(?:[a-z]{2}(?:[-_][a-z]{2})?/?){0,2}', parts.path, re.I)
        if company not in compact(item['title']) or not homepage_path or parts.query:
            continue
        try:
            driver.get(item['url'])
            WebDriverWait(driver, 8).until(lambda d: d.find_elements(By.TAG_NAME, 'body'))
            final_url = public_url(driver.current_url)
            if not source_matches(final_url, item['url'], subdomains=True) or company not in compact(driver.title):
                continue
            sources.append((final_url, True))
            # External career domains must be linked by the corporate site itself.
            for anchor in driver.find_elements(By.CSS_SELECTOR, 'a[href]'):
                if not re.search(r'채용|직무|careers?|recruit|jobs?', anchor.text, re.I):
                    continue
                try:
                    href = public_url(anchor.get_attribute('href') or '')
                except (ValueError, CollectionFailure):
                    continue
                sources.append((href, False))
            break
        except (WebDriverException, ValueError, CollectionFailure):
            continue
    if not sources:
        raise CollectionFailure('기업의 공식 홈페이지를 확인하지 못했습니다. 공식 URL 또는 본문을 직접 입력하세요.')
    query = ' '.join(filter(None, [data.company, data.division, data.role, '직무소개 채용']))
    search_url, results = search_links(driver, query)
    candidates = [item for item in results
                  if all(compact(term) in compact(item['title']) for term in (data.division, data.role) if term)
                  and any(source_matches(item['url'], base, subdomains) for base, subdomains in sources)]
    if not candidates:
        raise CollectionFailure('공식 출처의 직무정보를 찾지 못했습니다. 공식 URL 또는 본문을 직접 입력하세요.')
    return {'kind': 'candidates', 'query': query, 'source_url': search_url, 'candidates': candidates[:5]}


def collect_posting(data):
    try:
        url = public_url(data.url) if data.url else None
        with browser() as driver:
            if url is None:
                return search_official_postings(driver, data)
            driver.get(url)
            WebDriverWait(driver, 12).until(lambda d: d.find_elements(By.TAG_NAME, 'body'))
            # Some postings render their text after the body has appeared.
            text = WebDriverWait(driver, 12).until(lambda d: d.execute_script(r"""
                const nodes = [...document.querySelectorAll('main, article, [role="main"], #main-content')];
                const root = nodes.sort((a,b)=>(b.innerText||'').length-(a.innerText||'').length)[0] || document.body;
                const copy = root.cloneNode(true);
                const originals = [...root.querySelectorAll('*')], clones = [...copy.querySelectorAll('*')];
                for (let i = originals.length - 1; i >= 0; i--) {
                    const style = getComputedStyle(originals[i]);
                    if (style.display === 'none' || style.visibility === 'hidden' || originals[i].hidden || originals[i].getAttribute('aria-hidden') === 'true') clones[i].remove();
                }
                copy.querySelectorAll('script,style,nav,footer,header,button,iframe,form,[role="dialog"]').forEach(n=>n.remove());
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
