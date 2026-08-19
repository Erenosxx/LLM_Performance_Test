# -*- coding: utf-8 -*-
"""Koşu sonuçlarının diske yazılması ve geri okunması.

NEDEN: 17 Ağustos koşusunda ham sonuçlar hiçbir yere yazılmamıştı; hangi
sorunun hangi modeli ayırdığını bulmak için PDF'leri metne çevirip ayrıştırmak
gerekti. Artık her koşu `sonuclar.json` bırakır — madde analizi, yeniden
puanlama ve karşılaştırma modelleri yeniden çalıştırmadan yapılabilir.

Yazılan dosya PDF'in yerini almaz, yanında durur.
"""

import json
import os

DOSYA_ADI = "sonuclar.json"
SURUM = 1

# Kayda giren alanlar. Soru metni ve model cevabı KASITLI olarak dışarıda:
# dosya küçük ve karşılaştırma amaçlı kalsın (cevaplar PDF'te zaten var).
SORU_ALANLARI = ("key", "baslik", "kategori", "kademe", "seviye")
SONUC_ALANLARI = ("puan", "passed", "kararlilik", "kesildi", "grade_detail",
                  "total", "ttft", "completion_tokens", "tokens_per_sec")


def _sadelestir(sonuc):
    kayit = {a: sonuc.get(a) for a in SORU_ALANLARI}
    for a in SONUC_ALANLARI:
        if a in sonuc:
            kayit[a] = sonuc[a]
    if isinstance(kayit.get("grade_detail"), str):
        kayit["grade_detail"] = kayit["grade_detail"][:200]
    ag = sonuc.get("agentic_info")
    if ag:
        kayit["agentic_info"] = ag
    return kayit


def yaz(kok_dizin, records, run_meta):
    """Koşu sonuçlarını `<kok_dizin>/sonuclar.json` olarak yazar -> dosya yolu."""
    veri = {
        "surum": SURUM,
        "kosu": run_meta,
        "modeller": [
            {
                "ad": r.get("name"),
                "dosya": r.get("file"),
                "ok": r.get("ok"),
                "hata": r.get("error"),
                "ctx": r.get("ctx"),
                "max_tokens": r.get("max_tokens"),
                "params": r.get("params") or {},
                "profil": r.get("profil") or {},
                "vram_peak_delta": r.get("vram_peak_delta"),
                "sonuclar": [_sadelestir(s) for s in (r.get("results") or [])],
            }
            for r in records
        ],
    }
    yol = os.path.join(kok_dizin, DOSYA_ADI)
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
    return yol


def oku(yol):
    """`sonuclar.json` (ya da onu içeren klasör) -> veri sözlüğü."""
    if os.path.isdir(yol):
        yol = os.path.join(yol, DOSYA_ADI)
    with open(yol, encoding="utf-8") as f:
        return json.load(f)


def model_sonuclari(veri):
    """madde_analizi() için {model_adı: [sonuç, ...]} biçimine indirger."""
    return {m["ad"]: m["sonuclar"] for m in veri.get("modeller", [])
            if m.get("ok") and m.get("sonuclar")}
