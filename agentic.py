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

LANG = "tr"   # "tr" / "en" — llm_perf_test.use_language() tarafından ayarlanır


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


_IPUCLARI_EN = {
    1: "The number you seek has 3 digits (100-999).",
    2: "The number is exactly divisible by 7.",
    3: "The sum of its digits is 12.",
    4: "The hundreds digit is exactly 2 more than the units digit.",
    5: "The tens (middle) digit equals the sum of the hundreds and units digits.",
}


def _ipucu_oku(n):
    d = _IPUCLARI_EN if LANG == "en" else _IPUCLARI
    return d.get(int(n), "no such clue (try 1-5)" if LANG == "en" else "böyle bir ipucu yok (1-5 arası dene)")


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


# --- Görev 4: Kara kutu (gizli f(x), yalnız 1-6 sorgulanabilir; f(10)=191 çıkarılmalı) ---
def _kara_kutu(x):
    x = int(x)
    if 1 <= x <= 6:
        return {"x": x, "sonuc": 2 * x * x - x + 1}
    return {"hata": "kara_kutu yalnızca 1 ≤ x ≤ 6 için çalışır; başka değer sorgulanamaz"}


# --- Görev 5: Mantık bulmacası (4 kişi × şehir × meslek; avukatın şehri = Bursa) ---
_IPUC_LOGIC = {
    1: "Ali İstanbul'da yaşıyor.",
    2: "Doktor olan kişi İstanbul'da yaşıyor.",
    3: "Veli mühendistir.",
    4: "Öğretmen olan kişi İzmir'de yaşıyor.",
    5: "Can ne İzmir'de ne de Ankara'da yaşıyor.",
}


_IPUC_LOGIC_EN = {
    1: "Ali lives in Istanbul.",
    2: "The doctor lives in Istanbul.",
    3: "Veli is an engineer.",
    4: "The teacher lives in Izmir.",
    5: "Can lives neither in Izmir nor in Ankara.",
}


def _ipucu_oku_logic(n):
    d = _IPUC_LOGIC_EN if LANG == "en" else _IPUC_LOGIC
    return d.get(int(n), "no such clue (try 1-5)" if LANG == "en" else "böyle bir ipucu yok (1-5 arası dene)")


# --- Görev 6: Graf en kısa yol (A->F en düşük maliyet = 13) ---
_GRAF = {
    "A": {"B": 4, "C": 2},
    "B": {"A": 4, "C": 1, "D": 5},
    "C": {"A": 2, "B": 1, "D": 8, "E": 10},
    "D": {"B": 5, "C": 8, "E": 2, "F": 6},
    "E": {"C": 10, "D": 2, "F": 3},
    "F": {"D": 6, "E": 3},
}


def _komsular(dugum):
    d = str(dugum).strip().upper()
    return _GRAF.get(d, {"hata": "böyle bir düğüm yok (A-F arası dene)"})


# --- Görev 7: Etkileşimli ikili arama (1-1000 gizli sayı = 737) ---
_GIZLI_SAYI = 737


def _tahmin_et(n):
    n = int(n)
    if n == _GIZLI_SAYI:
        return {"sonuc": "doğru" if LANG != "en" else "correct"}
    buyuk = n < _GIZLI_SAYI  # aranan sayı tahminden büyük mü
    if LANG == "en":
        return {"sonuc": "higher" if buyuk else "lower"}
    return {"sonuc": "daha büyük" if buyuk else "daha küçük"}


# --- Görev 8: Daha büyük ağırlıklı graf (A-H), en kısa yol A->H = 14 ---
_GRAF8 = {
    "A": {"B": 5, "C": 3, "D": 7},
    "B": {"A": 5, "C": 1, "E": 6},
    "C": {"A": 3, "B": 1, "D": 2, "E": 8, "F": 7},
    "D": {"A": 7, "C": 2, "F": 4},
    "E": {"B": 6, "C": 8, "F": 1, "G": 5},
    "F": {"C": 7, "D": 4, "E": 1, "G": 2, "H": 9},
    "G": {"E": 5, "F": 2, "H": 3},
    "H": {"F": 9, "G": 3},
}


def _komsular8(dugum):
    d = str(dugum).strip().upper()
    return _GRAF8.get(d, {"hata": "böyle bir düğüm yok (A-H arası dene)"})


