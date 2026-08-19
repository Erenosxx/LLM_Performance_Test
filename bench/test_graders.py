# -*- coding: utf-8 -*-
"""Yeni grader'ların doğrulaması: doğru cevap GEÇMELİ, bozuk cevap KALMALI.

Bir grader'ın en tehlikeli hatası yanlış cevabı geçirmesidir (false pass) —
ölçüm sessizce anlamsızlaşır. Bu yüzden her grader için hem pozitif hem
negatif durum sınanır.

Çalıştır:  python -m bench.test_graders
"""

import json

from bench import graders as G
from bench.banks.talimat import TALIMAT_SORULARI
from bench.banks.json_cikti import JSON_SORULARI
from bench.banks.halusinasyon import HALUSINASYON_SORULARI, REFERANS_RET


def yakin(bulunan, beklenen, ad, tol=1e-3):
    if bulunan is None or abs(bulunan - beklenen) > tol:
        raise AssertionError(f"{ad}: beklenen ≈{beklenen}, bulunan {bulunan!r}")


def dogru(kosul, ad):
    if not kosul:
        raise AssertionError(ad)


# --- TALİMAT ---------------------------------------------------------------

def test_talimat_referanslar_gecer():
    for q in TALIMAT_SORULARI:
        puan, detay, _ = G.grade_talimat(q["cozum"], q["kisitlar"])
        yakin(puan, 1.0, f"Talimat S{q['seviye']} referansı ({detay})")


def test_talimat_ihlal_kalir():
    q = TALIMAT_SORULARI[1]          # 5 madde, 'K' ile başlamalı, rakam yok
    puan, _, _ = G.grade_talimat("- Armut\n- Elma\n- 3 muz", q["kisitlar"])
    dogru(puan < 0.5, f"kısıtları ihlal eden cevap yüksek puan aldı: {puan}")


def test_talimat_kismi_puan():
    q = TALIMAT_SORULARI[1]
    # madde sayısı doğru + harf doğru, ama rakam var -> 2/3
    puan, _, _ = G.grade_talimat("- Kalem\n- Kitap\n- Kapı\n- Kutu\n- Kuş 5", q["kisitlar"])
    yakin(puan, 2 / 3, "kısmi kısıt uyumu")


def test_talimat_kelime_siniri():
    # 've' yasağı 'güvenlik' sözcüğünü YAKALAMAMALI (alt dizi tuzağı)
    ok, _ = G.KISIT_DENETCILERI["yasak_kelime"]("Güvenlik önlemleri alındı.", "ve")
    dogru(ok, "'güvenlik' içindeki 've' yasak sayıldı — kelime sınırı çalışmıyor")
    ok2, _ = G.KISIT_DENETCILERI["yasak_kelime"]("Kalem ve defter", "ve")
    dogru(not ok2, "gerçek 've' yakalanmadı")


def test_talimat_turkce_kelime():
    ok, _ = G.KISIT_DENETCILERI["zorunlu_kelime"]("Bu doğrudur çünkü ölçtük.", "çünkü")
    dogru(ok, "Türkçe sözcük bulunamadı (NFC normalizasyon hatası)")


# --- JSON ------------------------------------------------------------------

def test_json_referanslar_gecer():
    for q in JSON_SORULARI:
        puan, detay, _ = G.grade_json(q["cozum"], q["sema"], q["beklenen"])
        yakin(puan, 1.0, f"JSON S{q['seviye']} referansı ({detay})")


def test_json_gecersiz_sifir():
    q = JSON_SORULARI[0]
    puan, _, _ = G.grade_json("Tabii, işte bilgiler: ad Ahmet, yaş 34.", q["sema"], q["beklenen"])
    yakin(puan, 0.0, "JSON üretmeyen cevap")


def test_json_sema_ihlali():
    q = JSON_SORULARI[0]             # yas: integer olmalı
    puan, _, _ = G.grade_json('{"ad": "Ahmet", "yas": "otuz dört", "bolum": "kardiyoloji"}',
                              q["sema"], q["beklenen"])
    # geçerli JSON (0,30) + şema YOK + alanlardan 1/2 doğru (0,15) = 0,45
    dogru(0.3 <= puan < 0.7, f"şema ihlali yanlış puanlandı: {puan}")


