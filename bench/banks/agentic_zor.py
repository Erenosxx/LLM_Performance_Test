# -*- coding: utf-8 -*-
"""Agentic branşının ZOR kademesi.

NEDEN: Mevcut 11 agentic görevini 17-18 Ağu ölçümlerinde dört model de tam
yaptı (11/11) — yani branş hiç ayrım üretmiyor. Sebep, o görevlerin ARAÇLI
BULMACA olması: araçlar her zaman çalışıyor, hepsi ilgili, çağrı sayısı
serbest ve ortam hiç sürpriz yapmıyor.

Gerçek ajan yeteneği bunlarla ölçülür ve hiçbiri testte yoktu:

    bozuk_arac    ilk çağrıda hata döner, ikincide çalışır -> yeniden deneme
    celdirici     12 araçtan yalnız 3'ü ilgili -> gereksiz çağrı cezası
    butce         en fazla N çağrı -> verimsiz keşif cezalandırılır
    kirli_veri    araç çıktısı kendi içinde çelişkili -> fark etmeli
    uzun_ufuk     çok adımlı, ara durumu hatırlamayı gerektirir

Araç uygulamaları DURUM TUTAR (kaç kez çağrıldı) — bu yüzden her görev için
`sifirla()` çağrılır; `AGENTIC_ZOR_GOREVLER` bir FONKSİYONdur, liste değil,
böylece her koşu temiz durumla başlar.
"""

# --- Görev 1: bozuk araç ----------------------------------------------------
_durum = {"sensor_cagri": 0, "arsiv_cagri": 0, "butce_cagri": 0}


def sifirla():
    for k in _durum:
        _durum[k] = 0


def _sensor_oku(kanal):
    """İlk çağrıda GEÇİCİ hata döner; ikinci çağrıda gerçek değeri verir."""
    _durum["sensor_cagri"] += 1
    if _durum["sensor_cagri"] == 1:
        return {"hata": "SENSOR_MESGUL", "mesaj": "Cihaz meşgul, isteği tekrarlayın."}
    degerler = {1: 36.8, 2: 72.0, 3: 98.0}
    return {"kanal": kanal, "deger": degerler.get(int(kanal), 0.0)}


# --- Görev 2: çeldirici araçlar --------------------------------------------
_ARSIV = {101: {"ad": "kanül", "raf": "A3", "adet": 12},
          102: {"ad": "dren", "raf": "B1", "adet": 5},
          103: {"ad": "sütür", "raf": "A3", "adet": 40}}


def _arsiv_listele():
    _durum["arsiv_cagri"] += 1
    return {"kayitlar": sorted(_ARSIV)}


def _arsiv_oku(kayit_id):
    _durum["arsiv_cagri"] += 1
    return _ARSIV.get(int(kayit_id), {"hata": "YOK"})


def _bos_arac(**kwargs):
    """Çeldirici: her zaman boş döner. Model bunu kullanırsa vakit kaybeder."""
    return {"sonuc": None, "not": "bu araç bu görevle ilgisiz"}


# --- Görev 3: kirli veri ----------------------------------------------------
def _rapor_oku(bolum):
    """İki bölüm AYNI alan için farklı değer verir — model çelişkiyi görmeli."""
    veriler = {
        "ozet": {"toplam_vaka": 18, "kaynak": "özet sayfası"},
        "detay": {"toplam_vaka": 21, "kaynak": "detay tablosu"},
        "imza": {"onaylayan": "başhekim", "tarih": "3 Mart"},
    }
    return veriler.get(str(bolum), {"hata": "BÖLÜM YOK"})


def _tool(ad, aciklama, ozellikler, zorunlu=None):
    return {"type": "function", "function": {
        "name": ad, "description": aciklama,
        "parameters": {"type": "object", "properties": ozellikler,
                       "required": zorunlu or list(ozellikler)}}}


