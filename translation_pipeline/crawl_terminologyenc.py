import html
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

# The Encyclopedia of Translated Islamic Terms (terminologyenc.com), made by the association that the competition
# names as its reference. Every term has the arabic word, its translation in about 17 languages, a meaning and a
# brief explanation. This script reads the public pages (robots.txt allows /browse/) slowly, one page a second,
# and saves them in data/terminology/terminologyenc.json with the page of each term, so that every term we use
# can be traced back to its source.
#
#   py translation_pipeline/crawl_terminologyenc.py          all the terms
#   py translation_pipeline/crawl_terminologyenc.py 20       only 20 terms, saved in terminologyenc.sample.json
#
# It can be stopped and started again: the terms already saved are not read twice.

SITE = "https://terminologyenc.com"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "terminology"
PAUSE = 1.0  # seconds between two pages

HEADERS = {"User-Agent": "Mozilla/5.0 (Alsun, a translation project for the AI and Islamic content challenge)"}
LETTERS = "أبتثجحخدذرزسشصضطظعغفقكلمنهـوي"
CATEGORIES = [1, 2, 3, 4, 5, 6, 7, 755, 758, 760, 761, 762]  # the 7 groups of terms and the dictionaries

# what each field of a term page is: id on the page => name in the saved file
FIELDS = {
    "title": "term",
    "ling_def": "linguistic_meaning",
    "brief_ling_def": "linguistic_explanation",
    "idio_def": "meaning",
    "brief_expl": "explanation",
    "root": "root",
    "value": "value",
}

session = requests.Session()
session.headers.update(HEADERS)


class SiteNotAnswering(Exception):
    pass


def get(url):
    # five tries; a refusal (403 / 429) stops everything, we do not push on a site that says stop. A connection
    # that the site closes is waited for, longer each time (the site is not ours to hurry).
    for attempt in range(5):
        try:
            response = session.get(url, timeout=30)
        except requests.RequestException:
            time.sleep(15 * (attempt + 1))
            continue
        if response.status_code in (403, 429):
            sys.exit(f"the site refused ({response.status_code}) at {url}, stopping")
        if response.status_code == 200:
            return response.text
        if response.status_code == 404:
            return None  # a link to a page that is not there
        time.sleep(5 * (attempt + 1))
    raise SiteNotAnswering(url)


def text_of(fragment):
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    lines = [" ".join(line.split()) for line in html.unescape(fragment).splitlines()]
    return "\n".join(line for line in lines if line)


def term_ids(url):
    page = get(url)
    time.sleep(PAUSE)
    return set(map(int, re.findall(r"/browse/term/(\d+)", page or "")))


def category_name(number):
    page = get(f"{SITE}/ar/browse/category/{number}")
    time.sleep(PAUSE)
    found = re.search(r"<title>التصنيف:\s*(.*?)\s*-", page or "")
    return found.group(1) if found else str(number)


def collect_ids():
    # every term is in the list of its first letter; the groups tell us which group a term belongs to
    ids = {}
    for number in CATEGORIES:
        name = category_name(number)
        for term_id in term_ids(f"{SITE}/ar/browse/category/{number}"):
            ids.setdefault(term_id, []).append(name)
        print(f"group {number} {name}: {len(ids)} terms so far")
    for letter in LETTERS:
        for term_id in term_ids(f"{SITE}/ar/browse/alpha/{letter}"):
            ids.setdefault(term_id, [])
        print(f"letter {letter}: {len(ids)} terms so far")
    return ids


def read_term(term_id, groups):
    url = f"{SITE}/en/browse/term/{term_id}"
    page = get(url)
    if page is None:
        return None
    term = {"id": term_id, "url": url, "groups": groups}
    for field, name in FIELDS.items():
        values = {}
        arabic = re.search(rf'<span id="t_{field}"[^>]*>(.*?)</span>', page, re.S)
        if arabic and text_of(arabic.group(1)):
            values["ar"] = text_of(arabic.group(1))
        # the other languages: <b>Language</b></span> text <button ... data-det="id/field/lang">
        for body, found_field, language in re.findall(
            r'<span class="label[^>]*><b>[^<]*</b></span>(.*?)<button[^>]*data-det="\d+/(\w+)/(\w+)"', page, re.S
        ):
            if found_field == field and text_of(body):
                values[language] = text_of(body)
        if values:
            term[name] = values
    return term if "term" in term else None


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / ("terminologyenc.sample.json" if limit else "terminologyenc.json")

    saved = {}
    if output.exists():
        saved = {term["id"]: term for term in json.loads(output.read_text(encoding="utf-8"))["terms"]}

    ids = collect_ids()
    todo = sorted(term_id for term_id in ids if term_id not in saved)
    if limit:
        todo = todo[:limit]
    print(f"{len(ids)} terms on the site, {len(saved)} already saved, {len(todo)} to read")

    def save():
        data = {
            "source": "terminologyenc.com - Encyclopedia of Translated Islamic Terms",
            "read_on": date.today().isoformat(),
            "terms": [saved[term_id] for term_id in sorted(saved)],
        }
        output.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")

    failed = []
    in_a_row = 0
    for count, term_id in enumerate(todo, start=1):
        try:
            term = read_term(term_id, ids[term_id])
        except SiteNotAnswering:
            in_a_row += 1
            failed.append(term_id)
            if in_a_row >= 3:  # the site is not answering: what we have is saved, and we can start again later
                save()
                sys.exit(f"three pages in a row were not read, stopping with {len(saved)} terms saved; start again later")
            continue
        time.sleep(PAUSE)
        in_a_row = 0
        if term is None:
            failed.append(term_id)  # a page that is not there
        else:
            saved[term_id] = term
        if count % 100 == 0:
            save()
            print(f"{count}/{len(todo)} read")
    save()
    print(f"saved {len(saved)} terms to {output}; not read: {failed}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
