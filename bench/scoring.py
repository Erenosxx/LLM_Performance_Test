# -*- coding: utf-8 -*-
"""Puanlama çekirdeği: kısmi puan, kademe ağırlıkları, avg@k, madde analizi.

Bu modüldeki her şey SAF fonksiyondur — ağ, dosya, GPU, model erişimi yok.
Böylece sunucu açmadan doğrulanabilir (`python -m bench.test_scoring`).

NEDEN KISMİ PUAN: 17 Ağustos 2026 koşusunda 80 puanlı sorunun 73'ünü dört
model de geçti, 1'ini dördü de kaldı; yalnız 6 soru ayrım üretti. İkili
puanlama (geçti/kaldı) 10 testin 9'unu geçen modele de hiçbirini geçemeyene
de aynı 0'ı veriyordu. Kısmi puan bu bilgiyi geri kazandırır.
"""

import math

# --- Zorluk kademeleri ------------------------------------------------------
# Ağırlık, sorunun toplam puana katkısıdır. Doygunluk oluştuğunda alt kademe
# emekliye ayrılır, üste yeni kademe eklenir; ölçek bu sayede yaşar.
KADEME_AGIRLIK = {
    "kolay": 1,      # sınıfın tamamının geçmesi beklenir (taban kontrolü)
    "orta": 2,       # çoğu geçer
    "zor": 3,        # ayrım burada başlar
    "acımasız": 4,   # bugün hiçbiri geçmeyebilir — tavan ölçümü
}
KADEME_SIRA = ["kolay", "orta", "zor", "acımasız"]
VARSAYILAN_KADEME = "orta"

# Tam puanın altındaki her şey "geçti" sayılmaz; kısmi puan ayrı raporlanır.
TAM_PUAN_ESIGI = 0.999

# Bir sorunun "ayırt ettiği" kabul edilen en küçük yayılım (tam puanın çeyreği).
AYIRT_ETME_ESIGI = 0.25


def agirlik(kademe):
    """Kademe adı -> ağırlık. Bilinmeyen/boş kademe varsayılana düşer."""
    return KADEME_AGIRLIK.get(kademe or VARSAYILAN_KADEME, KADEME_AGIRLIK[VARSAYILAN_KADEME])


def gecti_mi(puan):
    """Kısmi puandan ikili sonuç. None (puanlanmayan soru) None kalır."""
    if puan is None:
        return None
    return puan >= TAM_PUAN_ESIGI


def oran(dogru, toplam):
    """Güvenli oran: toplam 0 ise 0.0."""
    if not toplam:
        return 0.0
    return max(0.0, min(1.0, dogru / toplam))


# --- SQL satır kümesi puanı -------------------------------------------------

def satir_kumesi_puani(beklenen, gelen):
    """SQL sonucu için kısmi puan -> (puan, açıklama).

    Kademeli, çünkü "sıralaması eksik ama doğru veri" ile "tamamen yanlış
    sorgu" aynı şey değil:
      1.00  birebir aynı (sıra dahil)
      0.90  aynı satırlar, farklı sıra (ORDER BY eksik/yanlış)
      ≤0.80 kısmi kesişim -> F1 puanı 0.8 ile ölçeklenir
      0.00  hiç kesişim yok
    """
    if beklenen == gelen:
        return 1.0, "Sonuç birebir doğru."
    bek = _coklu_kume(beklenen)
    gel = _coklu_kume(gelen)
    if bek == gel:
        return 0.90, "Satırlar doğru ama sıralama farklı (ORDER BY eksik/yanlış)."
    kesisim = sum(min(bek[k], gel.get(k, 0)) for k in bek)
    if not kesisim:
        return 0.0, f"Hiçbir satır eşleşmedi ({len(gelen)} satır döndü, {len(beklenen)} bekleniyordu)."
    duyarlilik = kesisim / max(1, sum(gel.values()))    # precision
    anma = kesisim / max(1, sum(bek.values()))          # recall
    f1 = 2 * duyarlilik * anma / (duyarlilik + anma)
    return round(0.8 * f1, 4), (f"Kısmi eşleşme: {kesisim} satır tuttu "
                                f"(F1={f1:.2f}; {len(gelen)}/{len(beklenen)} satır).")


def _coklu_kume(satirlar):
    """Satır listesini çoklu kümeye (multiset) çevirir; sıra bilgisini atar."""
    sayac = {}
    for s in satirlar or []:
        anahtar = tuple(s) if isinstance(s, (list, tuple)) else (s,)
        sayac[anahtar] = sayac.get(anahtar, 0) + 1
    return sayac


# --- avg@k: aynı sorunun k denemesini birleştirme ---------------------------

def birlestir(puanlar):
    """k denemenin puanını tek sonuca indirger.

    -> {"puan": ortalama, "kararlilik": 1-yayılım, "denemeler": [...], "k": k}

    KARARLILIK tanımı: 1 - (en yüksek - en düşük). Üç denemede de aynı sonuç
    çıkarsa 1.0; biri 0 biri 1 ise 0.0. Kart ayarıyla (rastgele örnekleme)
    koşulduğu için "şansa geçen" sorular bu metrikte görünür hale gelir.
    """
    gecerli = [p for p in puanlar if p is not None]
    if not gecerli:
        return {"puan": None, "kararlilik": None, "denemeler": list(puanlar), "k": 0}
    ort = sum(gecerli) / len(gecerli)
    yayilim = max(gecerli) - min(gecerli)
    return {"puan": round(ort, 4), "kararlilik": round(1.0 - yayilim, 4),
            "denemeler": [None if p is None else round(p, 4) for p in puanlar],
            "k": len(gecerli)}


