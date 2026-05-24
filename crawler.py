"""
crawler.py — By Techne 검도 대회 일정 크롤러
- sites.json 을 읽어 각 사이트를 크롤링
- 대회 공고 제목/날짜/링크를 추출해 events.json 으로 저장
- GitHub Actions 에서 주 1회 자동 실행됨
"""

import json
import re
import time
import hashlib
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ── 설정 ──────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BytechneBot/1.0)"
}
TIMEOUT = 15
DELAY   = 2      # 사이트 간 요청 딜레이 (초)

# 대회 공고 판별 키워드 (제목에 포함되면 대회 공고로 간주)
CONTEST_KEYWORDS = [
    "대회", "검도대회", "오픈", "선수권", "체육대회",
    "페스티벌", "대항", "기념", "배", "컵"
]

# 날짜 패턴 (제목 또는 본문에서 추출)
DATE_PATTERNS = [
    r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",   # 2026.05.17, 2026-05-17
    r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일",    # 2026년 5월 17일
    r"(\d{1,2})[.\-/](\d{1,2})\s*[~\-]\s*(\d{1,2})[.\-/](\d{1,2})",  # 5.17~5.18
]

# ── 유틸 함수 ──────────────────────────────────────

def make_id(name: str, date: str) -> str:
    """대회명 + 날짜로 고유 ID 생성"""
    raw = f"{name}_{date}"
    return hashlib.md5(raw.encode()).hexdigest()[:10]


def is_contest(title: str) -> bool:
    """제목이 대회 공고인지 판별"""
    return any(kw in title for kw in CONTEST_KEYWORDS)


def extract_date(text: str, base_year: int = None) -> tuple[str, str]:
    """
    텍스트에서 날짜 추출.
    반환: (start_date, end_date) 형식 "YYYY-MM-DD"
    못 찾으면 ("", "")
    """
    if base_year is None:
        base_year = datetime.now().year

    # YYYY.MM.DD 패턴
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        start = f"{y}-{mo}-{d}"
        # 종료일 탐색 (같은 줄에서 ~ 이후)
        end_m = re.search(
            r"[~\-]\s*(\d{4})?[.\-/]?(\d{1,2})[.\-/](\d{1,2})", text[m.end():]
        )
        if end_m:
            ey = end_m.group(1) or y
            emo = end_m.group(2).zfill(2)
            ed  = end_m.group(3).zfill(2)
            end = f"{ey}-{emo}-{ed}"
        else:
            end = start
        return start, end

    # YYYY년 M월 D일 패턴
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{y}-{mo}-{d}", f"{y}-{mo}-{d}"

    return "", ""


