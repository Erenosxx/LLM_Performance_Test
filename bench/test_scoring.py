# -*- coding: utf-8 -*-
"""bench/scoring.py doğrulaması. Sunucu/GPU gerektirmez.

Çalıştır:  python -m bench.test_scoring
"""

from bench import scoring as S


def esit(bulunan, beklenen, ad):
    if bulunan != beklenen:
        raise AssertionError(f"{ad}: beklenen {beklenen!r}, bulunan {bulunan!r}")


def yakin(bulunan, beklenen, ad, tol=1e-3):
    if bulunan is None or abs(bulunan - beklenen) > tol:
        raise AssertionError(f"{ad}: beklenen ≈{beklenen}, bulunan {bulunan!r}")


def test_agirlik():
    esit(S.agirlik("kolay"), 1, "kolay ağırlık")
    esit(S.agirlik("acımasız"), 4, "acımasız ağırlık")
    esit(S.agirlik(None), 2, "kademe yoksa varsayılan orta")
    esit(S.agirlik("bilinmeyen"), 2, "bilinmeyen kademe varsayılana düşer")


def test_gecti_mi():
    esit(S.gecti_mi(1.0), True, "tam puan geçer")
    esit(S.gecti_mi(0.999), True, "eşik sınırı geçer")
    esit(S.gecti_mi(0.9), False, "kısmi puan geçmez")
    esit(S.gecti_mi(None), None, "puanlanmayan soru None kalır")


def test_oran():
    yakin(S.oran(9, 10), 0.9, "9/10")
    esit(S.oran(0, 0), 0.0, "sıfıra bölme")
    yakin(S.oran(15, 10), 1.0, "1'i aşamaz")


def test_satir_kumesi():
    bek = [(1, "a"), (2, "b"), (3, "c")]
    p, _ = S.satir_kumesi_puani(bek, bek)
    yakin(p, 1.0, "birebir aynı")

    p, aciklama = S.satir_kumesi_puani(bek, [(3, "c"), (1, "a"), (2, "b")])
    yakin(p, 0.90, "sıra farklı")
    if "sıralama" not in aciklama:
        raise AssertionError("sıra farkı açıklamada belirtilmeli")

    p, _ = S.satir_kumesi_puani(bek, [(1, "a"), (2, "b")])       # 2/3 tuttu
    # duyarlılık 2/2=1, anma 2/3 -> F1=0.8 -> 0.8*0.8=0.64
    yakin(p, 0.64, "kısmi kesişim")

    p, _ = S.satir_kumesi_puani(bek, [(9, "z")])
    yakin(p, 0.0, "hiç kesişim yok")

    p, _ = S.satir_kumesi_puani(bek, [])
    yakin(p, 0.0, "boş sonuç")

    # KRİTİK: kısmi puan asla tam puanı geçmemeli, yoksa yanlış sorgu 'geçti' olur
    for gelen in ([(1, "a")], [(1, "a"), (2, "b")], [(3, "c"), (1, "a"), (2, "b")]):
        p, _ = S.satir_kumesi_puani(bek, gelen)
        if S.gecti_mi(p):
            raise AssertionError(f"yanlış sonuç 'geçti' sayıldı: {gelen}")


def test_birlestir():
    r = S.birlestir([1.0, 1.0, 1.0])
    yakin(r["puan"], 1.0, "avg@3 hepsi doğru")
    yakin(r["kararlilik"], 1.0, "hepsi aynı -> kararlılık 1")

    r = S.birlestir([1.0, 0.0, 1.0])
    yakin(r["puan"], 0.6667, "avg@3 ortalama")
    yakin(r["kararlilik"], 0.0, "0 ile 1 arası salınım -> kararlılık 0")

    r = S.birlestir([0.8, 0.9, 1.0])
    yakin(r["puan"], 0.9, "kısmi puanların ortalaması")
    yakin(r["kararlilik"], 0.8, "yayılım 0.2 -> kararlılık 0.8")

    r = S.birlestir([None, None])
    esit(r["puan"], None, "hepsi None ise puan None")

    r = S.birlestir([1.0, None, 0.0])
    yakin(r["puan"], 0.5, "None denemeler atlanır")
    esit(r["k"], 2, "geçerli deneme sayısı")


