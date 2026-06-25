# -*- coding: utf-8 -*-
"""
Agentic (araç kullanan) branşı: çok-turlu tool-calling döngüsü + çıkarım görevleri.

Model, OpenAI tool-calling formatıyla araç çağırır; biz aracı izole verinin üstünde
çalıştırıp sonucu geri besleriz; model devam eder. Görevler, modelin VERİYİ KENDİSİ
toplayıp DOĞRU ÇIKARIMI yapmasını gerektirir — yalnızca doğru mantık doğru sonuca ulaşır.
Tool-calling yapamayan / yanlış çıkaran model 0 alır; döngü asla takılmaz (tur limiti).
"""

import json
import time

import requests


# ===========================================================================
#  GÖREV VERİLERİ + ARAÇLAR
# ===========================================================================

# --- Görev 1: Tutarsız kayıt (bakiye = onceki_bakiye + alacak - borc; tam 1 kayıt bozuk) ---
_KAYITLAR = {
    1: {"onceki_bakiye": 1000, "alacak": 300, "borc": 100, "bakiye": 1200},
    2: {"onceki_bakiye": 1200, "alacak": 0,   "borc": 500, "bakiye": 700},
    3: {"onceki_bakiye": 700,  "alacak": 800, "borc": 0,   "bakiye": 1500},
    4: {"onceki_bakiye": 1500, "alacak": 200, "borc": 200, "bakiye": 1500},
    5: {"onceki_bakiye": 1500, "alacak": 0,   "borc": 900, "bakiye": 600},
    6: {"onceki_bakiye": 600,  "alacak": 1000, "borc": 300, "bakiye": 1350},  # HATA: 1300 olmalı
    7: {"onceki_bakiye": 1300, "alacak": 400, "borc": 100, "bakiye": 1600},
    8: {"onceki_bakiye": 1600, "alacak": 0,   "borc": 600, "bakiye": 1000},
}


def _kayit_listele():
    return sorted(_KAYITLAR.keys())


def _kayit_oku(id):
    return _KAYITLAR.get(int(id), {"hata": "böyle bir kayıt yok"})


# --- Görev 2: Kısıt kesişimi (5 ipucu -> tek sayı = 462) ---
_IPUCLARI = {
    1: "Aradığın sayı 3 basamaklıdır (100-999).",
    2: "Sayı 7'ye tam bölünür.",
    3: "Rakamlarının toplamı 12'dir.",
    4: "Yüzler basamağındaki rakam, birler basamağındaki rakamdan tam olarak 2 fazladır.",
    5: "Onlar (ortadaki) basamağındaki rakam, yüzler ve birler basamağındaki rakamların toplamına eşittir.",
}


def _ipucu_oku(n):
    return _IPUCLARI.get(int(n), "böyle bir ipucu yok (1-5 arası dene)")


# --- Görev 3: Çok kaynaklı çıkarım (en yüksek satış -> yöneticisinin adı = Veli) ---
_CALISANLAR = {
    1: {"ad": "Ali", "departman": "Yonetim", "yonetici_id": None},
    2: {"ad": "Veli", "departman": "Satis", "yonetici_id": 1},
    3: {"ad": "Ayse", "departman": "Pazarlama", "yonetici_id": 1},
    4: {"ad": "Mehmet", "departman": "Satis", "yonetici_id": 2},
    5: {"ad": "Zeynep", "departman": "Satis", "yonetici_id": 2},
    6: {"ad": "Can", "departman": "Pazarlama", "yonetici_id": 3},
}
_SATIS = {1: 0, 2: 5000, 3: 3000, 4: 9000, 5: 7000, 6: 8000}


def _calisan_listele():
    return sorted(_CALISANLAR.keys())


def _calisan_oku(id):
    return _CALISANLAR.get(int(id), {"hata": "yok"})


def _satis_getir(calisan_id):
    return {"calisan_id": int(calisan_id), "toplam_satis": _SATIS.get(int(calisan_id), 0)}


def _tool(name, desc, props, required=()):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": list(required)}}}