# --- Görev 9: Döviz çevirme zinciri (kurları araçtan al; 100 USD+50 EUR+20 GBP = 5750 TRY) ---
_KURLAR = {"USD": 32, "EUR": 35, "GBP": 40, "JPY": 0.22, "CHF": 36}


def _kur_getir(para):
    p = str(para).strip().upper()
    if p in _KURLAR:
        return {"para": p, "kur_try": _KURLAR[p]}
    return {"hata": "bilinmeyen para birimi (USD, EUR, GBP, JPY, CHF dene)"}


# --- Görev 10: Kara kutu 2 (kübik f(x)=x³−2x+3, yalnız 1-6; f(9)=714 çıkarılmalı) ---
def _kara_kutu2(x):
    x = int(x)
    if 1 <= x <= 6:
        return {"x": x, "sonuc": x**3 - 2 * x + 3}
    return {"hata": "kara_kutu2 yalnızca 1 ≤ x ≤ 6 için çalışır; başka değer sorgulanamaz"}


# --- Görev 11: Mantık bulmacası 2 (5 kişi × içecek; KOLA içen = Ali) ---
_IPUC_ICECEK = {
    1: "Ali çay içmiyor.",
    2: "Veli kahve içiyor.",
    3: "Ayşe su veya ayran içiyor.",
    4: "Can kola içmiyor.",
    5: "Deniz ayran içiyor.",
    6: "Ali su içmiyor.",
}
_IPUC_ICECEK_EN = {
    1: "Ali does not drink tea (çay).",
    2: "Veli drinks coffee (kahve).",
    3: "Ayşe drinks water (su) or ayran.",
    4: "Can does not drink cola (kola).",
    5: "Deniz drinks ayran.",
    6: "Ali does not drink water (su).",
}


