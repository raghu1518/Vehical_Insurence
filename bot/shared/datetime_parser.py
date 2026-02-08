from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re


_WS_RE = re.compile(r"\s+")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUM_DATE_RE = re.compile(r"\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})\b")
_NUM_DATE_COMPACT_RE = re.compile(r"\b(\d{2})(\d{2})(\d{4})\b")
_TIME_24H_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_TIME_AMPM_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b")
_TIME_HINDI_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(बजे|baje)\b")

_EN_NUM = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "half": 0.5,
}
_ROMAN_NUM = {
    "ek": 1,
    "do": 2,
    "teen": 3,
    "char": 4,
    "panch": 5,
    "chhe": 6,
    "saat": 7,
    "aath": 8,
    "nau": 9,
    "das": 10,
    "aadha": 0.5,
}
_HI_NUM = {
    "एक": 1,
    "दो": 2,
    "तीन": 3,
    "चार": 4,
    "पांच": 5,
    "छह": 6,
    "सात": 7,
    "आठ": 8,
    "नौ": 9,
    "दस": 10,
    "आधा": 0.5,
}

_MONTH_SYNONYMS: dict[int, list[str]] = {
    1: [
        "jan",
        "january",
        "जनवरी",
        "जानेवारी",
        "जनवरी",
        "जुनवरी",
        "ਜਨਵਰੀ",
        "જાન્યુઆરી",
        "ਜਨਵਰੀ",
        "জানুয়ারি",
        "জানুৱাৰী",
        "ଜାନୁଆରୀ",
        "ஜனவரி",
        "జనవరి",
        "ಜನವರಿ",
        "ജനുവരി",
        "جنوری",
        "जनवरी",
        "जनवरी",
    ],
    2: [
        "feb",
        "february",
        "फ़रवरी",
        "फरवरी",
        "फेब्रुवारी",
        "फेब्रुअरी",
        "फेब्रुअरी",
        "फेब्रुअरी",
        "फेब्रुअरी",
        "ਫਰਵਰੀ",
        "ਫ਼ਰਵਰੀ",
        "ફેબ્રુઆરી",
        "ফেব্রুয়ারি",
        "ফেব্ৰুৱাৰী",
        "ଫେବ୍ରୁଆରୀ",
        "ଫେବୃଆରୀ",
        "பிப்ரவரி",
        "ఫిబ్రవరి",
        "ಫೆಬ್ರವರಿ",
        "ഫെബ്രുവരി",
        "فیبروری",
        "فروری",
    ],
    3: [
        "mar",
        "march",
        "मार्च",
        "ਮਾਰਚ",
        "માર્ચ",
        "মার্চ",
        "মাৰ্চ",
        "ମାର୍ଚ୍ଚ",
        "மார்ச்",
        "మార్చి",
        "ಮಾರ್ಚ್",
        "മാർച്ച്",
        "مارچ",
    ],
    4: [
        "apr",
        "april",
        "अप्रैल",
        "एप्रिल",
        "अप्रिल",
        "अप्रिल",
        "ਅਪ੍ਰੈਲ",
        "ਅਪ੍ਰਿਲ",
        "એપ્રિલ",
        "এপ্রিল",
        "এপ্ৰিল",
        "ଏପ୍ରିଲ୍",
        "ஏப்ரல்",
        "ఏప్రిల్",
        "ಏಪ್ರಿಲ್",
        "ഏപ്രിൽ",
        "اپریل",
    ],
    5: [
        "may",
        "मई",
        "मे",
        "ਮਈ",
        "મે",
        "মে",
        "মে",
        "ମେ",
        "மே",
        "మే",
        "ಮೇ",
        "മേയ്",
        "മെയ്",
        "مئی",
    ],
    6: [
        "jun",
        "june",
        "जून",
        "जुन",
        "जून",
        "ਜੂਨ",
        "જૂન",
        "জুন",
        "জুন",
        "ଜୁନ୍",
        "ஜூன்",
        "జూన్",
        "ಜೂನ್",
        "ജൂൺ",
        "جون",
    ],
    7: [
        "jul",
        "july",
        "जुलाई",
        "जुलै",
        "जुलाई",
        "जुलाई",
        "ਜੁਲਾਈ",
        "જુલાઈ",
        "জুলাই",
        "জুলাই",
        "ଜୁଲାଇ",
        "ஜூலை",
        "జూలై",
        "ಜುಲೈ",
        "ജൂലൈ",
        "جولائی",
    ],
    8: [
        "aug",
        "august",
        "अगस्त",
        "आगस्ट",
        "ऑगस्ट",
        "अगस्ट",
        "ਅਗਸਤ",
        "ઓગસ્ટ",
        "ઑગસ્ટ",
        "আগস্ট",
        "অগস্ট",
        "আগষ্ট",
        "ଅଗଷ୍ଟ",
        "ஆகஸ்ட்",
        "ఆగస్టు",
        "ಆಗಸ್ಟ್",
        "ഓഗസ്റ്റ്",
        "اگست",
    ],
    9: [
        "sep",
        "sept",
        "september",
        "सितंबर",
        "सितम्बर",
        "सप्टेंबर",
        "સપ્ટેમ્બર",
        "ਸਤੰਬਰ",
        "ਸਿਤੰਬਰ",
        "সেপ্টেম্বর",
        "সেপ্টেম্বৰ",
        "ସେପ୍ଟେମ୍ବର",
        "செப்டம்பர்",
        "సెప్టెంబర్",
        "ಸೆಪ್ಟೆಂಬರ್",
        "സെപ്റ്റംബർ",
        "ستمبر",
        "ستمبر",
    ],
    10: [
        "oct",
        "october",
        "अक्टूबर",
        "अक्टोबर",
        "ऑक्टोबर",
        "ਅਕਤੂਬਰ",
        "અક્ટોબર",
        "ઑક્ટોબર",
        "অক্টোবর",
        "অক্টোবর",
        "ଅକ୍ଟୋବର",
        "அக்டோபர்",
        "అక్టోబర్",
        "ಅಕ್ಟೋಬರ್",
        "ഒക്ടോബർ",
        "اکتوبر",
    ],
    11: [
        "nov",
        "november",
        "नवंबर",
        "नवम्बर",
        "नोव्हेंबर",
        "ਨਵੰਬਰ",
        "નવેમ્બર",
        "নভেম্বর",
        "নৱেম্বৰ",
        "ନଭେମ୍ବର",
        "நவம்பர்",
        "నవంబర్",
        "ನವೆಂಬರ್",
        "നവംബർ",
        "نومبر",
    ],
    12: [
        "dec",
        "december",
        "दिसंबर",
        "दिसम्बर",
        "डिसेंबर",
        "ਦਸੰਬਰ",
        "ડિસેમ્બર",
        "ডিসেম্বর",
        "ডিচেম্বৰ",
        "ଡିସେମ୍ବର",
        "டிசம்பர்",
        "డిసెంబర్",
        "ಡಿಸೆಂಬರ್",
        "ഡിസംബർ",
        "دسمبر",
    ],
}