_CELDIRICILER = ["hava_durumu", "doviz_kuru", "takvim_ac", "not_yaz",
                 "eposta_gonder", "cevir", "hesapla_faiz", "sarki_ac", "harita_ac"]


def gorevler():
    """Her çağrıda TEMİZ durumla görev listesi üretir."""
    sifirla()
    celdirici_araclar = [_tool(ad, f"{ad} işlemi yapar.", {"girdi": {"type": "string"}})
                         for ad in _CELDIRICILER]
    celdirici_impl = {ad: _bos_arac for ad in _CELDIRICILER}
    return [
        {"key": "agentic_zor_1", "seviye": 12, "kademe": "zor",
         "baslik": "Agentic S12 (bozuk araç — yeniden deneme)",
         "grader_type": "math", "expected": 72.0,
         "cozum": "sensor_oku(2) ilk çağrıda SENSOR_MESGUL döner; tekrar çağrılınca 72.0 verir. "
                  "Ölçülen: model geçici hatayı görüp yeniden deniyor mu?",
         "user": ("sensor_oku aracı bazen geçici hata döndürür ('SENSOR_MESGUL'). "
                  "2 numaralı kanalın değerini öğren. Hata alırsan aynı çağrıyı TEKRAR dene. "
                  "Sonucu EN SON satırda tam olarak `#### <sayı>` biçiminde ver."),
         "tools": [_tool("sensor_oku", "Bir kanalın ölçüm değerini döndürür. Geçici hata verebilir.",
                         {"kanal": {"type": "integer", "description": "kanal numarası"}})],
         "impls": {"sensor_oku": _sensor_oku}, "sifirla": sifirla},

        {"key": "agentic_zor_2", "seviye": 13, "kademe": "zor",
         "baslik": "Agentic S13 (çeldirici araçlar)",
         "grader_type": "math", "expected": 52.0,
         "cozum": "A3 rafındaki kalemler: kanül 12 + sütür 40 = 52. Diğer 9 araç ilgisiz; "
                  "onları çağırmak verimlilik kaybıdır.",
         "user": ("Elinde çok sayıda araç var ama çoğu bu görevle ilgisiz. "
                  "A3 rafında toplam kaç adet malzeme var? Yalnız gereken araçları kullan. "
                  "Sonucu EN SON satırda tam olarak `#### <sayı>` biçiminde ver."),
         "tools": ([_tool("arsiv_listele", "Tüm kayıt id'lerini döndürür.", {}),
                    _tool("arsiv_oku", "Bir kaydı döndürür: ad, raf, adet.",
                          {"kayit_id": {"type": "integer"}})] + celdirici_araclar),
         "impls": {**{"arsiv_listele": _arsiv_listele, "arsiv_oku": _arsiv_oku},
                   **celdirici_impl}, "sifirla": sifirla},

        {"key": "agentic_zor_3", "seviye": 14, "kademe": "acımasız",
         "baslik": "Agentic S14 (kirli veri — çelişki)",
         "grader_type": "math", "expected": 2.0,
         "cozum": "ozet bölümü toplam_vaka=18, detay bölümü 21 diyor. Model çelişkiyi fark edip "
                  "'2 farklı değer' demeli; tek bir sayıyı doğru kabul ederse kalır.",
         "user": ("rapor_oku aracıyla 'ozet' ve 'detay' bölümlerini oku. Toplam vaka sayısı için "
                  "belgede KAÇ FARKLI değer bulunduğunu söyle (değerin kendisini değil, kaç farklı "
                  "değer olduğunu). Sonucu EN SON satırda tam olarak `#### <sayı>` biçiminde ver."),
         "tools": [_tool("rapor_oku", "Raporun bir bölümünü döndürür: ozet, detay, imza.",
                         {"bolum": {"type": "string", "description": "ozet | detay | imza"}})],
         "impls": {"rapor_oku": _rapor_oku}, "sifirla": sifirla},
    ]