def fetch(url: str) -> BeautifulSoup | None:
    """URL 가져와서 BeautifulSoup 반환. 실패하면 None."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  ⚠️  fetch 실패: {url} → {e}")
        return None


# ── 사이트 유형별 파서 ─────────────────────────────

def parse_gnuboard(site: dict) -> list[dict]:
    """
    그누보드 계열 (kumdo.org, seoulkumdo, gnkumdo, kkumdo 등)
    게시판 목록 → 각 글 제목/링크/날짜 추출
    """
    results = []
    soup = fetch(site["url"])
    if not soup:
        return results

    # 그누보드 목록 행: <tr> 안에 제목 링크
    rows = soup.select("tr")
    for row in rows:
        a = row.select_one("td.td_subject a, td.subject a, .bo_tit a")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not is_contest(title):
            continue

        link = urljoin(site["url"], a.get("href", ""))

        # 날짜: 목록에서 먼저 찾기
        date_td = row.select_one("td.td_datetime, td.datetime, .td_num2")
        date_text = date_td.get_text(strip=True) if date_td else ""
        start, end = extract_date(date_text)

        # 날짜 못 찾으면 제목에서 시도
        if not start:
            start, end = extract_date(title)

        results.append({
            "id": make_id(title, start),
            "name": title,
            "date": start,
            "endDate": end,
            "location": "",
            "type": "",
            "open": "오픈" in title,
            "source": link,
            "source_site": site["id"],
            "note": "",
            "updated": datetime.now().strftime("%Y-%m-%d")
        })

    return results


def parse_dmboard(site: dict) -> list[dict]:
    """
    dmboard 계열 (nwkumdo, gpkumdo 등)
    """
    results = []
    soup = fetch(site["url"])
    if not soup:
        return results

    rows = soup.select("table tr, .list_wrap li")
    for row in rows:
        a = row.select_one("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not is_contest(title):
            continue

        link = urljoin(site["url"], a.get("href", ""))
        start, end = extract_date(title)

        results.append({
            "id": make_id(title, start),
            "name": title,
            "date": start,
            "endDate": end,
            "location": "",
            "type": "",
            "open": "오픈" in title,
            "source": link,
            "source_site": site["id"],
            "note": "",
            "updated": datetime.now().strftime("%Y-%m-%d")
        })

    return results


def parse_custom(site: dict) -> list[dict]:
    """
    커스텀 사이트 공통 파서 — 링크 제목 기반으로 최대한 추출
    """
    results = []
    soup = fetch(site["url"])
    if not soup:
        return results

    # 모든 링크 중 대회 키워드 포함된 것
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if len(title) < 5:
            continue
        if not is_contest(title):
            continue

        link = urljoin(site["url"], a.get("href", ""))
        start, end = extract_date(title)

        results.append({
            "id": make_id(title, start),
            "name": title,
            "date": start,
            "endDate": end,
            "location": "",
            "type": "",
            "open": "오픈" in title,
            "source": link,
            "source_site": site["id"],
            "note": "",
            "updated": datetime.now().strftime("%Y-%m-%d")
        })

    # 중복 제거 (같은 제목)
    seen = set()
    unique = []
    for r in results:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)
    return unique


# ── 유형별 파서 라우터 ─────────────────────────────

PARSERS = {
    "gnuboard": parse_gnuboard,
    "dmboard":  parse_dmboard,
    "custom":   parse_custom,
}


# ── 수동 입력 데이터 병합 ──────────────────────────

def load_manual(path: str = "manual_events.json") -> list[dict]:
    """
    운영자가 직접 입력한 대회 데이터 로드.
    파일 없으면 빈 리스트 반환.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"  ⚠️  manual_events.json 로드 실패: {e}")
        return []


# ── 메인 ──────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"By Techne 검도 크롤러 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    # sites.json 읽기
    with open("sites.json", encoding="utf-8") as f:
        sites = json.load(f)

    all_events = []

    for site in sites:
        if not site.get("active", True):
            print(f"⏭  건너뜀: {site['name']} (active=false)")
            continue

        print(f"🔍 크롤링: {site['name']}")
        parser = PARSERS.get(site["type"], parse_custom)

        try:
            events = parser(site)
            print(f"   → {len(events)}건 발견")
            all_events.extend(events)
        except Exception as e:
            print(f"   ⚠️  오류 발생: {e}")

        time.sleep(DELAY)

    # 수동 입력 데이터 병합
    manual = load_manual()
    if manual:
        print(f"\n📝 수동 입력 데이터: {len(manual)}건")
        all_events.extend(manual)

    # ID 기준 중복 제거 (수동 입력이 우선)
    seen_ids = set()
    deduped = []
    # 수동 입력을 먼저 처리해 우선순위 부여
    for ev in sorted(all_events, key=lambda x: x.get("source_site","") == "manual", reverse=True):
        if ev["id"] not in seen_ids:
            seen_ids.add(ev["id"])
            deduped.append(ev)

    # 날짜순 정렬
    deduped.sort(key=lambda x: x.get("date") or "9999")

    # events.json 저장
    output = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(deduped),
        "events": deduped
    }

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✅ 완료: 총 {len(deduped)}건 → events.json 저장")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
