# -*- coding: utf-8 -*-
"""Türkçe tıbbi terim yetkinliği branşı.

KAYNAK: Sorular uydurulmadı — TÜBİTAK WP6 değerlendirmesindeki GERÇEK Whisper
ASR bozulmalarından türetildi (`TUBITAK_WP6_eval/frozen/reference_fixes.json`,
11 Ağu 2026'da elle küratörlenmiş 58 düzeltme + reddedilen adaylar listesi).

İki tür soru var ve ikincisi daha ayırt edici:

  1) DÜZELTME  — gerçekten bozuk terim ("intertorakal" diye bir terim yok).
     Ölçülen: model doğru terimi biliyor mu?

  2) DOKUNMAMA — her iki biçim de meşru ("miyokart" Türk tıp yazınında
     kullanılıyor) ya da konuşma dili sadık transkripsiyon ("nerden").
     Ölçülen: model gereksiz "düzeltme" yapmaktan KAÇINABİLİYOR mu?

İkinci tür, WP6 ölçümünün en kritik bulgusuyla doğrudan ilgili: aşırı düzeltme
kritik terim bozulmasına yol açıyor. Orada Qwen3.8'in kritik bozma oranı
diğerlerinin onda biriydi; bu branş o davranışı doğrudan ölçer.

BİÇİM: hepsi tek satırlık katı çıktı ister -> tamamen mekanik denetim.
"""

_BICIM = ("\n\nYanıtını TEK SATIR olarak, tam olarak şu biçimde ver "
          "(açıklama ekleme):\nSONUC=<terim>\n"
          "Terim zaten doğruysa veya iki biçim de geçerliyse: SONUC=DEGISIKLIK_YOK")


def _duzeltme(seviye, kademe, bozuk, dogru, baglam, gerekce, kabul=()):
    """Gerçekten bozuk bir terim -> doğru biçimi bekleriz."""
    secenekler = "|".join([dogru] + list(kabul))
    return {
        "seviye": seviye, "kademe": kademe, "tur": "düzeltme", "gerekce": gerekce,
        "prompt": (f"Aşağıdaki cümle bir ses kaydından otomatik yazıya çevrilmiştir. "
                   f"Altı çizili terim doğru mu, değilse doğrusu nedir?\n"
                   f"\"{baglam}\"\nİncelenen terim: {bozuk}" + _BICIM),
        # TEK kısıt: doğru terim. Biçim kısıtı bilerek eklenmedi — eklenirse
        # terimi bilmeyen ama biçime uyan model yarım puan alır ve branş
        # %50 tabandan başlar (ölçüm gücü yarıya iner).
        "kisitlar": [("regex_var", rf"^SONUC=\s*({secenekler})\s*$")],
        "cozum": f"SONUC={dogru}",
    }


def _dokunma(seviye, kademe, terim, baglam, gerekce):
    """Meşru biçim -> model DEĞİŞTİRMEMELİ."""
    return {
        "seviye": seviye, "kademe": kademe, "tur": "dokunmama", "gerekce": gerekce,
        "prompt": (f"Aşağıdaki cümle bir ses kaydından otomatik yazıya çevrilmiştir. "
                   f"Altı çizili terim doğru mu, değilse doğrusu nedir?\n"
                   f"\"{baglam}\"\nİncelenen terim: {terim}" + _BICIM),
        "kisitlar": [("regex_var", r"^SONUC=\s*DEGISIKLIK_YOK\s*$")],
        "cozum": "SONUC=DEGISIKLIK_YOK",
    }


TURKCE_SORULARI = [
    # --- 1) GERÇEK BOZULMALAR ---------------------------------------------
    _duzeltme(1, "kolay", "grafı", "grafi",
              "akciğer grafı çekildi ve değerlendirildi",
              "Noktasız ı artefaktı: Latince kökenli terimde 'i' yerine 'ı'."),
    _duzeltme(2, "orta", "biluribin", "bilirubin",
              "total biluribin değeri yüksek bulundu",
              "Harf sırası bozuk (bilirubin)."),
    _duzeltme(3, "orta", "anostomoz", "anastomoz",
              "uç uca anostomoz yapıldı",
              "Stoma kökü: anastomoz."),
    _duzeltme(4, "zor", "intertorakal", "interkostal",
              "intertorakal aralıktan girildi",
              "'intertorakal' diye bir terim yok; kastedilen interkostal."),
    _duzeltme(5, "zor", "flouroskopi", "floroskopi",
              "işlem flouroskopi eşliğinde yapıldı",
              "Fazla u: floroskopi."),
    _duzeltme(6, "zor", "batum", "batın", "hasta batum ağrısıyla başvurdu",
              "Cerrahi bağlamda 'batın' (abdomen); 'batum' şehir adı — bağlam gerektirir."),
    _duzeltme(7, "acımasız", "deferans", "deferens",
              "ductus deferans korundu",
              "Latince ductus deferens; Türkçeleştirme tuzağı."),
    # --- 2) DOKUNMAMA (asıl ayırt edici) -----------------------------------
    _dokunma(8, "zor", "miyokart", "miyokart enfarktüsü öyküsü var",
             "Türk tıp yazınında 'miyokart' da kullanılıyor; tek doğru biçim iddia edilemez. "
             "WP6'da bu düzeltme REDDEDİLDİ."),
    _dokunma(9, "zor", "infeksiyon", "yara yerinde infeksiyon gelişmedi",
             "'infeksiyon' Türk tıp yazınında kabul gören varyant."),
    _dokunma(10, "acımasız", "nerden", "hasta nerden geldiğini hatırlamıyordu",
             "Konuşma dili transkripti; 'nereden'e çevirmek sadakat ihlalidir. "
             "WP6 kuralı: konuşma dili DÜZELTİLMEZ."),
]