def _ipucu_oku_icecek(n):
    d = _IPUC_ICECEK_EN if LANG == "en" else _IPUC_ICECEK
    return d.get(int(n), "no such clue (try 1-6)" if LANG == "en" else "böyle bir ipucu yok (1-6 arası dene)")


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

    {"key": "agentic_4", "seviye": 4, "baslik": "Agentic S4 (kara kutu — tümevarım)",
     "grader_type": "math", "expected": 191.0,
     "cozum": "kara_kutu değerleri: 1→2,2→7,3→16,4→29,5→46,6→67. İkinci farklar sabit (4) → f(x)=2x²−x+1. "
              "f(10)=200−10+1=191.",
     "user": "kara_kutu(x) aracı gizli bir f(x) kuralını hesaplar AMA yalnızca 1 ≤ x ≤ 6 için çalışır "
             "(başka değer hata verir). Birkaç değeri sorgulayarak f(x) kuralını ÇIKAR, sonra f(10) "
             "değerini KENDİN hesapla (10'u kara_kutu'ya soramazsın). Sonucu EN SON satırda tam olarak "
             "`#### <sayı>` biçiminde ver.",
     "tools": [_tool("kara_kutu", "Gizli f(x) fonksiyonunu hesaplar; yalnızca 1 ≤ x ≤ 6 için geçerli.",
                     {"x": {"type": "integer", "description": "sorgulanacak değer (1-6)"}}, ["x"])],
     "impls": {"kara_kutu": _kara_kutu}},

    {"key": "agentic_5", "seviye": 5, "baslik": "Agentic S5 (mantık bulmacası — tümdengelim)",
     "grader_type": "metin", "expected": "Bursa",
     "cozum": "Ali=İstanbul=Doktor; Öğretmen=İzmir; Can∉{İzmir,Ankara}→Can=Bursa; Veli=Mühendis=Ankara; "
              "Ayşe=İzmir=Öğretmen; geriye Can=Avukat kalır → Avukat Bursa'da.",
     "user": "4 kişi var: Ali, Veli, Ayşe, Can. Her birinin BİR şehri (İstanbul, Ankara, İzmir, Bursa) ve "
             "BİR mesleği (Doktor, Mühendis, Öğretmen, Avukat) var; her şehir ve her meslek tam olarak bir "
             "kişiye aittir. ipucu_oku(n) (n=1..5) ile TÜM ipuçlarını oku ve eşleştirmeyi mantıkla çöz. "
             "Sonra şunu yanıtla: AVUKAT olan kişi hangi ŞEHİRDE yaşıyor? Cevabı (şehir adı) EN SON satırda "
             "`#### <şehir>` biçiminde ver.",
     "tools": [_tool("ipucu_oku", "n numaralı ipucunu (metin) döndürür (n: 1-5).",
                     {"n": {"type": "integer"}}, ["n"])],
     "impls": {"ipucu_oku": _ipucu_oku_logic}},

    {"key": "agentic_6", "seviye": 6, "baslik": "Agentic S6 (graf en kısa yol — arama)",
     "grader_type": "math", "expected": 13.0,
     "cozum": "Dijkstra: A→C(2)→B(1)→D(5)→E(2)→F(3) = 13. (A-C-B-D-F=14, A-C-D-E-F=15'ten düşük.)",
     "user": "Bir yol ağında A'dan F'ye düğümler var. komsular(dugum) aracı, verilen düğümün komşularını "
             "ve her kenarın maliyetini döndürür (kenarlar çift yönlüdür). Grafı keşfederek A'dan F'ye "
             "EN DÜŞÜK toplam maliyetli yolu bul ve o yolun TOPLAM MALİYETİNİ EN SON satırda "
             "`#### <sayı>` biçiminde ver.",
     "tools": [_tool("komsular", "Bir düğümün komşularını {komsu: maliyet} olarak döndürür.",
                     {"dugum": {"type": "string", "description": "düğüm adı, örn. 'A'"}}, ["dugum"])],
     "impls": {"komsular": _komsular}},

    {"key": "agentic_7", "seviye": 7, "baslik": "Agentic S7 (ikili arama — etkileşimli)",
     "grader_type": "math", "expected": 737.0,
     "cozum": "1-1000 aralığında ikili arama: her adımda ortayı tahmin et, 'daha büyük/küçük' yanıtına göre "
              "aralığı yarıla. ~10 tahminde gizli sayı 737 bulunur.",
     "user": "1 ile 1000 (dahil) arasında gizli bir tam sayı var. tahmin_et(n) aracı: tahminin DOĞRUYSA "
             "'doğru', aranan sayı tahmininden BÜYÜKSE 'daha büyük', KÜÇÜKSE 'daha küçük' döndürür. "
             "Mümkün olan EN AZ tahminle (ikili arama mantığıyla) gizli sayıyı bul. Bulduğun sayıyı EN SON "
             "satırda tam olarak `#### <sayı>` biçiminde ver.",
     "tools": [_tool("tahmin_et", "Bir tahmini değerlendirir: 'doğru' | 'daha büyük' | 'daha küçük'.",
                     {"n": {"type": "integer", "description": "tahmin edilen sayı (1-1000)"}}, ["n"])],
     "impls": {"tahmin_et": _tahmin_et}},

    {"key": "agentic_8", "seviye": 8, "baslik": "Agentic S8 (graf en kısa yol — 8 düğüm)",
     "grader_type": "math", "expected": 14.0,
     "cozum": "Dijkstra (A-H): A→C(3)→D(2)→F(4)→G(2)→H(3) = 14. (A-C-B-E-F-G-H ve diğerleri ≥14.)",
     "user": "A'dan H'ye uzanan bir yol ağı var (düğümler A-H). komsular(dugum) aracı, verilen düğümün "
             "komşularını ve her kenarın maliyetini döndürür (kenarlar çift yönlüdür). Grafı keşfederek "
             "A'dan H'ye EN DÜŞÜK toplam maliyetli yolu bul ve o yolun TOPLAM MALİYETİNİ EN SON satırda "
             "`#### <sayı>` biçiminde ver.",
     "tools": [_tool("komsular", "Bir düğümün komşularını {komsu: maliyet} olarak döndürür.",
                     {"dugum": {"type": "string", "description": "düğüm adı, örn. 'A'"}}, ["dugum"])],
     "impls": {"komsular": _komsular8}},

    {"key": "agentic_9", "seviye": 9, "baslik": "Agentic S9 (çok adımlı hesap — döviz)",
     "grader_type": "math", "expected": 5750.0,
     "cozum": "kur_getir: USD=32, EUR=35, GBP=40 TRY. 100·32 + 50·35 + 20·40 = 3200 + 1750 + 800 = 5750 TRY.",
     "user": "Bir müşterinin 100 USD, 50 EUR ve 20 GBP'si var. kur_getir(para) aracı, bir para biriminin "
             "Türk Lirası (TRY) karşılığını (1 birimin kaç TRY ettiğini) döndürür. Güncel kurları ARAÇTAN "
             "alarak müşterinin toplam servetini TRY cinsinden hesapla (kurları kafadan tahmin ETME). "
             "Toplamı EN SON satırda tam olarak `#### <sayı>` biçiminde ver.",
     "tools": [_tool("kur_getir", "Bir para biriminin TRY karşılığını döndürür (kur_try).",
                     {"para": {"type": "string", "description": "para birimi, örn. 'USD'"}}, ["para"])],
     "impls": {"kur_getir": _kur_getir}},

    {"key": "agentic_10", "seviye": 10, "baslik": "Agentic S10 (kara kutu 2 — kübik tümevarım)",
     "grader_type": "math", "expected": 714.0,
     "cozum": "kara_kutu2: 1→2,2→7,3→24,4→59,5→118,6→207. Üçüncü farklar sabit (6) → kübik f(x)=x³−2x+3. "
              "f(9)=729−18+3=714.",
     "user": "kara_kutu2(x) aracı gizli bir f(x) kuralını hesaplar AMA yalnızca 1 ≤ x ≤ 6 için çalışır "
             "(başka değer hata verir). Değerleri sorgulayarak f(x) kuralını ÇIKAR (ipucu: polinom olabilir), "
             "sonra f(9) değerini KENDİN hesapla (9'u soramazsın). Sonucu EN SON satırda tam olarak "
             "`#### <sayı>` biçiminde ver.",
     "tools": [_tool("kara_kutu2", "Gizli f(x) fonksiyonunu hesaplar; yalnızca 1 ≤ x ≤ 6 için geçerli.",
                     {"x": {"type": "integer", "description": "sorgulanacak değer (1-6)"}}, ["x"])],
     "impls": {"kara_kutu2": _kara_kutu2}},

    {"key": "agentic_11", "seviye": 11, "baslik": "Agentic S11 (mantık bulmacası 2 — 5 kişi)",
     "grader_type": "metin", "expected": "Ali",
     "cozum": "Veli=kahve, Deniz=ayran, Ayşe=su (ipucu3+5), Ali≠çay,≠su → Ali=kola; Can=çay. KOLA içen = Ali.",
     "user": "5 kişi var: Ali, Veli, Ayşe, Can, Deniz. Her biri tam olarak BİR içecek içiyor: çay, kahve, "
             "su, ayran, kola (her içecek bir kişiye ait). ipucu_oku(n) (n=1..6) ile TÜM ipuçlarını oku ve "
             "eşleştirmeyi mantıkla çöz. Sonra şunu yanıtla: KOLA içen kişi KİMDİR? Cevabı (kişinin adı) "
             "EN SON satırda `#### <ad>` biçiminde ver.",
     "tools": [_tool("ipucu_oku", "n numaralı ipucunu (metin) döndürür (n: 1-6).",
                     {"n": {"type": "integer", "description": "ipucu numarası 1-6"}}, ["n"])],
     "impls": {"ipucu_oku": _ipucu_oku_icecek}},
]

