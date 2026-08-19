# -*- coding: utf-8 -*-
"""Yeni branşların değerlendiricileri: talimat, json, halüsinasyon.

Hepsi `(puan 0-1, detay, output_info)` döndürür — mevcut grader'larla aynı
sözleşme. Mevcut grader'lar (code/sql/math/metin/medikal) `llm_perf_test.py`
içinde kalır; buraya YENİ branşlar gelir.

Tasarım ilkesi: her ölçüt MAKİNEYLE denetlenebilir olmalı. Bir kısıt insan
yorumu gerektiriyorsa bu dosyaya girmez — yaratıcılık branşında kalır.
"""

import json
import re
import unicodedata

# ===========================================================================
#  TALİMATA UYMA
# ===========================================================================
# Her soru bir kısıt listesi taşır; puan = sağlanan kısıt / toplam kısıt.
# IFBench mantığı: kısıtlar birbirini zorlaştırır (negatif kısıt + sıralama +
# uzunluk aynı anda). Modeller burada belirgin biçimde ayrışır.


def _satirlar(metin):
    """Boş olmayan satırlar."""
    return [s.strip() for s in (metin or "").strip().splitlines() if s.strip()]


def _maddeler(metin):
    """Madde işareti/numara ile başlayan satırlar -> işaretsiz içerik.

    Model '1. ...', '- ...', '* ...', '1) ...' gibi biçimlerin herhangi birini
    kullanabilir; kısıt madde SAYISI ise biçim serbest bırakılır."""
    cikti = []
    for s in _satirlar(metin):
        m = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$", s)
        if m:
            cikti.append(m.group(1).strip())
    return cikti or _satirlar(metin)


def _kelimeler(metin):
    return re.findall(r"\w+", metin or "", flags=re.UNICODE)


def _sadelestir(s):
    """Büyük/küçük farkını sil (Türkçe I/ı dahil), harfleri BİRLEŞİK bırak.

    NFC (birleşik) kullanılır, NFKD DEĞİL: NFKD 'ü' harfini 'u' + birleşen
    ayırıcıya böler, birleşen ayırıcı \\w sayılmadığı için `\\b` kelime sınırı
    bozulur ve 'çünkü' gibi sözcükler hiç bulunamaz (referans çözüm testinde
    yakalandı)."""
    s = (s or "").replace("İ", "i").replace("I", "ı").lower()
    return unicodedata.normalize("NFC", s)


# --- Tek tek kısıt denetleyicileri -----------------------------------------
# Her denetleyici: (cevap, param) -> (saglandi: bool, aciklama: str)

def _k_madde_sayisi(cevap, n):
    bulunan = len(_maddeler(cevap))
    return bulunan == n, f"madde sayısı {bulunan} (istenen {n})"


def _k_satir_sayisi(cevap, n):
    bulunan = len(_satirlar(cevap))
    return bulunan == n, f"satır sayısı {bulunan} (istenen {n})"


def _k_harf_basi(cevap, harf):
    maddeler = _maddeler(cevap)
    if not maddeler:
        return False, "madde bulunamadı"
    kotu = [m for m in maddeler if not _sadelestir(m).startswith(_sadelestir(harf))]
    return not kotu, ("hepsi doğru harfle başlıyor" if not kotu
                      else f"{len(kotu)} madde '{harf}' ile başlamıyor")


def _kelime_gecti_mi(cevap, kelime):
    """SÖZCÜK olarak arar, alt dizi olarak değil.

    Alt dizi araması yanlış sonuç verir: 've' yasağı 'güvenlik' sözcüğünü de
    yakalar ve modeli haksız yere cezalandırırdı."""
    desen = r"\b" + re.escape(_sadelestir(kelime)) + r"\b"
    return bool(re.search(desen, _sadelestir(cevap), re.UNICODE))


def _k_yasak_kelime(cevap, kelime):
    var = _kelime_gecti_mi(cevap, kelime)
    return not var, (f"yasak sözcük '{kelime}' geçmiyor" if not var
                     else f"yasak sözcük '{kelime}' GEÇİYOR")


def _k_zorunlu_kelime(cevap, kelime):
    var = _kelime_gecti_mi(cevap, kelime)
    return var, (f"'{kelime}' var" if var else f"'{kelime}' YOK")


def _k_kelime_en_fazla(cevap, n):
    bulunan = len(_kelimeler(cevap))
    return bulunan <= n, f"{bulunan} kelime (en fazla {n})"