_MONTH_MAP: dict[str, int] = {}
for _month_num, _names in _MONTH_SYNONYMS.items():
    for _name in _names:
        _MONTH_MAP[_name.lower()] = _month_num

_MONTH_PATTERN = "|".join(
    sorted((re.escape(name) for name in _MONTH_MAP.keys()), key=len, reverse=True)
)
_MONTH_FIRST_RE = re.compile(
    rf"\b({_MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{2,4}}))?\b",
    re.IGNORECASE,
)
_DAY_FIRST_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\b\s+({_MONTH_PATTERN})\.?(?:,?\s+(\d{{2,4}}))?\b",
    re.IGNORECASE,
)
_AGO_EN_RE = re.compile(
    r"\b(?P<num>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|half)\s*"
    r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\s*(ago|before|earlier)\b"
)
_AGO_HI_RE = re.compile(
    r"\b(?P<num>\d+|एक|दो|तीन|चार|पांच|छह|सात|आठ|नौ|दस|आधा)\s*"
    r"(?P<unit>सेकंड|सकंड|मिनट|घंट|घण्ट|दिन|हफ्त|हफ़्त|सप्ताह)\s*(पहले|पहिले)\b"
)
_AGO_HI_ROMAN_RE = re.compile(
    r"\b(?P<num>\d+|ek|do|teen|char|panch|chhe|saat|aath|nau|das|aadha)\s*"
    r"(?P<unit>sec|second|seconds|min|minute|minutes|hour|hr|hours|din|day|days|hafta|hafto|week|weeks)\s*"
    r"(?P<suffix>pehle|pahle)\b"
)

