#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bir koşunun soruları modelleri gerçekten ayırıyor mu?

Kullanım:
    python madde_analizi.py Model_raporları/calisma_20260818_101500
    python madde_analizi.py <klasör> --hepsi        # ayırt etmeyenleri de listele
    python madde_analizi.py <klasör> --csv rapor.csv

Testin kendi bakımını söylemesi için var: bir soruyu dört model de geçiyorsa
o soru ölçüm yapmıyor demektir, emekliye ayrılmalı ya da zorlaştırılmalıdır.
(17 Ağustos 2026 koşusunda 80 sorunun 74'ü bu durumdaydı — bu araç o analizi
elle PDF ayrıştırmadan yapar.)
"""

import argparse
import csv
import os
import sys

from bench import kayit as KAYIT
from bench import scoring as SCORE


def main():
    ap = argparse.ArgumentParser(description="Koşu sonuçlarının madde (soru) analizi.")
    ap.add_argument("kosu", help="koşu klasörü ya da sonuclar.json yolu")
    ap.add_argument("--hepsi", action="store_true", help="ayırt etmeyen soruları da listele")
    ap.add_argument("--csv", metavar="DOSYA", help="analizi CSV olarak yaz")
    args = ap.parse_args()

    try:
        veri = KAYIT.oku(args.kosu)
    except FileNotFoundError:
        sys.exit(f"HATA: {KAYIT.DOSYA_ADI} bulunamadı: {args.kosu}\n"
                 f"  → yalnız 18 Ağustos 2026'dan sonraki koşularda var; "
                 f"eski koşularda ham sonuç kaydedilmiyordu.")

    ms = KAYIT.model_sonuclari(veri)
    if len(ms) < 2:
        sys.exit(f"HATA: ayrım hesabı için en az 2 başarılı model gerekir (bulunan: {len(ms)}).")

    analiz = SCORE.madde_analizi(ms)
    ozet = SCORE.analiz_ozeti(analiz)
    modeller = list(ms)

    print(f"Koşu     : {args.kosu}")
    print(f"Modeller : {', '.join(modeller)}")
    print(f"Sorular  : {ozet['toplam']} puanlı")
    print(f"Ayırt eden: {ozet['ayirt_eden']} (%{ozet['oran']})   "
          f"Emeklilik adayı: {ozet['emeklilik_adayi']}\n")

    bas = f"{'soru':<40}{'kademe':<10}{'yayılım':>8}  " + "".join(f"{m[:16]:>17}" for m in modeller)
    print(bas)
    print("-" * len(bas))
    for a in analiz:
        if not args.hepsi and not a["ayirt_ediyor"]:
            continue
        satir = f"{a['baslik'][:38]:<40}{(a['kademe'] or '-'):<10}{a['yayilim']:>8.2f}  "
        satir += "".join(f"{a['puanlar'].get(m, float('nan')):>17.2f}" for m in modeller)
        print(satir)

    if not args.hepsi:
        print(f"\n(ayırt etmeyen {ozet['toplam'] - ozet['ayirt_eden']} soru gizlendi — --hepsi ile görülür)")

    emekli = [a for a in analiz if a["emeklilik_adayi"]]
    if emekli:
        print(f"\nEMEKLİLİK ADAYLARI ({len(emekli)}): hiçbir ayrım üretmiyor")
        gecti = [a["baslik"] for a in emekli if a["herkes_gecti"]]
        kaldi = [a["baslik"] for a in emekli if a["herkes_kaldi"]]
        if gecti:
            print(f"  herkes geçti ({len(gecti)}): {', '.join(g[:26] for g in gecti[:12])}"
                  f"{' …' if len(gecti) > 12 else ''}")
        if kaldi:
            print(f"  herkes kaldı ({len(kaldi)}): {', '.join(k[:26] for k in kaldi[:12])}"
                  f"{' …' if len(kaldi) > 12 else ''}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["key", "baslik", "kategori", "kademe", "yayilim", "ortalama", "sapma",
                        "ayirt_ediyor", "emeklilik_adayi"] + modeller)
            for a in analiz:
                w.writerow([a["key"], a["baslik"], a["kategori"], a["kademe"], a["yayilim"],
                            a["ortalama"], a["sapma"], int(a["ayirt_ediyor"]),
                            int(a["emeklilik_adayi"])] +
                           [a["puanlar"].get(m, "") for m in modeller])
        print(f"\n✔ CSV: {args.csv}")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) or ".")
    main()