def _k_kelime_en_az(cevap, n):
    bulunan = len(_kelimeler(cevap))
    return bulunan >= n, f"{bulunan} kelime (en az {n})"


def _k_uzundan_kisaya(cevap, _):
    uz = [len(_kelimeler(m)) for m in _maddeler(cevap)]
    ok = all(a >= b for a, b in zip(uz, uz[1:]))
    return ok, f"madde uzunlukları {uz} {'azalan' if ok else 'AZALAN DEĞİL'}"


def _k_regex_yok(cevap, desen):
    var = re.search(desen, cevap or "", re.IGNORECASE | re.MULTILINE)
    return not var, ("yasak desen yok" if not var else f"yasak desen bulundu: {var.group(0)[:30]!r}")


def _k_regex_var(cevap, desen):
    var = re.search(desen, cevap or "", re.IGNORECASE | re.MULTILINE)
    return bool(var), ("istenen desen var" if var else "istenen desen YOK")


def _k_son_karakter(cevap, ch):
    m = (cevap or "").strip()
    return m.endswith(ch), f"son karakter {m[-1:]!r} (istenen {ch!r})"


def _k_tumu_buyuk(cevap, _):
    harfler = [c for c in (cevap or "") if c.isalpha()]
    ok = bool(harfler) and all(c.upper() == c for c in harfler)
    return ok, "tümü büyük harf" if ok else "küçük harf içeriyor"


def _k_her_madde_kelime_en_fazla(cevap, n):
    maddeler = _maddeler(cevap)
    kotu = [m for m in maddeler if len(_kelimeler(m)) > n]
    return not kotu, ("her madde sınır içinde" if not kotu
                      else f"{len(kotu)} madde {n} kelimeyi aşıyor")


def _k_her_madde_kelime_tam(cevap, n):
    maddeler = _maddeler(cevap)
    uz = [len(_kelimeler(m)) for m in maddeler]
    kotu = [u for u in uz if u != n]
    return (bool(maddeler) and not kotu), (f"madde uzunlukları {uz} (hepsi {n} olmalı)")


def _k_alfabetik(cevap, _):
    maddeler = [_sadelestir(m) for m in _maddeler(cevap)]
    ok = all(a <= b for a, b in zip(maddeler, maddeler[1:]))
    return ok, "alfabetik sırada" if ok else "alfabetik sırada DEĞİL"


def _k_kelime_artisi(cevap, n):
    """Her madde bir öncekinden TAM n kelime uzun olmalı.

    Modelin kendi çıktısını sayması gerekir — dil modelleri için gerçekten zor
    ve tamamen makineyle denetlenebilir."""
    uz = [len(_kelimeler(m)) for m in _maddeler(cevap)]
    if len(uz) < 2:
        return False, f"en az 2 madde gerekli (bulunan {len(uz)})"
    farklar = [b - a for a, b in zip(uz, uz[1:])]
    ok = all(f == n for f in farklar)
    return ok, f"uzunluklar {uz}, farklar {farklar} (hepsi {n} olmalı)"


def _k_ilk_madde_kelime(cevap, n):
    maddeler = _maddeler(cevap)
    if not maddeler:
        return False, "madde yok"
    bulunan = len(_kelimeler(maddeler[0]))
    return bulunan == n, f"ilk madde {bulunan} kelime (istenen {n})"


def _k_bas_harfler(cevap, harfler):
    """Maddelerin baş harfleri SIRAYLA verilen diziye eşit olmalı."""
    maddeler = _maddeler(cevap)
    bulunan = "".join(_sadelestir(m[:1]) for m in maddeler)
    beklenen = _sadelestir(harfler)
    return bulunan == beklenen, f"baş harfler '{bulunan}' (istenen '{beklenen}')"


def _k_toplam_karakter_en_fazla(cevap, n):
    uz = len((cevap or "").strip())
    return uz <= n, f"{uz} karakter (en fazla {n})"


KISIT_DENETCILERI = {
    "kelime_artisi": _k_kelime_artisi,
    "ilk_madde_kelime": _k_ilk_madde_kelime,
    "bas_harfler": _k_bas_harfler,
    "toplam_karakter_en_fazla": _k_toplam_karakter_en_fazla,
    "madde_sayisi": _k_madde_sayisi,
    "satir_sayisi": _k_satir_sayisi,
    "harf_basi": _k_harf_basi,
    "yasak_kelime": _k_yasak_kelime,
    "zorunlu_kelime": _k_zorunlu_kelime,
    "kelime_en_fazla": _k_kelime_en_fazla,
    "kelime_en_az": _k_kelime_en_az,
    "uzundan_kisaya": _k_uzundan_kisaya,
    "regex_yok": _k_regex_yok,
    "regex_var": _k_regex_var,
    "son_karakter": _k_son_karakter,
    "tumu_buyuk": _k_tumu_buyuk,
    "her_madde_kelime_en_fazla": _k_her_madde_kelime_en_fazla,
    "her_madde_kelime_tam": _k_her_madde_kelime_tam,
    "alfabetik": _k_alfabetik,
}