_RELATIVE_DAYS = [
    (re.compile(r"\bday before yesterday\b"), -2),
    (re.compile(r"\bday before\b"), -2),
    (re.compile(r"\byesterday\b"), -1),
    (re.compile(r"\btoday\b"), 0),
    (re.compile(r"\btomorrow\b"), 1),
]
_RELATIVE_DAYS_HI = [
    (re.compile(r"\bपरसों\b"), -2),
    (re.compile(r"\bपर्सों\b"), -2),
    (re.compile(r"\bआज\b"), 0),
    (re.compile(r"\bकल\b"), -1),  # prefer past for incident context
]
_RELATIVE_DAYS_ROMAN = [
    (re.compile(r"\bparso?n?\b"), -2),
    (re.compile(r"\baaj\b"), 0),
    (re.compile(r"\bkal\b"), -1),
]

_TIME_WORDS = [
    ("early morning", time(6, 0)),
    ("late night", time(23, 0)),
    ("midnight", time(0, 0)),
    ("noon", time(12, 0)),
    ("morning", time(9, 0)),
    ("afternoon", time(15, 0)),
    ("evening", time(19, 0)),
    ("night", time(22, 0)),
]
_TIME_WORDS_HI = [
    ("सुबह जल्दी", time(6, 0)),
    ("देर रात", time(23, 0)),
    ("मध्यरात", time(0, 0)),
    ("अर्धरात्रि", time(0, 0)),
    ("दोपहर", time(14, 0)),
    ("शाम", time(19, 0)),
    ("रात", time(22, 0)),
    ("सुबह", time(9, 0)),
    ("सवेरे", time(8, 0)),
]
_TIME_WORDS_ROMAN = [
    ("subah jaldi", time(6, 0)),
    ("der raat", time(23, 0)),
    ("dopahar", time(14, 0)),
    ("shaam", time(19, 0)),
    ("raat", time(22, 0)),
    ("subah", time(9, 0)),
    ("savera", time(8, 0)),
]


@dataclass
class ParsedDateTime:
    value: datetime
    had_time: bool


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text.strip().lower())


def _normalize_month_token(token: str) -> str:
    cleaned = token.strip().lower()
    return cleaned.rstrip(".,")


def _to_number(raw: str) -> float | None:
    if raw.isdigit():
        return float(raw)
    if raw in _EN_NUM:
        return float(_EN_NUM[raw])
    if raw in _ROMAN_NUM:
        return float(_ROMAN_NUM[raw])
    if raw in _HI_NUM:
        return float(_HI_NUM[raw])
    return None


def _parse_relative_delta(text: str) -> timedelta | None:
    match = _AGO_EN_RE.search(text)
    if match:
        num = _to_number(match.group("num"))
        unit = match.group("unit")
        if num is None:
            return None
        seconds = _unit_seconds(unit)
        return timedelta(seconds=num * seconds)

    match = _AGO_HI_RE.search(text)
    if match:
        num = _to_number(match.group("num"))
        unit = match.group("unit")
        if num is None:
            return None
        seconds = _unit_seconds(unit)
        return timedelta(seconds=num * seconds)

    match = _AGO_HI_ROMAN_RE.search(text)
    if match:
        num = _to_number(match.group("num"))
        unit = match.group("unit")
        if num is None:
            return None
        seconds = _unit_seconds(unit)
        return timedelta(seconds=num * seconds)

    return None


def _unit_seconds(unit: str) -> int:
    unit = unit.lower()
    if unit.startswith(("sec", "सेक", "सक")):
        return 1
    if unit.startswith(("min", "मिनट")):
        return 60
    if unit.startswith(("hour", "hr", "घंट", "घण्ट")):
        return 3600
    if unit.startswith(("day", "दिन", "din")):
        return 86400
    if unit.startswith(("week", "हफ्त", "हफ़्त", "सप्ताह", "haft")):
        return 604800
    return 0


