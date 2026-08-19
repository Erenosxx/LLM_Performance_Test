# -*- coding: utf-8 -*-
"""Uzun bağlam branşı.

Bugüne kadar hiç ölçülmeyen eksen. Dört model de 262k native context
destekliyor (18 Ağu 2026'da config.json'lardan doğrulandı) ama tek 24 GB
kartta erişilebilen tavan modele göre değişir — o tavan da bir yetenek
metriğidir.

BELGELER PROGRAMATİK ÜRETİLİR: dış veri yok, PII yok, cevap kesin bilinir ve
tohum sabit olduğu için her koşuda BİREBİR aynı belge çıkar. Böylece ölçüm
tekrarlanabilir kalır.

Üç görev tipi:
  igne     — tek olgu belgenin %10/%50/%90 derinliğine gömülür (konum etkisi)
  celiski  — aynı olgu iki yerde FARKLI verilir; model çelişkiyi yakalamalı
  sentez   — cevap üç ayrı bölümdeki olgunun birleştirilmesini gerektirir

Puanlama `talimat` grader'ı ile yapılır (katı tek satırlık biçim), böylece
yeni bir grader'a gerek kalmaz ve denetim tamamen mekaniktir.
"""

# Dolgu metni: tıbbi rapor havası veren, olgu İÇERMEYEN cümleler.
# Deterministik seçim için indeksle döndürülür (rastgelelik YOK).
_DOLGU = [
    "Servis hemşiresi vital bulguları rutin aralıklarla kaydetti.",
    "Hasta yakınlarına taburculuk süreci hakkında bilgi verildi.",
    "Yatak başı monitörizasyon kesintisiz sürdürüldü.",
    "Sabah viziti sırasında genel durum stabil olarak değerlendirildi.",
    "Laboratuvar istemleri sistem üzerinden tekrarlandı.",
    "Fizyoterapi ekibi mobilizasyon programını gözden geçirdi.",
    "Beslenme ünitesi diyet planını güncelledi.",
    "Enfeksiyon kontrol komitesi el hijyeni denetimini tamamladı.",
    "Malzeme deposundan istenen sarf ürünleri teslim alındı.",
    "Nöbet devir teslimi eksiksiz biçimde yapıldı.",
    "Radyoloji randevusu planlanan saatte gerçekleşti.",
    "Hasta dosyası arşiv birimine bildirildi.",
]


# ÖLÇÜLDÜ (18 Ağu 2026, Qwen3.8 tokenizer'ı, /tokenize ucu ile): Türkçe tıbbi
# metinde 2,50 token/kelime. İlk tahmin 1,4'tü ve %44 düşüktü — bu yüzden 48k
# token'lık bir soru "sığar" sanılıp sunucuya gönderildi ve hata aldı.
# Dört belgede de oran 2,49-2,50 çıktı, yani sabit güvenilir.
TOKEN_KELIME_ORANI = 2.55          # küçük emniyet payı eklendi
CEVAP_BUTCESI = 512                # bu branşta cevap tek satır; fazlası gereksiz


def _dolgu_paragraf(indeks, cumle=6):
    """Deterministik dolgu paragrafı (tohum = indeks)."""
    return " ".join(_DOLGU[(indeks * 7 + i * 5) % len(_DOLGU)] for i in range(cumle))


