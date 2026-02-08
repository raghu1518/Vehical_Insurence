from pathlib import Path

from bot.infrastructure.rag import FAQRetriever
from bot.infrastructure.search import search_garages, search_hospitals


def test_search_hospitals_translates_query_before_matching(monkeypatch):
    calls = []

    def fake_translate(query: str, source_lang: str | None = None) -> str:
        calls.append((query, source_lang))
        return "kphb hospital"

    monkeypatch.setattr("bot.infrastructure.search.translate_to_english", fake_translate)
    monkeypatch.setattr(
        "bot.infrastructure.search.load_hospitals",
        lambda: [
            {
                "name": "Preeti Urology Hospital",
                "city": "Hyderabad",
                "state": "Telangana",
                "pincode": "500072",
                "address": "Road No. 4, KPHB Colony",
                "phone": "04023152444",
                "raw": {},
            }
        ],
    )

    results = search_hospitals("कुकटपल्ली अस्पताल", limit=1)

    assert len(results) == 1
    assert results[0]["name"] == "Preeti Urology Hospital"
    assert calls == [("कुकटपल्ली अस्पताल", None)]


def test_search_garages_translates_query_before_matching(monkeypatch):
    calls = []

    def fake_translate(query: str, source_lang: str | None = None) -> str:
        calls.append((query, source_lang))
        return "kphb towing garage"

    monkeypatch.setattr("bot.infrastructure.search.translate_to_english", fake_translate)
    monkeypatch.setattr(
        "bot.infrastructure.search.load_garages",
        lambda: [
            {
                "name": "NEW RR MOTORS",
                "city": "Hyderabad",
                "state": "Telangana",
                "pincode": "500072",
                "address": "KPHB, Kukatpally",
                "phone": "9440053357",
                "raw": {},
            }
        ],
    )

    results = search_garages("कृपया नजदीकी गैराज ढूंढो", limit=1)

    assert len(results) == 1
    assert results[0]["name"] == "NEW RR MOTORS"
    assert calls == [("कृपया नजदीकी गैराज ढूंढो", None)]


def test_rag_query_translates_before_tokenizing(monkeypatch):
    calls = []

    def fake_translate(query: str, source_lang: str | None = None) -> str:
        calls.append((query, source_lang))
        return "claim payments processed verification"

    monkeypatch.setattr("bot.infrastructure.rag.translate_to_english", fake_translate)

    retriever = FAQRetriever(Path("."))
    retriever._loaded = True
    faq_text = "Claim payments are typically processed in 4 to 7 working days after verification."
    retriever.chunks = [
        {
            "text": faq_text,
            "source": "faq.pdf",
            "tokens": retriever._tokenize(faq_text),
        }
    ]

    results = retriever.query("मेरा क्लेम पेमेंट कब होगा", top_k=1)

    assert len(results) == 1
    assert "4 to 7" in results[0]["text"]
    assert calls == [("मेरा क्लेम पेमेंट कब होगा", None)]
