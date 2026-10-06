import json
import re
import zipfile
from pathlib import Path

# Converts the translations downloaded from QUL (https://qul.tarteel.ai, "simple.json") to the format the
# pipeline reads (the same as download_quran_translation.py makes from the Quran.com API):
#   {"1": {"name_arabic": ..., "name_english": ..., "ayahs": {"1": "text", ...}}, ...}
# download_quran_translation.py stays as it is, in case we need the Quran.com source again.

DATA = Path(__file__).resolve().parent.parent / "data"
QUL_FOLDER = DATA / "qul"
# the surah names and the number of ayahs of every surah are taken from the English file we already trust
REFERENCE_FILE = DATA / "quran_en_saheeh.json"

# zip downloaded from QUL -> file for the pipeline
TRANSLATIONS = {
    "fr_hamidullah.zip": "quran_fr_hamidullah.json",   # Hamidullah, revised by the King Fahd Complex (2000)
    "id_kemenag.zip": "quran_id_kemenag.json",         # Indonesian Ministry of Religious Affairs
    "tr_diyanet.zip": "quran_tr_diyanet.json",         # Diyanet (Presidency of Religious Affairs)
    "de_bubenheim.zip": "quran_de_bubenheim.json",     # Bubenheim and Elyas
    "es_garcia.zip": "quran_es_garcia.json",           # Isa Garcia
}


def read_simple_json(zip_path):
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".json")]
        assert len(names) == 1, f"{zip_path}: expected one json file, found {names}"
        return json.loads(archive.read(names[0]).decode("utf-8"))


def find_problems(quran, reference):
    # everything that makes a file not safe to use; an empty list means the file passed
    problems = []
    if set(quran) != set(reference):
        problems.append("the surahs are not the 114 of the reference")
    for number, surah in reference.items():
        ayahs = quran.get(number, {}).get("ayahs", {})
        if set(ayahs) != set(surah["ayahs"]):
            problems.append(f"surah {number}: ayahs {len(ayahs)}, expected {len(surah['ayahs'])}")
        for ayah_number, text in ayahs.items():
            if not text.strip():
                problems.append(f"{number}:{ayah_number} is empty")
            elif re.search(r"<[^>]+>", text):
                problems.append(f"{number}:{ayah_number} has an html tag")
            elif re.search(r"\[\d+\]|\(\d+\)", text):
                problems.append(f"{number}:{ayah_number} has a footnote marker")
    return problems


def convert(zip_name, output_name, reference):
    simple = read_simple_json(QUL_FOLDER / zip_name)
    quran = {}
    for number, surah in reference.items():
        quran[number] = {
            "name_arabic": surah["name_arabic"],
            "name_english": surah["name_english"],
            "ayahs": {},
        }
    for key, value in simple.items():
        surah_number, ayah_number = key.split(":")
        quran[surah_number]["ayahs"][ayah_number] = value["t"].strip()

    # the ayahs in the order of the mushaf
    for number, surah in quran.items():
        surah["ayahs"] = {n: surah["ayahs"][n] for n in sorted(surah["ayahs"], key=int) if n in surah["ayahs"]}

    problems = find_problems(quran, reference)
    total = sum(len(surah["ayahs"]) for surah in quran.values())
    if problems:
        print(f"{zip_name}: NOT saved, {len(problems)} problems, for example: {problems[:5]}")
        return
    with open(DATA / output_name, "w", encoding="utf-8") as f:
        json.dump(quran, f, ensure_ascii=False, indent=2)
    print(f"{zip_name}: {total} ayahs, saved to {output_name}")


if __name__ == "__main__":
    reference = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    for zip_name, output_name in TRANSLATIONS.items():
        convert(zip_name, output_name, reference)