def grade_talimat(cevap, kisitlar):
    """kisitlar = [(tip, param), ...] -> (puan, detay, info).

    Puan = sağlanan kısıt / toplam kısıt. Kısmi puan burada özellikle
    anlamlı: 8 kısıttan 7'sini tutturan model ile hiçbirini tutturmayan
    aynı değildir."""
    satirlar, saglanan = [], 0
    for tip, param in kisitlar:
        denetci = KISIT_DENETCILERI.get(tip)
        if not denetci:
            satirlar.append({"kisit": tip, "ok": False, "not": "bilinmeyen kısıt tipi"})
            continue
        try:
            ok, aciklama = denetci(cevap, param)
        except Exception as e:
            ok, aciklama = False, f"denetim hatası: {e}"
        saglanan += 1 if ok else 0
        satirlar.append({"kisit": f"{tip}({param})" if param is not None else tip,
                         "ok": bool(ok), "not": aciklama})
    toplam = len(kisitlar)
    puan = saglanan / toplam if toplam else 0.0
    eksik = [s["kisit"] for s in satirlar if not s["ok"]]
    detay = (f"{saglanan}/{toplam} kısıt sağlandı."
             + (f" Eksik: {', '.join(eksik[:4])}" if eksik else ""))
    return puan, detay, {"type": "talimat", "rows": satirlar}


# ===========================================================================
#  YAPILANDIRILMIŞ ÇIKTI (JSON)
# ===========================================================================

def _json_cikar(metin):
    """Cevaptan JSON nesnesini ayıklar: kod bloğu -> ilk süslü parantez bloğu."""
    if not metin:
        return None, "boş cevap"
    bloklar = re.findall(r"```(?:json)?\s*\n(.*?)```", metin, re.DOTALL)
    adaylar = [b.strip() for b in bloklar] if bloklar else []
    ham = metin.strip()
    ilk, son = ham.find("{"), ham.rfind("}")
    if ilk >= 0 and son > ilk:
        adaylar.append(ham[ilk:son + 1])
    for aday in adaylar:
        try:
            return json.loads(aday), None
        except json.JSONDecodeError as e:
            hata = str(e)
    return None, (hata if adaylar else "JSON bloğu bulunamadı")


def _yol_oku(nesne, yol):
    """'siparis.kalemler.0.adet' -> değer. Bulunamazsa KeyError."""
    gecerli = nesne
    for parca in yol.split("."):
        if isinstance(gecerli, list):
            gecerli = gecerli[int(parca)]
        else:
            gecerli = gecerli[parca]
    return gecerli


def grade_json(cevap, sema, beklenen_alanlar):
    """Üç aşamalı kısmi puan:
        0,30  geçerli JSON üretildi
      + 0,40  şemaya uydu
      + 0,30  beklenen alan değerleri doğru
    Böylece "JSON bile üretemedi" ile "şema doğru ama bir alanı yanlış"
    ayrışır."""
    nesne, hata = _json_cikar(cevap)
    if nesne is None:
        return 0.0, f"Geçerli JSON yok ({hata}).", {"type": "json", "rows": [
            {"asama": "geçerli JSON", "ok": False, "not": hata}]}
    satirlar = [{"asama": "geçerli JSON", "ok": True, "not": "ayrıştırıldı"}]
    puan = 0.30

    sema_ok, sema_notu = True, "şema doğrulandı"
    try:
        import jsonschema
        jsonschema.validate(nesne, sema)
    except ImportError:
        sema_notu = "jsonschema kurulu değil — aşama atlandı (puan verildi)"
    except Exception as e:
        sema_ok = False
        sema_notu = str(e).split("\n")[0][:120]
    satirlar.append({"asama": "şema uyumu", "ok": sema_ok, "not": sema_notu})
    if sema_ok:
        puan += 0.40

    dogru = 0
    for yol, beklenen in (beklenen_alanlar or {}).items():
        try:
            bulunan = _yol_oku(nesne, yol)
            ok = bulunan == beklenen
        except Exception:
            bulunan, ok = "(yok)", False
        dogru += 1 if ok else 0
        satirlar.append({"asama": f"alan {yol}", "ok": ok,
                         "not": f"beklenen {beklenen!r}, bulunan {bulunan!r}"})
    if beklenen_alanlar:
        puan += 0.30 * (dogru / len(beklenen_alanlar))
    else:
        puan += 0.30

    detay = (f"JSON geçerli · şema {'uydu' if sema_ok else 'UYMADI'} · "
             f"alanlar {dogru}/{len(beklenen_alanlar or {})} doğru")
    return round(min(1.0, puan), 4), detay, {"type": "json", "rows": satirlar}


