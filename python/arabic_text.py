import re


def normalize_arabic(name):
    # make arabic text comparable: no tashkeel, one form of alef / taa marbuta / yaa
    name = re.sub(r"[ً-ٰـ]", "", name)
    name = re.sub(r"[أإآٱ]", "ا", name)
    return name.replace("ة", "ه").replace("ى", "ي")