def _parse_year(raw: str | None, now: datetime) -> int:
    if not raw:
        return now.year
    year = int(raw)
    if year < 100:
        year += 2000
    return year


def _parse_explicit_date(text: str, now: datetime | None = None) -> date | None:
    now = now or datetime.now()
    match = _ISO_DATE_RE.search(text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    match = _NUM_DATE_RE.search(text)
    if match:
        part1 = int(match.group(1))
        part2 = int(match.group(2))
        year = int(match.group(3))
        if year < 100:
            year += 2000

        day = part1
        month = part2
        if part1 <= 12 and part2 > 12:
            month = part1
            day = part2
        elif part1 > 12 and part2 <= 12:
            day = part1
            month = part2

        try:
            return date(year, month, day)
        except ValueError:
            return None

    match = _NUM_DATE_COMPACT_RE.search(text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None

    # Parse day-first before month-first to avoid false positives like
    # "8 feb 2026" being interpreted as "feb 20 26".
    match = _DAY_FIRST_RE.search(text)
    if match:
        day = int(match.group(1))
        month_key = _normalize_month_token(match.group(2))
        month = _MONTH_MAP.get(month_key)
        year = _parse_year(match.group(3), now)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                return None

    match = _MONTH_FIRST_RE.search(text)
    if match:
        month_key = _normalize_month_token(match.group(1))
        month = _MONTH_MAP.get(month_key)
        day = int(match.group(2))
        year = _parse_year(match.group(3), now)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                return None

    return None


def _parse_relative_day(text: str) -> int | None:
    for pattern, offset in _RELATIVE_DAYS:
        if pattern.search(text):
            return offset
    for pattern, offset in _RELATIVE_DAYS_HI:
        if pattern.search(text):
            return offset
    for pattern, offset in _RELATIVE_DAYS_ROMAN:
        if pattern.search(text):
            return offset
    if "last night" in text or "last evening" in text:
        return -1
    return None


def _parse_time(text: str) -> time | None:
    match = _TIME_AMPM_RE.search(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        ampm = match.group(3)
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        return time(hour, minute)

    match = _TIME_24H_RE.search(text)
    if match:
        return time(int(match.group(1)), int(match.group(2)))

    match = _TIME_HINDI_RE.search(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if re.search(r"(रात|शाम|दोपहर|raat|shaam|dopahar)", text) and hour < 12:
            hour += 12
        if re.search(r"(सुबह|सवेरे|subah|savera)", text) and hour == 12:
            hour = 0
        return time(hour, minute)

    for phrase, default_time in _TIME_WORDS:
        if phrase in text:
            return default_time

    for phrase, default_time in _TIME_WORDS_HI:
        if phrase in text:
            return default_time
    for phrase, default_time in _TIME_WORDS_ROMAN:
        if phrase in text:
            return default_time

    return None


def parse_natural_datetime(text: str, now: datetime | None = None) -> ParsedDateTime | None:
    if not text:
        return None
    normalized = _normalize(text)
    if not normalized:
        return None

    now = now or datetime.now()

    delta = _parse_relative_delta(normalized)
    parsed_time = _parse_time(normalized)
    if delta is not None:
        value = now - delta
        if parsed_time:
            value = value.replace(hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0)
        return ParsedDateTime(value=value, had_time=parsed_time is not None)

    explicit_date = _parse_explicit_date(normalized, now=now)
    rel_day = _parse_relative_day(normalized)

    if explicit_date is None and rel_day is None and parsed_time is None:
        return None

    base_date = explicit_date
    if base_date is None and rel_day is not None:
        base_date = (now + timedelta(days=rel_day)).date()
    if base_date is None:
        base_date = now.date()

    value = datetime.combine(base_date, parsed_time or time(0, 0))
    return ParsedDateTime(value=value, had_time=parsed_time is not None)


def parse_incident_date(text: str, now: datetime | None = None) -> str | None:
    parsed = parse_natural_datetime(text, now=now)
    if not parsed:
        return None
    return parsed.value.date().isoformat()
