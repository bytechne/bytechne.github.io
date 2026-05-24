"""
crawler.py — 검도나우 크롤러
- 대한검도회(kumdo.org) 대회 일정만 크롤링
- manual_events.json 과 병합하여 events.json 생성
- 수동 실행 전용 (GitHub Actions에서 Run workflow 버튼으로 실행)
"""

import json
import re
import time
import hashlib
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KendoNowBot/1.0)"}
TIMEOUT = 15
YEAR    = datetime.now().year

KUMDO_URL = "https://www.kumdo.org/bbs/board.php?bo_table=schedule_guide&sca=%EB%8C%80%ED%9A%8C"

# 대회 공고 판별 키워드
CONTEST_KEYWORDS = ["대회", "선수권", "페스티벌", "오픈", "컵", "체육대회"]

def make_id(name, date):
    return hashlib.md5(f"{name}_{date}".encode()).hexdigest()[:10]

def is_contest(title):
    title = title.strip()
    if len(title) < 6:
        return False
    return any(kw in title for kw in CONTEST_KEYWORDS)

def extract_date_korean(text):
    """MM월 DD일 ~ MM월 DD일 형식 추출"""
    m = re.search(r'(\d{1,2})월\s*(\d{1,2})일\s*[~～]\s*(\d{1,2})월\s*(\d{1,2})일', text)
    if m:
        sm, sd, em, ed = m.group(1), m.group(2), m.group(3), m.group(4)
        return (f"{YEAR}-{sm.zfill(2)}-{sd.zfill(2)}",
                f"{YEAR}-{em.zfill(2)}-{ed.zfill(2)}")
    m = re.search(r'(\d{1,2})월\s*(\d{1,2})일', text)
    if m:
        d = f"{YEAR}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
        return d, d
    return "", ""

def fetch(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  ⚠️  fetch 실패: {url} → {e}")
        return None

def crawl_kumdo():
    """대한검도회 대회 일정 크롤링"""
    print(f"🔍 대한검도회 크롤링 중...")
    results = []
    soup = fetch(KUMDO_URL)
    if not soup:
        return results

    rows = soup.select("tr")
    for row in rows:
        a = row.select_one("td.td_subject a, td.subject a, .bo_tit a")
        if not a:
            continue

        raw = a.get_text(" ", strip=True)

        # 제목과 날짜 분리 (날짜 패턴 이전이 제목)
        date_match = re.search(r'\d{2}월\s*\d{2}일', raw)
        if date_match:
            title = raw[:date_match.start()].strip()
            date_part = raw[date_match.start():]
        else:
            title = raw
            date_part = raw

        if not title:
            title = raw

        if not is_contest(title):
            continue

        link = urljoin(KUMDO_URL, a.get("href", ""))
        start, end = extract_date_korean(date_part)

        results.append({
            "id": make_id(title, start),
            "name": title.strip(),
            "date": start,
            "endDate": end or start,
            "location": "",
            "type": "official",   # 대한검도회 크롤링 데이터 식별자
            "open": "오픈" in title or "사회인" in title,
            "source": link,
            "source_site": "kumdo_org",
            "note": "",
            "updated": datetime.now().strftime("%Y-%m-%d")
        })

    print(f"   → {len(results)}건 수집")
    return results

def load_manual(path="manual_events.json"):
    """운영자 직접 입력 데이터 로드"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"  ⚠️  manual_events.json 로드 실패: {e}")
        return []

def main():
    print(f"\n{'='*50}")
    print(f"검도나우 크롤러 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    # 대한검도회 크롤링
    crawled = crawl_kumdo()

    # 날짜순 정렬
    crawled.sort(key=lambda x: x.get("date") or "9999")

    # events.json 저장 (참고용 - 웹사이트와 미연동)
    output = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(crawled),
        "events": crawled
    }

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✅ 완료: {len(crawled)}건 → events.json 저장 (참고용)")
    print(f"   웹사이트 반영은 manual_events.json 을 직접 편집해주세요.")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
