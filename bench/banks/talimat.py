# -*- coding: utf-8 -*-
"""Talimata uyma branşı.

Modelin ZEKÂSINI değil, DİSİPLİNİNİ ölçer: bileşik kısıtlara harfiyen uyma.
IFBench'te modeller arasındaki en büyük farklardan biri bu eksende çıkıyor
(Qwen3.8 79,5 · Qwen3.6 69,1 · Opus4.6 Max 62,5).

Her soru:
    kisitlar : [(tip, param), ...]  -> bench/graders.py denetler
    cozum    : tüm kısıtları sağlayan referans cevap (selftest bunu kullanır)

KURAL: her kısıt makineyle denetlenebilir olmalı. "Akıcı yaz" gibi bir kısıt
buraya giremez — o yaratıcılık branşının işi.
"""

TALIMAT_SORULARI = [
    {
        "seviye": 1, "kademe": "kolay",
        "prompt": "Tam 3 madde yaz. Her madde tek satır olsun. Hiçbir maddede 've' "
                  "bağlacı geçmesin. Başlık, giriş cümlesi veya açıklama EKLEME.",
        "kisitlar": [("madde_sayisi", 3), ("yasak_kelime", "ve"),
                     ("regex_yok", r"```")],
        "cozum": "- Sabah erken kalkmak\n- Düzenli su içmek\n- Kısa yürüyüş yapmak",
    },
    {
        "seviye": 2, "kademe": "orta",
        "prompt": "Tam 5 madde yaz. Her madde 'K' harfiyle başlasın. Hiçbir maddede "
                  "sayı kullanma. Açıklama veya başlık ekleme.",
        "kisitlar": [("madde_sayisi", 5), ("harf_basi", "K"), ("regex_yok", r"\d")],
        "cozum": "- Kalem\n- Kitap\n- Kapı\n- Kutu\n- Kuş",
    },
    {
        "seviye": 3, "kademe": "orta",
        "prompt": "Cevabın TAMAMI en fazla 20 kelime olsun ve 'çünkü' sözcüğü mutlaka "
                  "geçsin. Tek paragraf yaz, madde işareti kullanma.",
        "kisitlar": [("kelime_en_fazla", 20), ("zorunlu_kelime", "çünkü"),
                     ("regex_yok", r"^\s*[-*•]")],
        "cozum": "Erken yatmak faydalıdır çünkü uyku düzeni bağışıklığı güçlendirir ve "
                 "ertesi günkü dikkati belirgin biçimde artırır.",
    },
    {
        "seviye": 4, "kademe": "zor",
        "prompt": "Tam 4 madde yaz. Maddeleri EN UZUNDAN EN KISAYA doğru sırala "
                  "(kelime sayısına göre). Hiçbir maddede 'bir' sözcüğü geçmesin. "
                  "Her madde en fazla 8 kelime olsun. Açıklama ekleme.",
        "kisitlar": [("madde_sayisi", 4), ("uzundan_kisaya", None),
                     ("yasak_kelime", "bir"), ("her_madde_kelime_en_fazla", 8)],
        "cozum": ("- Sabah saatlerinde düzenli olarak kısa yürüyüş yapmak\n"
                  "- Akşam yemeğini erken saatte tamamlamak\n"
                  "- Gün içinde yeterince su içmek\n"
                  "- Ekranlardan uzak durmak"),
    },
    {
        "seviye": 5, "kademe": "zor",
        "prompt": "Aşağıdaki cümleyi TAMAMEN BÜYÜK HARFLE yeniden yaz, sonuna ünlem "
                  "işareti koy, 'hastane' sözcüğünü 'klinik' ile değiştir ve başka "
                  "hiçbir şey yazma:\n"
                  "hasta sabah hastane bahçesinde yürüyüş yaptı",
        "kisitlar": [("tumu_buyuk", None), ("son_karakter", "!"),
                     ("zorunlu_kelime", "KLİNİK"), ("yasak_kelime", "hastane"),
                     ("satir_sayisi", 1)],
        "cozum": "HASTA SABAH KLİNİK BAHÇESİNDE YÜRÜYÜŞ YAPTI!",
    },
    {
        "seviye": 6, "kademe": "zor",
        "prompt": "Tam 6 madde yaz. Tek sayılı maddeler (1., 3., 5.) 'A' harfiyle, "
                  "çift sayılı maddeler (2., 4., 6.) 'B' harfiyle başlasın — yani "
                  "sırayla A, B, A, B, A, B. Numaralandırma kullan (1., 2., ...). "
                  "Hiçbir maddede noktalama işareti kullanma.",
        "kisitlar": [("madde_sayisi", 6),
                     ("regex_var", r"1[.)]\s*A"), ("regex_var", r"2[.)]\s*B"),
                     ("regex_var", r"3[.)]\s*A"), ("regex_var", r"4[.)]\s*B"),
                     ("regex_var", r"5[.)]\s*A"), ("regex_var", r"6[.)]\s*B")],
        "cozum": ("1. Armut\n2. Balık\n3. Ayva\n4. Bulut\n5. Ağaç\n6. Bardak"),
    },
    {
        "seviye": 7, "kademe": "zor",
        "prompt": "En az 40, en fazla 60 kelimelik tek bir paragraf yaz. Konu: "
                  "ameliyathane hazırlığı. İçinde 'steril' sözcüğü geçsin, "
                  "'ameliyat' sözcüğü HİÇ geçmesin. Madde işareti kullanma.",
        "kisitlar": [("kelime_en_az", 40), ("kelime_en_fazla", 60),
                     ("zorunlu_kelime", "steril"), ("yasak_kelime", "ameliyat"),
                     ("regex_yok", r"^\s*[-*•]")],
        "cozum": ("Girişim öncesinde ekip, salonun havalandırmasını ve masa yüzeylerini "
                  "denetler. Kullanılacak tüm malzemeler steril paketlerde getirilir ve "
                  "paket bütünlüğü tek tek kontrol edilir. Ekip üyeleri el yıkama "
                  "protokolünü uygular, önlük ve eldiven giyer. Hasta pozisyonu "
                  "verildikten sonra cilt antisepsisi tamamlanır ve örtüler serilir. "
                  "Sayım işlemi başlamadan önce eksiksiz yapılır."),
    },
    {
        "seviye": 8, "kademe": "acımasız",
        "prompt": "Tam 5 madde yaz. Her madde tam olarak 4 kelime olsun. Maddeler "
                  "alfabetik sırada olsun. Hiçbir maddede 'e' harfi geçmesin. "
                  "Madde işareti olarak yalnız tire (-) kullan. Açıklama ekleme.",
        "kisitlar": [("madde_sayisi", 5), ("her_madde_kelime_en_fazla", 4),
                     ("regex_yok", r"[eE]"), ("regex_var", r"^\s*-\s"),
                     ("uzundan_kisaya", None)],
        "cozum": ("- Ali balık tuttu bugün\n- Barış kumaş sattı hızlı\n"
                  "- Cana su taşıdı dun\n- Duru masa boyadı yavaş\n"
                  "- Fatma çorap ördü mavi"),
    },
    {
        "seviye": 9, "kademe": "acımasız",
        "prompt": "Aşağıdaki listeyi kelime sayısına göre AZALAN sırada yeniden yaz. "
                  "Tam 4 madde olsun, her madde tire ile başlasın, hiçbir maddede "
                  "rakam kullanma ve toplam cevabın 30 kelimeyi geçmesin:\n"
                  "kalp, açık kalp cerrahisi sonrası bakım, damar, koroner arter baypas",
        "kisitlar": [("madde_sayisi", 4), ("uzundan_kisaya", None),
                     ("regex_yok", r"\d"), ("kelime_en_fazla", 30),
                     ("regex_var", r"^\s*-\s")],
        "cozum": ("- açık kalp cerrahisi sonrası bakım\n- koroner arter baypas\n"
                  "- damar\n- kalp"),
    },
    {
        "seviye": 10, "kademe": "acımasız",
        "prompt": "Cevabını TAM OLARAK şu biçimde ver, fazladan hiçbir şey yazma:\n"
                  "SONUC: <sayı>\nGEREKCE: <en fazla 10 kelime>\n"
                  "Soru: 17 ile 43'ün toplamının 3 katı kaçtır?",
        "kisitlar": [("satir_sayisi", 2), ("regex_var", r"^SONUC:\s*180\s*$"),
                     ("regex_var", r"^GEREKCE:"), ("kelime_en_fazla", 16),
                     ("regex_yok", r"```")],
        "cozum": "SONUC: 180\nGEREKCE: Toplam altmış, üç katı yüz seksen",
    },
    # --- ACIMASIZ+ kademe -----------------------------------------------
    # 18 Ağu 2026 canlı provasında Qwen3.8 10/10, Gemma 4 9/10 aldı: branş
    # doygundu. Aşağıdaki üç soru modelin KENDİ ÇIKTISINI SAYMASINI gerektirir
    # (kelime artışı, baş harf dizisi, karakter bütçesi) — dil modelleri için
    # gerçekten zor, denetimi ise tamamen mekanik.
    {
        "seviye": 11, "kademe": "acımasız",
        "prompt": "Tam 4 madde yaz. İlk madde tam 3 kelime olsun; her madde bir "
                  "öncekinden TAM 2 kelime uzun olsun. Madde işareti olarak tire "
                  "kullan. Açıklama ekleme.",
        "kisitlar": [("madde_sayisi", 4), ("ilk_madde_kelime", 3),
                     ("kelime_artisi", 2), ("regex_var", r"^\s*-\s")],
        "cozum": ("- Sabah yürüyüşü yaptım\n"
                  "- Akşam kitap okudum uzun süre\n"
                  "- Hafta sonu arkadaşlarla birlikte kahve içtik dışarıda\n"
                  "- Yaz tatilinde ailemle beraber uzun bir yolculuğa çıkmayı istiyorum"),
    },
    {
        "seviye": 12, "kademe": "acımasız",
        "prompt": "Tam 5 madde yaz. Maddelerin baş harfleri SIRAYLA B, D, K, M, T "
                  "olsun. Her madde tam 3 kelime olsun. Hiçbir maddede 'a' harfi "
                  "geçmesin. Tire ile başlat, açıklama ekleme.",
        "kisitlar": [("madde_sayisi", 5), ("bas_harfler", "BDKMT"),
                     ("her_madde_kelime_tam", 3), ("regex_yok", r"[aA]"),
                     ("regex_var", r"^\s*-\s")],
        "cozum": ("- Bilgi üretmek zordur\n- Değer bulmuş görünüyor\n"
                  "- Kültür bizim köprümüz\n- Müzik güzeldir hep\n"
                  "- Temiz gönül şendir"),
    },
    {
        "seviye": 13, "kademe": "acımasız",
        "prompt": "Şu sayıların medyanını bul: 12, 7, 19, 4, 23, 15. Cevabını TEK "
                  "SATIRDA, hiç boşluk kullanmadan ve tam olarak şu biçimde ver:\n"
                  "MEDYAN=<sayı>|ADET=<kaç sayı vardı>|KAYNAK=verilen",
        "kisitlar": [("satir_sayisi", 1),
                     ("regex_var", r"^MEDYAN=13\.5\|ADET=6\|KAYNAK=verilen$"),
                     ("regex_yok", r"\s"), ("toplam_karakter_en_fazla", 40)],
        "cozum": "MEDYAN=13.5|ADET=6|KAYNAK=verilen",
    },
]