AGENTIC_TASKS = [
    {"key": "agentic_1", "seviye": 1, "baslik": "Agentic S1 (tutarsız kayıt)",
     "grader_type": "math", "expected": 6.0,
     "cozum": "Her kayıtta bakiye = onceki_bakiye + alacak − borç. id=6: 600+1000−300=1300 olmalı ama 1350 yazıyor → bozuk kayıt 6.",
     "user": "Bir muhasebe defterinde 8 kayıt var. GEÇERLİ her kayıtta şu kural sağlanır: "
             "bakiye = onceki_bakiye + alacak − borç. Tam olarak BİR kayıt bu kuralı bozuyor. "
             "Önce kayit_listele ile id'leri al, sonra her kaydı kayit_oku ile BİR KEZ oku ve kuralı "
             "kontrol et. Kuralı bozan kaydı bulur bulmaz DUR ve EN SON satırda tam olarak `#### <id>` "
             "biçiminde ver. Aynı kaydı tekrar tekrar okuma.",
     "tools": [_tool("kayit_listele", "Tüm kayıt id'lerini döndürür.", {}),
               _tool("kayit_oku", "Bir kaydın alanlarını döndürür: onceki_bakiye, alacak, borc, bakiye.",
                     {"id": {"type": "integer", "description": "okunacak kaydın id'si"}}, ["id"])],
     "impls": {"kayit_listele": _kayit_listele, "kayit_oku": _kayit_oku}},

    {"key": "agentic_2", "seviye": 2, "baslik": "Agentic S2 (kısıt kesişimi)",
     "grader_type": "math", "expected": 462.0,
     "cozum": "h=b+2, o=h+b → toplam 4b+4=12 → b=2,h=4,o=6 → 462; 462=7·66 (7'ye bölünür). Tek çözüm 462.",
     "user": "Gizli bir sayı arıyorsun. 1'den 5'e kadar numaralı 5 ipucu var; her biri bir kısıt veriyor. "
             "ipucu_oku aracıyla TÜM ipuçlarını oku, hepsini aynı anda sağlayan TEK sayıyı mantıkla çıkar. "
             "Cevabını EN SON satırda tam olarak `#### <sayı>` biçiminde ver.",
     "tools": [_tool("ipucu_oku", "n numaralı ipucunu (metin) döndürür (n: 1-5).",
                     {"n": {"type": "integer", "description": "ipucu numarası 1-5"}}, ["n"])],
     "impls": {"ipucu_oku": _ipucu_oku}},

    {"key": "agentic_3", "seviye": 3, "baslik": "Agentic S3 (çok kaynaklı çıkarım)",
     "grader_type": "metin", "expected": "Veli",
     "cozum": "Satışlar: Mehmet(id4)=9000 en yüksek. Mehmet'in yonetici_id'si 2 → çalışan 2 = Veli.",
     "user": "Bir şirkette çalışanlar ve her birinin toplam satışı var. Araçları kullanarak önce EN YÜKSEK "
             "toplam satışı yapan çalışanı bul, sonra o çalışanın YÖNETİCİSİNİN adını bul. "
             "Cevabını (yöneticinin adı) EN SON satırda tam olarak `#### <ad>` biçiminde ver.",
     "tools": [_tool("calisan_listele", "Tüm çalışan id'lerini döndürür.", {}),
               _tool("calisan_oku", "Bir çalışanın bilgisini döndürür: ad, departman, yonetici_id.",
                     {"id": {"type": "integer"}}, ["id"]),
               _tool("satis_getir", "Bir çalışanın toplam satışını döndürür.",
                     {"calisan_id": {"type": "integer"}}, ["calisan_id"])],
     "impls": {"calisan_listele": _calisan_listele, "calisan_oku": _calisan_oku,
               "satis_getir": _satis_getir}},
]


# ===========================================================================
#  ÇOK-TURLU ARAÇ DÖNGÜSÜ
# ===========================================================================

def agentic_loop(base_url, model_id, task, temperature, max_tokens,
                 no_think=False, max_turns=25, timeout=300):
    """Modeli araçlarla çok-turlu çalıştırır. Dayanıklı: hata/araçsızlık/limit -> durmaz.
    Döndürür: text (nihai cevap), turns, tool_calls, read_before_answer, total, completion_tokens, ttft."""
    url = base_url + "/v1/chat/completions"
    impls = task["impls"]
    messages = [{"role": "user", "content": task["user"]}]
    t0 = time.perf_counter()
    ttft = None
    tool_calls_count = 0
    comp_tokens = 0
    final_text = ""
    transcript = []
    turn = 0
    for turn in range(1, max_turns + 1):
        payload = {"model": model_id, "messages": messages, "tools": task["tools"],
                   "temperature": temperature, "max_tokens": max_tokens}
        if no_think:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            obj = r.json()
        except Exception as e:
            final_text = f"[İSTEK HATASI: {e}]"
            break
        if ttft is None:
            ttft = time.perf_counter() - t0
        usage = obj.get("usage") or {}
        comp_tokens += usage.get("completion_tokens", 0) or 0
        msg = obj["choices"][0]["message"]
        tcs = msg.get("tool_calls")
        if tcs:
            tool_calls_count += len(tcs)
            messages.append(msg)
            for tc in tcs:
                fn = (tc.get("function") or {}).get("name", "")
                try:
                    args = json.loads((tc.get("function") or {}).get("arguments") or "{}")
                except Exception:
                    args = {}
                impl = impls.get(fn)
                if impl is None:
                    result = f"HATA: bilinmeyen araç '{fn}'"
                else:
                    try:
                        result = impl(**args)
                    except Exception as e:
                        result = f"HATA: {e}"
                transcript.append({"arac": fn, "arg": args, "sonuc": result})
                content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": tc.get("id", str(turn)),
                                 "name": fn, "content": content})
            continue
        # araç çağrısı yok -> nihai cevap
        final_text = msg.get("content") or ""
        break
    else:
        final_text = final_text or "[TUR LİMİTİ — model nihai cevaba ulaşamadı]"
    total = time.perf_counter() - t0
    if comp_tokens <= 0:
        comp_tokens = max(1, round(len(final_text) / 4))
    gen = max(1e-6, total - (ttft or 0))
    return {"text": final_text, "turns": turn, "tool_calls": tool_calls_count,
            "read_before_answer": tool_calls_count > 0, "transcript": transcript,
            "total": total, "ttft": ttft if ttft is not None else total,
            "completion_tokens": comp_tokens, "tokens_per_sec": comp_tokens / gen}