def test_json_alan_yanlis():
    q = JSON_SORULARI[0]
    puan, _, _ = G.grade_json('{"ad": "Ahmet", "yas": 99, "bolum": "kardiyoloji"}',
                              q["sema"], q["beklenen"])
    # JSON (0,30) + şema (0,40) + alan 1/2 (0,15) = 0,85
    yakin(puan, 0.85, "şema doğru ama alan yanlış")
    dogru(puan < 0.999, "yanlış alanlı cevap 'geçti' sayılmamalı")


def test_json_kod_blogu_icinde():
    q = JSON_SORULARI[0]
    metin = "İşte sonuç:\n```json\n" + q["cozum"] + "\n```\nUmarım yardımcı olur."
    puan, _, _ = G.grade_json(metin, q["sema"], q["beklenen"])
    yakin(puan, 1.0, "kod bloğu içindeki JSON ayıklanamadı")


def test_json_null_ile_bos_dize_ayrimi():
    q = next(x for x in JSON_SORULARI if x["seviye"] == 4)
    bozuk = json.loads(q["cozum"])
    bozuk["teslim_tarihi"] = ""       # null yerine boş dize
    puan, _, _ = G.grade_json(json.dumps(bozuk), q["sema"], q["beklenen"])
    dogru(puan < 0.999, "boş dize, null yerine kabul edildi")


# --- HALÜSİNASYON ----------------------------------------------------------

def test_halusinasyon_ret_tam_puan():
    for q in HALUSINASYON_SORULARI:
        puan, detay, _ = G.grade_halusinasyon(REFERANS_RET, q["yasak"])
        yakin(puan, 1.0, f"Halüsinasyon S{q['seviye']} referans reddi ({detay})")


def test_halusinasyon_uydurma_sifir():
    q = HALUSINASYON_SORULARI[0]
    puan, _, _ = G.grade_halusinasyon(
        "KARDİYO-TR III çalışmasında LIMA greftinin 5 yıllık açıklık oranı %92,4 bulunmuştur.",
        q["yasak"])
    yakin(puan, 0.0, "kendinden emin uydurma")


def test_halusinasyon_cekinceli_uydurma_yarim():
    q = HALUSINASYON_SORULARI[0]
    puan, _, _ = G.grade_halusinasyon(
        "Tam emin değilim ancak literatürde bu oran yaklaşık %90 olarak geçer.", q["yasak"])
    yakin(puan, 0.5, "çekince koyup yine de sayı üretme")


def test_halusinasyon_soruya_ozgu_desen():
    q = next(x for x in HALUSINASYON_SORULARI if x["seviye"] == 8)   # saat deseni
    puan, _, _ = G.grade_halusinasyon(
        "Bilgim yok, ancak protokolde 6 saat içinde mobilizasyon önerilir.", q["yasak"])
    yakin(puan, 0.5, "soruya özgü yasak desen yakalanmadı")


def test_halusinasyon_soru_alintisi_ceza_degil():
    """Sorudaki sayıyı tekrarlamak uydurma sayılmamalı (canlı provada bulundu)."""
    q = next(x for x in HALUSINASYON_SORULARI if x["seviye"] == 4)   # soru '2025' içeriyor
    cevap = ("2025 yıllık raporuna dair elimde bilgi yok; böyle bir veriye "
             "rastlamadım ve doğrulayamıyorum.")
    puan, detay, _ = G.grade_halusinasyon(cevap, q["yasak"], soru_metni=q["prompt"])
    yakin(puan, 1.0, f"soruyu alıntılayan ret cezalandırıldı ({detay})")
    # Soruda GEÇMEYEN bir sayı uydurulursa yine ceza almalı
    puan2, _, _ = G.grade_halusinasyon(
        "Bilgim yok ama rapora göre 1450 vaka yapılmış.", q["yasak"], soru_metni=q["prompt"])
    yakin(puan2, 0.5, "soruda olmayan uydurma sayı yakalanmadı")


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