def _belge(hedef_kelime, olgular, baslik="VAKA İZLEM KAYITLARI"):
    """Verilen olguları belirtilen derinliklere gömerek belge üretir.

    olgular: [(oran, metin), ...]  oran 0.0-1.0 arası derinlik.
    Belge yaklaşık `hedef_kelime` kelime olur (token ≈ 2,5 × kelime — ölçüldü).
    """
    paragraf_kelime = len(_dolgu_paragraf(0).split())
    toplam_paragraf = max(4, hedef_kelime // max(1, paragraf_kelime))
    yerlesim = {}
    for oran, metin in olgular:
        idx = min(toplam_paragraf - 1, max(0, int(toplam_paragraf * oran)))
        while idx in yerlesim:            # çakışma olursa bir alta kay
            idx += 1
        yerlesim[idx] = metin
    parcalar = [f"{baslik}\n"]
    for i in range(toplam_paragraf):
        parcalar.append(f"[Kayıt {i + 1:03d}] " + _dolgu_paragraf(i))
        if i in yerlesim:
            parcalar.append(f"[Kayıt {i + 1:03d}-EK] {yerlesim[i]}")
    return "\n\n".join(parcalar)


_BICIM = ("\n\nYanıtını TEK SATIR olarak, tam olarak şu biçimde ver "
          "(açıklama ekleme):\nSONUC=<değer>")


def _igne(seviye, kademe, kelime, derinlik, deger, soru):
    """Tek olgu, belirli derinliğe gömülü."""
    olgu = f"Hastanın kayıtlı protokol numarası {deger} olarak doğrulandı."
    belge = _belge(kelime, [(derinlik, olgu)])
    return {
        "seviye": seviye, "kademe": kademe, "tur": "igne",
        "hedef_kelime": kelime, "derinlik": derinlik,
        "prompt": belge + f"\n\nSORU: {soru}" + _BICIM,
        "kisitlar": [("regex_var", rf"^SONUC=\s*{deger}\s*$")],
        "cozum": f"SONUC={deger}",
    }


def _celiski(seviye, kademe, kelime):
    """Aynı olgu iki yerde farklı; model çelişkiyi bildirmeli."""
    belge = _belge(kelime, [
        (0.15, "Hastanın yatış tarihi 12 Mart olarak kaydedildi."),
        (0.80, "Hastanın yatış tarihi 19 Mart olarak kaydedildi."),
    ])
    return {
        "seviye": seviye, "kademe": kademe, "tur": "celiski",
        "hedef_kelime": kelime, "derinlik": None,
        "prompt": (belge + "\n\nSORU: Belgede yatış tarihi kaç farklı değerle "
                           "geçiyor? Yalnız SAYI yaz." + _BICIM),
        "kisitlar": [("regex_var", r"^SONUC=\s*2\s*$")],
        "cozum": "SONUC=2",
    }


def _sentez(seviye, kademe, kelime):
    """Cevap üç ayrı olgunun birleştirilmesini gerektirir."""
    belge = _belge(kelime, [
        (0.10, "Birinci vakada kullanılan sütür sayısı 4 olarak kaydedildi."),
        (0.50, "İkinci vakada kullanılan sütür sayısı 7 olarak kaydedildi."),
        (0.90, "Üçüncü vakada kullanılan sütür sayısı 5 olarak kaydedildi."),
    ])
    return {
        "seviye": seviye, "kademe": kademe, "tur": "sentez",
        "hedef_kelime": kelime, "derinlik": None,
        "prompt": (belge + "\n\nSORU: Üç vakada kullanılan toplam sütür sayısı "
                           "kaçtır? Yalnız SAYI yaz." + _BICIM),
        "kisitlar": [("regex_var", r"^SONUC=\s*16\s*$")],
        "cozum": "SONUC=16",
    }


# Kademe merdiveni (ölçülmüş token karşılıkları):
#   S1  ~8k    S2/S3 ~23k    S4 ~50k    S5/S6 ~89k
# S5/S6 ilk hâlinde ~99k idi ve Qwen'lerin ölçülen 98304 tavanına 500 token
# kalıyordu; 36k kelimeye indirildi ki dört modelden üçünde ölçülebilsin.
# 32k bağlamlı bir modelde ilk üçü koşar, kalanı "bağlam yetersiz" olarak
# ATLANIR (puan None) — yetenek eksikliğiyle donanım sınırı karışmasın diye.
# Modele KV kuantizasyonuyla 64k verilirse S4 kendiliğinden devreye girer.
UZUN_BAGLAM_SORULARI = [
    _igne(1, "kolay", 3000, 0.50, "48217",
          "Hastanın kayıtlı protokol numarası kaçtır?"),
    _igne(2, "orta", 9000, 0.90, "73914",
          "Hastanın kayıtlı protokol numarası kaçtır?"),
    _celiski(3, "zor", 9000),
    _sentez(4, "zor", 20000),
    _igne(5, "acımasız", 36000, 0.10, "55082",
          "Hastanın kayıtlı protokol numarası kaçtır?"),
    _sentez(6, "acımasız", 36000),
]