def kayit(key, kat, puan, kademe="orta", kararlilik=1.0, total=1.0, kesildi=False):
    return {"key": key, "baslik": key, "kategori": kat, "puan": puan, "kademe": kademe,
            "kararlilik": kararlilik, "total": total, "kesildi": kesildi}


def test_kategori_ozeti():
    sonuclar = [
        kayit("k1", "Kod", 1.0, "kolay"),      # ağırlık 1 -> 1.0
        kayit("k2", "Kod", 0.5, "zor"),        # ağırlık 3 -> 1.5
        kayit("k3", "Kod", None, "orta"),      # puanlanmaz
        kayit("s1", "SQL", 0.0, "acımasız", kesildi=True),
    ]
    ozet = S.kategori_ozeti(sonuclar, ["Kod", "SQL"])
    esit(ozet["Kod"]["graded"], 2, "puanlanan soru sayısı")
    esit(ozet["Kod"]["items"], 3, "toplam soru sayısı")
    esit(ozet["Kod"]["passed"], 1, "yalnız tam puan 'geçti' sayılır")
    yakin(ozet["Kod"]["agirlikli_puan"], 2.5, "ağırlıklı puan")
    esit(ozet["Kod"]["azami_agirlik"], 4, "azami ağırlık = 1 + 3")
    esit(ozet["Kod"]["en_zor_kademe"], "kolay", "tam puan alınan en zor kademe")
    esit(ozet["SQL"]["kesilen"], 1, "kesilme sayısı")

    toplam = S.toplam_ozet(ozet)
    yakin(toplam["agirlikli_puan"], 2.5, "genel ağırlıklı puan")
    esit(toplam["azami_agirlik"], 8, "genel azami (4 + 4)")
    yakin(toplam["yuzde"], 31.2, "yüzde")


def test_en_zor_kademe():
    esit(S.en_zor_cozulen([kayit("a", "K", 1.0, "kolay"), kayit("b", "K", 1.0, "acımasız")]),
         "acımasız", "en zor tam puanlı kademe seçilir")
    esit(S.en_zor_cozulen([kayit("a", "K", 0.9, "zor")]), None, "kısmi puan kademe saymaz")


def test_madde_analizi():
    # 17 Ağustos'un gerçek deseni: herkesin geçtiği soru ayrım üretmiyor
    m = {
        "A": [kayit("q1", "Kod", 1.0), kayit("q2", "SQL", 1.0), kayit("q3", "SQL", 0.0)],
        "B": [kayit("q1", "Kod", 1.0), kayit("q2", "SQL", 0.0), kayit("q3", "SQL", 0.0)],
        "C": [kayit("q1", "Kod", 1.0), kayit("q2", "SQL", 0.5), kayit("q3", "SQL", 0.0)],
    }
    analiz = S.madde_analizi(m)
    esit(len(analiz), 3, "üç soru analiz edildi")
    d = {a["key"]: a for a in analiz}
    esit(d["q1"]["ayirt_ediyor"], False, "herkesin geçtiği soru ayırt etmez")
    esit(d["q1"]["emeklilik_adayi"], True, "herkes geçti -> emeklilik adayı")
    esit(d["q2"]["ayirt_ediyor"], True, "farklı puanlar -> ayırt eder")
    esit(d["q3"]["herkes_kaldi"], True, "herkes kaldı")
    esit(d["q3"]["emeklilik_adayi"], True, "herkes kaldı -> emeklilik adayı")
    esit(analiz[0]["key"], "q2", "en ayırt edici soru başta")

    ozet = S.analiz_ozeti(analiz)
    esit(ozet["ayirt_eden"], 1, "ayırt eden soru sayısı")
    esit(ozet["emeklilik_adayi"], 2, "emeklilik adayı sayısı")

    esit(S.madde_analizi({"A": m["A"]}), [], "tek modelle ayrım hesaplanamaz")


def main():
    testler = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    hata = 0
    for t in testler:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            hata += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(testler) - hata}/{len(testler)} test geçti.")
    return 1 if hata else 0


if __name__ == "__main__":
    raise SystemExit(main())
