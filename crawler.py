"""
crawler.py — 검도나우 대회 일정 크롤러 v2
- sites.json 을 읽어 각 사이트를 크롤링
- events.json 으로 저장
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
DELAY   = 2
YEAR    = datetime.now().year

# 대회 공고 판별 키워드
CONTEST_KEYWORDS = ["대회", "선수권", "페스티벌", "오픈", "컵", "기념", "체육대회"]

# 제외할 링크 텍스트 (메뉴/네비 오인 방지)
EXCLUDE_KEYWORDS = [
    "로그인", "회원가입", "공지사항", "자유게시판", "갤러리", "홈", "HOME",
    "대회참가접수", "대회연혁", "대회공문", "대회접수", "연혁", "공문", "접수",
    "전국체육대회", "전국소년체육대회", "전국동계체육대회",
    "도민체육대회", "도민생활체육대회", "어르신생활체육대회", "여성생활체육대회",
    "더보기", "이전", "다음", "목록"
]

def make_id(name, date):
    return hashlib.md5(f"{name}_{date}".encode()).hexdigest()[:10]

def is_contest(title):
    title = title.strip()
    if len(title) < 6:
        return False
    if any(ex in title for ex in EXCLUDE_KEYWORDS):
        return False
    return any(kw in title for kw in CONTEST_KEYWORDS)

def extract_date_korean(text):
    """
    '02월 06일', '02월 06일 ~ 02월 09일' 형식 추출
    반환: (start "YYYY-MM-DD", end "YYYY-MM-DD")
    """
    # MM월 DD일 ~ MM월 DD일
    m = re.search(r'(\d{1,2})월\s*(\d{1,2})일\s*[~～]\s*(\d{1,2})월\s*(\d{1,2})일', text)
    if m:
        sm, sd, em, ed = m.group(1), m.group(2), m.group(3), m.group(4)
        return (f"{YEAR}-{sm.zfill(2)}-{sd.zfill(2)}",
                f"{YEAR}-{em.zfill(2)}-{ed.zfill(2)}")

    # MM월 DD일 (단일)
    m = re.search(r'(\d{1,2})월\s*(\d{1,2})일', text)
    if m:
        sm, sd = m.group(1), m.group(2)
        d = f"{YEAR}-{sm.zfill(2)}-{sd.zfill(2)}"
        return d, d

    return "", ""

def extract_date_numeric(text):
    """
    '2026.05.17', '2026-05-17' 형식 추출
    """
    m = re.search(r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})', text)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        start = f"{y}-{mo}-{d}"
        # 종료일
        end_m = re.search(r'[~～]\s*(\d{4})?[.\-]?(\d{1,2})[.\-](\d{1,2})', text[m.end():])
        if end_m:
            ey = end_m.group(1) or y
            emo = end_m.group(2).zfill(2)
            ed  = end_m.group(3).zfill(2)
            return start, f"{ey}-{emo}-{ed}"
        return start, start
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

def make_event(title, start, end, link, site_id):
    return {
        "id": make_id(title, start),
        "name": title.strip(),
        "date": start,
        "endDate": end or start,
        "location": "",
        "type": "",
        "open": "오픈" in title or "사회인" in title,
        "source": link,
        "source_site": site_id,
        "note": "",
        "updated": datetime.now().strftime("%Y-%m-%d")
    }

# ── 대한검도회 (kumdo.org) ─────────────────────────
def parse_kumdo_org(site):
    """
    게시판 목록에서 제목 + 날짜 추출.
    제목 텍스트에 날짜·장소가 섞여 있으므로 분리 처리.
    """
    results = []
    soup = fetch(site["url"])
    if not soup:
        return results

    rows = soup.select("tr")
    for row in rows:
        a = row.select_one("td.td_subject a, td.subject a, .bo_tit a")
        if not a:
            continue

        # 제목만 (링크 텍스트의 첫 줄 또는 span 제거 후)
        # 그누보드는 보통 <a> 안에 날짜·장소까지 포함해서 렌더링됨
        raw = a.get_text(" ", strip=True)

        # 날짜 패턴이 포함된 경우 제목과 날짜 분리
        # 제목은 날짜 패턴 이전 텍스트
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

        link = urljoin(site["url"], a.get("href", ""))
        start, end = extract_date_korean(date_part)

        # 날짜 못 찾으면 목록 날짜 컬럼에서 시도
        if not start:
            date_td = row.select_one("td.td_datetime, td.datetime")
            if date_td:
                start, end = extract_date_numeric(date_td.get_text())

        results.append(make_event(title, start, end, link, site["id"]))

    return results

# ── 그누보드 계열 (서울시검도회, 경남검도회, 고양시검도회 등) ──
def parse_gnuboard(site):
    results = []
    soup = fetch(site["url"])
    if not soup:
        return results

    rows = soup.select("tr")
    for row in rows:
        a = row.select_one("td.td_subject a, td.subject a, .bo_tit a")
        if not a:
            continue

        title = a.get_text(strip=True)
        if not is_contest(title):
            continue

        link = urljoin(site["url"], a.get("href", ""))

        # 날짜: 목록 컬럼 우선
        start, end = "", ""
        date_td = row.select_one("td.td_datetime, td.datetime, .td_num2")
        if date_td:
            start, end = extract_date_numeric(date_td.get_text())

        # 제목에서 날짜 시도
        if not start:
            start, end = extract_date_numeric(title)
        if not start:
            start, end = extract_date_korean(title)

        # 날짜 못 찾으면 게시글 본문 직접 방문해서 추출
        if not start and link:
            time.sleep(1)
            post_soup = fetch(link)
            if post_soup:
                body = post_soup.select_one("#bo_v_con, .bo_v_con, .view_content, #content")
                if body:
                    body_text = body.get_text(" ", strip=True)
                    start, end = extract_date_korean(body_text)
                    if not start:
                        start, end = extract_date_numeric(body_text)

        results.append(make_event(title, start, end, link, site["id"]))

    return results

# ── dmboard 계열 (남원시검도회, 가평군검도회) ──
def parse_dmboard(site):
    results = []
    soup = fetch(site["url"])
    if not soup:
        return results

    for a in soup.select("table tr td a, .list_wrap li a"):
        title = a.get_text(strip=True)
        if not is_contest(title):
            continue

        link = urljoin(site["url"], a.get("href", ""))
        start, end = extract_date_numeric(title)
        if not start:
            start, end = extract_date_korean(title)

        results.append(make_event(title, start, end, link, site["id"]))

    return results

# ── 경상북도검도회 (custom) ──
def parse_kbkumdo(site):
    results = []
    soup = fetch(site["url"])
    if not soup:
        return results

    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not is_contest(title):
            continue
        link = urljoin(site["url"], a.get("href", ""))
        start, end = extract_date_numeric(title)
        if not start:
            start, end = extract_date_korean(title)
        results.append(make_event(title, start, end, link, site["id"]))

    # 중복 제거
    seen, unique = set(), []
    for r in results:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)
    return unique

# ── 강원도체육회: 검도 관련 링크만 (키워드 필터 강화) ──
def parse_gwsports(site):
    # 이 사이트는 검도 전용이 아니므로 스킵
    print("  → 강원도체육회: 검도 전용 페이지 없음, 스킵")
    return []

# ── 인천시검도회 ──
def parse_incheonkumdo(site):
    results = []
    soup = fetch(site["url"])
    if not soup:
        return results

    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not is_contest(title):
            continue
        if len(title) < 8:
            continue
        link = urljoin(site["url"], a.get("href", ""))
        start, end = extract_date_numeric(title)
        if not start:
            start, end = extract_date_korean(title)
        results.append(make_event(title, start, end, link, site["id"]))

    seen, unique = set(), []
    for r in results:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)
    return unique

# ── 대선검도회 ──
def parse_dskumdo(site):
    results = []
    soup = fetch(site["url"])
    if not soup:
        return results

    # 공문 게시판에서만 대회 관련 글 추출
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not is_contest(title):
            continue
        if len(title) < 8:
            continue
        # 네비 메뉴 제외
        if any(ex in title for ex in ["대회 연혁", "대회 공문", "대회 접수", "대회참가"]):
            continue
        link = urljoin(site["url"], a.get("href", ""))
        start, end = extract_date_numeric(title)
        if not start:
            start, end = extract_date_korean(title)
        results.append(make_event(title, start, end, link, site["id"]))

    seen, unique = set(), []
    for r in results:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)
    return unique

# ── 파서 라우터 ──
PARSERS = {
    "kumdo_org":    parse_kumdo_org,
    "kbkumdo":      parse_kbkumdo,
    "gnkumdo":      parse_gnuboard,
    "seoulkumdo":   parse_gnuboard,
    "gwsports":     parse_gwsports,
    "snsports":     lambda s: [],
    "incheonkumdo": parse_incheonkumdo,
    "nwkumdo":      parse_dmboard,
    "kkumdo":       parse_gnuboard,
    "gpkumdo":      parse_dmboard,
    "dskumdo":      parse_dskumdo,
}

def load_manual(path="manual_events.json"):
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
    print(f"검도나우 크롤러 v2 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    with open("sites.json", encoding="utf-8") as f:
        sites = json.load(f)

    all_events = []

    for site in sites:
        if not site.get("active", True):
            print(f"⏭  건너뜀: {site['name']} (active=false)")
            continue

        print(f"🔍 크롤링: {site['name']}")
        parser = PARSERS.get(site["id"], parse_gnuboard)

        try:
            events = parser(site)
            print(f"   → {len(events)}건 발견")
            all_events.extend(events)
        except Exception as e:
            print(f"   ⚠️  오류: {e}")

        time.sleep(DELAY)

    # 수동 입력 병합 (수동이 우선)
    manual = load_manual()
    if manual:
        print(f"\n📝 수동 입력: {len(manual)}건")
        all_events = manual + all_events

    # ID 기준 중복 제거
    seen_ids, deduped = set(), []
    for ev in all_events:
        if ev["id"] not in seen_ids:
            seen_ids.add(ev["id"])
            deduped.append(ev)

    # 날짜순 정렬 (날짜 없는 항목은 뒤로)
    deduped.sort(key=lambda x: x.get("date") or "9999")

    output = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(deduped),
        "events": deduped
    }

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✅ 완료: {len(deduped)}건 → events.json 저장")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