# --- Kategori ve toplam özeti ----------------------------------------------

def kategori_ozeti(sonuclar, kategoriler):
    """Kategori bazında ham/ağırlıklı puan, geçme sayısı, süre, kararlılık.

    `passed` ve `graded` alanları ESKİ raporun beklediği biçimde korunur;
    yeni alanlar eklenerek geriye dönük uyum sağlanır.
    """
    cikti = {}
    for kat in kategoriler:
        maddeler = [r for r in sonuclar if r.get("kategori") == kat]
        puanli = [r for r in maddeler if r.get("puan") is not None]
        agirlikli = sum(agirlik(r.get("kademe")) * r["puan"] for r in puanli)
        azami = sum(agirlik(r.get("kademe")) for r in puanli)
        kararliliklar = [r["kararlilik"] for r in puanli if r.get("kararlilik") is not None]
        cikti[kat] = {
            # --- eski alanlar (rapor kodu bunlara dayanıyor) ---
            "passed": sum(1 for r in puanli if gecti_mi(r["puan"])),
            "graded": len(puanli),
            "items": len(maddeler),
            "time": sum(r.get("total") or 0 for r in maddeler),
            # --- yeni alanlar ---
            "ham_puan": round(sum(r["puan"] for r in puanli), 3),
            "agirlikli_puan": round(agirlikli, 3),
            "azami_agirlik": azami,
            "kararlilik": round(sum(kararliliklar) / len(kararliliklar), 3) if kararliliklar else None,
            "en_zor_kademe": en_zor_cozulen(puanli),
            "kesilen": sum(1 for r in maddeler if r.get("kesildi")),
        }
    return cikti


def en_zor_cozulen(puanli_sonuclar):
    """Modelin TAM puan aldığı en zor kademe. Hiçbiri yoksa None."""
    cozulen = {r.get("kademe") or VARSAYILAN_KADEME
               for r in puanli_sonuclar if gecti_mi(r.get("puan"))}
    for k in reversed(KADEME_SIRA):
        if k in cozulen:
            return k
    return None


def toplam_ozet(kategori_ozetleri):
    """Kategori özetlerinden genel toplam."""
    agirlikli = sum(c["agirlikli_puan"] for c in kategori_ozetleri.values())
    azami = sum(c["azami_agirlik"] for c in kategori_ozetleri.values())
    return {
        "agirlikli_puan": round(agirlikli, 3),
        "azami_agirlik": azami,
        "yuzde": round(100.0 * agirlikli / azami, 1) if azami else 0.0,
        "gecen": sum(c["passed"] for c in kategori_ozetleri.values()),
        "puanli": sum(c["graded"] for c in kategori_ozetleri.values()),
        "kesilen": sum(c["kesilen"] for c in kategori_ozetleri.values()),
    }


# --- Madde analizi: testin kendini denetlemesi ------------------------------

def madde_analizi(model_sonuclari):
    """Sorular modelleri ayırt ediyor mu? -> yayılıma göre sıralı liste.

    model_sonuclari: {model_adı: [sonuç kaydı, ...]}
    Her kayıtta en az "key" ve "puan" olmalı.

    En az 2 model gerekir; tek modelle ayrım hesaplanamaz (boş liste döner).
    Bu fonksiyon testin bakımını otomatikleştirir: doygun maddeler
    ("herkes geçti"/"herkes kaldı") emeklilik adayı olarak işaretlenir.
    """
    if len(model_sonuclari) < 2:
        return []
    kayitlar = {}
    for model, sonuclar in model_sonuclari.items():
        for r in sonuclar:
            if r.get("puan") is None:
                continue
            k = kayitlar.setdefault(r["key"], {"key": r["key"], "baslik": r.get("baslik", r["key"]),
                                               "kategori": r.get("kategori", ""),
                                               "kademe": r.get("kademe"), "puanlar": {}})
            k["puanlar"][model] = r["puan"]
    cikti = []
    for k in kayitlar.values():
        p = list(k["puanlar"].values())
        if len(p) < 2:
            continue
        yayilim = max(p) - min(p)
        ortalama = sum(p) / len(p)
        sapma = math.sqrt(sum((x - ortalama) ** 2 for x in p) / len(p))
        herkes_gecti = all(gecti_mi(x) for x in p)
        herkes_kaldi = all(x <= 0.0 for x in p)
        cikti.append({**k, "yayilim": round(yayilim, 4), "ortalama": round(ortalama, 4),
                      "sapma": round(sapma, 4),
                      "ayirt_ediyor": yayilim >= AYIRT_ETME_ESIGI,
                      "herkes_gecti": herkes_gecti, "herkes_kaldi": herkes_kaldi,
                      "emeklilik_adayi": herkes_gecti or herkes_kaldi})
    cikti.sort(key=lambda x: (-x["yayilim"], x["key"]))
    return cikti


def analiz_ozeti(analiz):
    """Madde analizinin tek satırlık özeti."""
    if not analiz:
        return {"toplam": 0, "ayirt_eden": 0, "emeklilik_adayi": 0, "oran": 0.0}
    ayirt = sum(1 for a in analiz if a["ayirt_ediyor"])
    return {
        "toplam": len(analiz),
        "ayirt_eden": ayirt,
        "emeklilik_adayi": sum(1 for a in analiz if a["emeklilik_adayi"]),
        "oran": round(100.0 * ayirt / len(analiz), 1),
    }
