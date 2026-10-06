import json
import re
import requests

# Quran.com API v4.
API = "https://api.quran.com/api/v4"
TRANSLATIONS = {
    20: "quran_en_saheeh.json",         # Saheeh International
    203: "quran_en_hilali_khan.json",   # Al-Hilali & Khan (the Noble Quran, printed by King Fahd Complex)
}


def clean(text):
    # remove footnote markers like <sup foot_note=123>1</sup>
    return re.sub(r"<sup.*?</sup>", "", text).strip()


chapters = requests.get(f"{API}/chapters", params={"language": "ar"}).json()["chapters"]

for translation_id, output_file in TRANSLATIONS.items():
    quran = {}
    for chapter in chapters:
        number = chapter["id"]
        response = requests.get(
            f"{API}/verses/by_chapter/{number}",
            params={"translations": translation_id, "per_page": 300},
        ).json()

        quran[number] = {
            "name_arabic": chapter["name_arabic"],
            "name_english": chapter["name_simple"],
            "ayahs": {
                verse["verse_number"]: clean(verse["translations"][0]["text"])
                for verse in response["verses"]
            },
        }
        print(f"{translation_id} | {number} {chapter['name_arabic']}: {len(quran[number]['ayahs'])} ayahs")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(quran, f, ensure_ascii=False, indent=2)

    print(f"saved to {output_file}")