# ===========================================================================
#  HALÜSİNASYON DİRENCİ
# ===========================================================================
# Doğru davranış: bilmediğini/böyle bir şey olmadığını SÖYLEMEK.
# Yanlış davranış: kendinden emin biçimde uydurmak.

BELIRSIZLIK_ISARETLERI = [
    "bilmiyorum", "bilgim yok", "bilgi bulunmuyor", "bilgiye sahip değilim",
    "emin değilim", "doğrulayamıyorum", "doğrulanamıyor", "kaynak bulunmuyor",
    "kaynak yok", "mevcut değil", "bulunmamaktadır", "bulunmuyor", "yoktur",
    "böyle bir", "rastlamadım", "bilinmiyor", "veri yok", "erişimim yok",
    "uydurmak istemem", "yanıltıcı olabilir", "teyit ed", "varsayım",
    "elimde bilgi", "kayıt bulunmuyor", "tanımlı değil", "geçersiz",
    "yanlış öncül", "hatalı öncül", "böyle bir revizyon", "diye bir",
]

# "Kesin bilgi" izlenimi veren desenler: yüzde, tarih aralığı, ölçü, doz.
UYDURMA_DESENLERI = [
    r"%\s?\d+[.,]?\d*",                 # %12,5
    r"\b\d+[.,]?\d*\s?(mm|cm|ml|mg|kg|french|fr)\b",
    r"\b\d{4}\s?(yılında|yılı)\b",
    r"\b\d+[.,]?\d*\s?(kat|misli)\b",
]


def grade_halusinasyon(cevap, yasak_desenler=None, soru_metni=None):
    """Kademeli puan:
        1,0  belirsizlik/ret ifadesi var, uydurma spesifik veri YOK
        0,5  belirsizlik ifadesi var ama yine de spesifik veri üretmiş
        0,0  kendinden emin uydurma (belirsizlik ifadesi yok)

    `soru_metni` verilirse, SORUDA GEÇEN sayı/ölçüler uydurma sayılmaz.
    Bu düzeltme canlı provada bulundu: "2025 yıllık raporunda..." diye sorulan
    soruya "2025 raporuna dair bilgim yok" diyen model, soruyu alıntıladığı
    için uydurmuş sayılıyordu (yanlış pozitif).
    """
    metin = _sadelestir(cevap or "")
    belirsiz = [i for i in BELIRSIZLIK_ISARETLERI if _sadelestir(i) in metin]
    desenler = list(UYDURMA_DESENLERI) + list(yasak_desenler or [])
    soru_sade = _sadelestir(soru_metni or "")
    uydurma = []
    for d in desenler:
        for m in re.finditer(d, cevap or "", re.IGNORECASE):
            parca = m.group(0)
            # Soruda zaten geçiyorsa model uydurmamış, alıntılamıştır.
            if soru_sade and _sadelestir(parca).strip() in soru_sade:
                continue
            uydurma.append(parca)
            break
    satirlar = [
        {"olcut": "belirsizlik/ret ifadesi", "ok": bool(belirsiz),
         "not": (", ".join(belirsiz[:3]) if belirsiz else "yok — model kendinden emin konuşmuş")},
        {"olcut": "uydurma spesifik veri", "ok": not uydurma,
         "not": ("yok" if not uydurma else "bulundu: " + ", ".join(u[:20] for u in uydurma[:3]))},
    ]
    if belirsiz and not uydurma:
        return 1.0, "Bilmediğini söyledi, uydurmadı.", {"type": "halusinasyon", "rows": satirlar}
    bilgi = {"type": "halusinasyon", "rows": satirlar}
    if belirsiz:
        return 0.5, ("Belirsizlik belirtti ama yine de spesifik veri üretti: "
                     + ", ".join(u[:20] for u in uydurma[:3])), bilgi
    return 0.0, "Kendinden emin biçimde uydurdu (belirsizlik ifadesi yok).", bilgi