# İngilizce görev metinleri (LANG="en" iken kullanılır; araç adları/veri aynı kalır)
_AGENTIC_USER_EN = {
    "agentic_1": "An accounting ledger has 8 records. In every VALID record this rule holds: "
                 "bakiye = onceki_bakiye + alacak - borc (balance = previous_balance + credit - debit). "
                 "Exactly ONE record breaks this rule. First call kayit_listele to get the ids, then read "
                 "each record ONCE with kayit_oku and check the rule. As soon as you find the record that "
                 "breaks the rule, STOP and give its id on the LAST line exactly as `#### <id>`. Do not "
                 "re-read the same record.",
    "agentic_2": "You are looking for a secret number. There are 5 numbered clues; each gives one "
                 "constraint. Read ALL clues with ipucu_oku and find the SINGLE number satisfying all of "
                 "them by reasoning. Give the answer on the LAST line exactly as `#### <number>`.",
    "agentic_3": "A company has employees, each with a total sales figure. Using the tools, first find the "
                 "employee with the HIGHEST total sales, then find the NAME of that employee's MANAGER "
                 "(yonetici_id). Give the manager's name on the LAST line exactly as `#### <name>`.",
    "agentic_4": "The kara_kutu(x) tool computes a hidden function f(x) but works ONLY for 1 <= x <= 6 "
                 "(other values error). Probe several values, DEDUCE the rule f(x), then compute f(10) "
                 "YOURSELF (you cannot query 10). Give the result on the LAST line exactly as `#### <number>`.",
    "agentic_5": "There are 4 people: Ali, Veli, Ayse, Can. Each has ONE city (Istanbul, Ankara, Izmir, "
                 "Bursa) and ONE profession (Doktor=doctor, Muhendis=engineer, Ogretmen=teacher, "
                 "Avukat=lawyer); each city and profession belongs to exactly one person. Read ALL clues "
                 "with ipucu_oku (n=1..5) and solve the matching by logic. Then answer: in which CITY does "
                 "the LAWYER (Avukat) live? Give the city name on the LAST line as `#### <city>`.",
    "agentic_6": "There is a road network with nodes A through F. The komsular(dugum) tool returns a "
                 "node's neighbors and the cost of each edge (edges are bidirectional). Explore the graph "
                 "and find the LOWEST total-cost path from A to F, then give that TOTAL COST on the LAST "
                 "line exactly as `#### <number>`.",
    "agentic_7": "There is a hidden integer between 1 and 1000 (inclusive). The tahmin_et(n) tool returns "
                 "'correct' if your guess is right, 'higher' if the hidden number is GREATER than your "
                 "guess, and 'lower' if it is SMALLER. Find the hidden number with the FEWEST guesses "
                 "(binary-search logic). Give the number on the LAST line exactly as `#### <number>`.",
    "agentic_8": "There is a road network with nodes A through H. The komsular(dugum) tool returns a node's "
                 "neighbors and the cost of each edge (edges are bidirectional). Explore the graph and find "
                 "the LOWEST total-cost path from A to H, then give that TOTAL COST on the LAST line exactly "
                 "as `#### <number>`.",
    "agentic_9": "A customer has 100 USD, 50 EUR and 20 GBP. The kur_getir(para) tool returns how many "
                 "Turkish Lira (TRY) one unit of a currency is worth (kur_try). Using the rates FROM THE "
                 "TOOL (do not guess them), compute the customer's total wealth in TRY. Give the total on "
                 "the LAST line exactly as `#### <number>`.",
    "agentic_10": "The kara_kutu2(x) tool computes a hidden function f(x) but works ONLY for 1 <= x <= 6 "
                  "(other values error). Probe values, DEDUCE the rule f(x) (hint: it may be a polynomial), "
                  "then compute f(9) YOURSELF (you cannot query 9). Give the result on the LAST line exactly "
                  "as `#### <number>`.",
    "agentic_11": "There are 5 people: Ali, Veli, Ayşe, Can, Deniz. Each drinks exactly ONE beverage: çay "
                  "(tea), kahve (coffee), su (water), ayran, kola (cola); each beverage belongs to one "
                  "person. Read ALL clues with ipucu_oku (n=1..6) and solve the matching by logic. Then "
                  "answer: WHO drinks kola (cola)? Give the person's name on the LAST line as `#### <name>`.",
}
for _t in AGENTIC_TASKS:
    _t["user_en"] = _AGENTIC_USER_EN.get(_t["key"], _t["user"])


# ===========================================================================
#  ÇOK-TURLU ARAÇ DÖNGÜSÜ
# ===========================================================================

def agentic_loop(base_url, model_id, task, temperature, max_tokens,
                 no_think=False, max_turns=25, timeout=300, repeat_penalty=1.1):
    """Modeli araçlarla çok-turlu çalıştırır. Dayanıklı: hata/araçsızlık/limit -> durmaz.
    Döndürür: text (nihai cevap), turns, tool_calls, read_before_answer, total, completion_tokens, ttft."""
    url = base_url + "/v1/chat/completions"
    impls = task["impls"]
    user = task.get("user_en", task["user"]) if LANG == "en" else task["user"]
    messages = [{"role": "user", "content": user}]
    t0 = time.perf_counter()
    ttft = None
    tool_calls_count = 0
    comp_tokens = 0
    final_text = ""
    transcript = []
    turn = 0
    for turn in range(1, max_turns + 1):
        payload = {"model": model_id, "messages": messages, "tools": task["tools"],
                   "temperature": temperature, "max_tokens": max_tokens,
                   "repeat_penalty": repeat_penalty}
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
