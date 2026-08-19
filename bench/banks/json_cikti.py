# -*- coding: utf-8 -*-
"""Yapılandırılmış çıktı (JSON şema uyumu) branşı.

Ajan altyapısının temel taşı: model, serbest metinden veri çıkarıp KATI bir
şemaya dökebiliyor mu? Üç aşamalı puanlanır (bkz. bench/graders.grade_json):
geçerli JSON (0,30) + şema uyumu (0,40) + alan değerleri (0,30).

Baskı unsurları kasıtlıdır: veri dağınık verilir, sayı metin içinde geçer,
enum değerleri sınırlıdır, `null` ile boş dize ayrımı sorulur, Türkçe
karakter ve tırnak kaçışı gerekir.
"""

JSON_SORULARI = [
    {
        "seviye": 1, "kademe": "kolay",
        "prompt": ("Aşağıdaki bilgiyi JSON'a çevir. SADECE JSON ver, açıklama yazma.\n"
                   "\"Ahmet Yılmaz 34 yaşında, kardiyoloji bölümünde çalışıyor.\"\n"
                   "Alanlar: ad (metin), yas (tam sayı), bolum (metin)."),
        "sema": {"type": "object", "required": ["ad", "yas", "bolum"],
                 "properties": {"ad": {"type": "string"}, "yas": {"type": "integer"},
                                "bolum": {"type": "string"}}},
        "beklenen": {"yas": 34, "bolum": "kardiyoloji"},
        "cozum": '{"ad": "Ahmet Yılmaz", "yas": 34, "bolum": "kardiyoloji"}',
    },
    {
        "seviye": 2, "kademe": "orta",
        "prompt": ("Metinden JSON üret. SADECE JSON ver.\n"
                   "\"Hasta 3 gün önce yatırıldı. Ateşi yok, öksürüğü var, "
                   "baş ağrısı bildirilmedi.\"\n"
                   "Alanlar: yatis_gun (tam sayı), belirtiler (dizi — yalnız VAR olanlar), "
                   "ates (mantıksal)."),
        "sema": {"type": "object", "required": ["yatis_gun", "belirtiler", "ates"],
                 "properties": {"yatis_gun": {"type": "integer"},
                                "belirtiler": {"type": "array", "items": {"type": "string"}},
                                "ates": {"type": "boolean"}}},
        "beklenen": {"yatis_gun": 3, "ates": False},
        "cozum": '{"yatis_gun": 3, "belirtiler": ["öksürük"], "ates": false}',
    },
    {
        "seviye": 3, "kademe": "orta",
        "prompt": ("SADECE JSON ver. Durum alanı yalnız şu üç değerden biri olabilir: "
                   "\"bekliyor\", \"devam\", \"bitti\".\n"
                   "\"2 numaralı işlem hâlâ sürüyor, sorumlusu Ayşe.\"\n"
                   "Alanlar: islem_no (tam sayı), durum (enum), sorumlu (metin)."),
        "sema": {"type": "object", "required": ["islem_no", "durum", "sorumlu"],
                 "properties": {"islem_no": {"type": "integer"},
                                "durum": {"enum": ["bekliyor", "devam", "bitti"]},
                                "sorumlu": {"type": "string"}}},
        "beklenen": {"islem_no": 2, "durum": "devam", "sorumlu": "Ayşe"},
        "cozum": '{"islem_no": 2, "durum": "devam", "sorumlu": "Ayşe"}',
    },
    {
        "seviye": 4, "kademe": "zor",
        "prompt": ("SADECE JSON ver. Bilinmeyen alanlara boş dize DEĞİL, null yaz.\n"
                   "\"Sipariş 7712, iki kalem içeriyor: 3 adet kanül ve 2 adet dren. "
                   "Teslim tarihi henüz belli değil.\"\n"
                   "Alanlar: siparis_no (tam sayı), teslim_tarihi (metin veya null), "
                   "kalemler (nesne dizisi: ad, adet)."),
        "sema": {"type": "object", "required": ["siparis_no", "teslim_tarihi", "kalemler"],
                 "properties": {
                     "siparis_no": {"type": "integer"},
                     "teslim_tarihi": {"type": ["string", "null"]},
                     "kalemler": {"type": "array", "minItems": 2, "items": {
                         "type": "object", "required": ["ad", "adet"],
                         "properties": {"ad": {"type": "string"}, "adet": {"type": "integer"}}}}}},
        "beklenen": {"siparis_no": 7712, "teslim_tarihi": None,
                     "kalemler.0.adet": 3, "kalemler.1.adet": 2},
        "cozum": ('{"siparis_no": 7712, "teslim_tarihi": null, "kalemler": '
                  '[{"ad": "kanül", "adet": 3}, {"ad": "dren", "adet": 2}]}'),
    },
    {
        "seviye": 5, "kademe": "zor",
        "prompt": ("SADECE JSON ver. Metindeki tırnak işaretlerini JSON içinde doğru "
                   "kaçır.\n"
                   "Cihazın etiketinde \"Model X-3\" yazıyor, seri numarası 44A, "
                   "durumu arızalı.\n"
                   "Alanlar: etiket (metin — tırnaklar dahil: \"Model X-3\"), "
                   "seri (metin), arizali (mantıksal)."),
        "sema": {"type": "object", "required": ["etiket", "seri", "arizali"],
                 "properties": {"etiket": {"type": "string"}, "seri": {"type": "string"},
                                "arizali": {"type": "boolean"}}},
        "beklenen": {"etiket": '"Model X-3"', "seri": "44A", "arizali": True},
        "cozum": '{"etiket": "\\"Model X-3\\"", "seri": "44A", "arizali": true}',
    },
    {
        "seviye": 6, "kademe": "zor",
        "prompt": ("SADECE JSON ver. Toplamı SEN hesapla.\n"
                   "\"Mart ayında 3 hasta 4'er gün, 2 hasta 6'şar gün yattı.\"\n"
                   "Alanlar: ay (metin), hasta_sayisi (tam sayı), "
                   "toplam_yatis_gunu (tam sayı)."),
        "sema": {"type": "object", "required": ["ay", "hasta_sayisi", "toplam_yatis_gunu"],
                 "properties": {"ay": {"type": "string"}, "hasta_sayisi": {"type": "integer"},
                                "toplam_yatis_gunu": {"type": "integer"}}},
        "beklenen": {"hasta_sayisi": 5, "toplam_yatis_gunu": 24},
        "cozum": '{"ay": "Mart", "hasta_sayisi": 5, "toplam_yatis_gunu": 24}',
    },
    {
        "seviye": 7, "kademe": "acımasız",
        "prompt": ("SADECE JSON ver. İç içe yapı ve sıralama önemli: personel listesi "
                   "maaşa göre AZALAN sırada olsun.\n"
                   "\"Kardiyoloji servisinde Veli 32000, Ayşe 41000, Can 27000 maaş alıyor. "
                   "Servis sorumlusu Ayşe.\"\n"
                   "Alanlar: servis (metin), sorumlu (metin), "
                   "personel (nesne dizisi: ad, maas — maaşa göre azalan)."),
        "sema": {"type": "object", "required": ["servis", "sorumlu", "personel"],
                 "properties": {
                     "servis": {"type": "string"}, "sorumlu": {"type": "string"},
                     "personel": {"type": "array", "minItems": 3, "items": {
                         "type": "object", "required": ["ad", "maas"],
                         "properties": {"ad": {"type": "string"}, "maas": {"type": "integer"}}}}}},
        "beklenen": {"sorumlu": "Ayşe", "personel.0.ad": "Ayşe", "personel.0.maas": 41000,
                     "personel.1.maas": 32000, "personel.2.maas": 27000},
        "cozum": ('{"servis": "Kardiyoloji", "sorumlu": "Ayşe", "personel": '
                  '[{"ad": "Ayşe", "maas": 41000}, {"ad": "Veli", "maas": 32000}, '
                  '{"ad": "Can", "maas": 27000}]}'),
    },
    {
        "seviye": 8, "kademe": "acımasız",
        "prompt": ("SADECE JSON ver. Metinde ÇELİŞKİ var; çelişkiyi tespit edip "
                   "`celiski` alanına true yaz ve çelişen alanı `celiskili_alan` "
                   "olarak bildir.\n"
                   "\"Ameliyat 14:00'te başladı ve 90 dakika sürdü. Kayıtlara göre "
                   "16:00'da bitmiş.\"\n"
                   "Alanlar: baslangic (metin \"14:00\"), sure_dk (tam sayı), "
                   "celiski (mantıksal), celiskili_alan (metin)."),
        "sema": {"type": "object",
                 "required": ["baslangic", "sure_dk", "celiski", "celiskili_alan"],
                 "properties": {"baslangic": {"type": "string"}, "sure_dk": {"type": "integer"},
                                "celiski": {"type": "boolean"},
                                "celiskili_alan": {"type": "string"}}},
        "beklenen": {"baslangic": "14:00", "sure_dk": 90, "celiski": True},
        "cozum": ('{"baslangic": "14:00", "sure_dk": 90, "celiski": true, '
                  '"celiskili_alan": "bitis_saati"}'),
    },
    # --- ACIMASIZ+ kademe -------------------------------------------------
    # 18 Ağu 2026 canlı provasında iki model de 8/8 aldı: branş doygundu.
    # Bu üçü fazladan alan yasağı (additionalProperties: false), türetilmiş
    # alan hesabı, çelişki çözümü ve birim dönüşümü gerektirir.
    {
        "seviye": 9, "kademe": "acımasız",
        "prompt": ("SADECE JSON ver. ŞEMADA OLMAYAN HİÇBİR ALAN EKLEME. "
                   "`toplam_tutar` alanını kalemlerden SEN hesapla.\n"
                   "\"Fatura 991: 4 adet kanül (birim 150 TL), 3 adet dren "
                   "(birim 80 TL). KDV yok.\"\n"
                   "Alanlar: fatura_no (tam sayı), kalemler (dizi: ad, adet, birim_fiyat), "
                   "toplam_tutar (tam sayı)."),
        "sema": {"type": "object", "additionalProperties": False,
                 "required": ["fatura_no", "kalemler", "toplam_tutar"],
                 "properties": {
                     "fatura_no": {"type": "integer"},
                     "toplam_tutar": {"type": "integer"},
                     "kalemler": {"type": "array", "minItems": 2, "items": {
                         "type": "object", "additionalProperties": False,
                         "required": ["ad", "adet", "birim_fiyat"],
                         "properties": {"ad": {"type": "string"},
                                        "adet": {"type": "integer"},
                                        "birim_fiyat": {"type": "integer"}}}}}},
        "beklenen": {"fatura_no": 991, "toplam_tutar": 840,
                     "kalemler.0.adet": 4, "kalemler.1.birim_fiyat": 80},
        "cozum": ('{"fatura_no": 991, "kalemler": ['
                  '{"ad": "kanül", "adet": 4, "birim_fiyat": 150}, '
                  '{"ad": "dren", "adet": 3, "birim_fiyat": 80}], '
                  '"toplam_tutar": 840}'),
    },
    {
        "seviye": 10, "kademe": "acımasız",
        "prompt": ("SADECE JSON ver. Süreleri DAKİKAYA çevir. Şemada olmayan alan "
                   "ekleme. Bitiş saati verilmemişse null yaz.\n"
                   "\"Birinci vaka 1 saat 25 dakika sürdü, 09:00'da başladı. "
                   "İkinci vaka 2 saat sürdü, başlangıcı kayıtlı değil.\"\n"
                   "Alanlar: vakalar (dizi: sira, baslangic (metin|null), sure_dk (tam sayı)), "
                   "toplam_sure_dk (tam sayı)."),
        "sema": {"type": "object", "additionalProperties": False,
                 "required": ["vakalar", "toplam_sure_dk"],
                 "properties": {
                     "toplam_sure_dk": {"type": "integer"},
                     "vakalar": {"type": "array", "minItems": 2, "items": {
                         "type": "object", "additionalProperties": False,
                         "required": ["sira", "baslangic", "sure_dk"],
                         "properties": {"sira": {"type": "integer"},
                                        "baslangic": {"type": ["string", "null"]},
                                        "sure_dk": {"type": "integer"}}}}}},
        "beklenen": {"toplam_sure_dk": 205, "vakalar.0.sure_dk": 85,
                     "vakalar.0.baslangic": "09:00", "vakalar.1.sure_dk": 120,
                     "vakalar.1.baslangic": None},
        "cozum": ('{"vakalar": [{"sira": 1, "baslangic": "09:00", "sure_dk": 85}, '
                  '{"sira": 2, "baslangic": null, "sure_dk": 120}], '
                  '"toplam_sure_dk": 205}'),
    },
    {
        "seviye": 11, "kademe": "acımasız",
        "prompt": ("SADECE JSON ver. Metinde AYNI alan için iki farklı değer var; "
                   "daha SONRA verilen düzeltmeyi esas al ve düzeltilen alanı "
                   "`duzeltilen` dizisine yaz. Şemada olmayan alan ekleme.\n"
                   "\"Hasta 45 yaşında, kan grubu A Rh+. Düzeltme: hastanın yaşı "
                   "45 değil 54, kan grubu doğru.\"\n"
                   "Alanlar: yas (tam sayı), kan_grubu (metin), duzeltilen (metin dizisi)."),
        "sema": {"type": "object", "additionalProperties": False,
                 "required": ["yas", "kan_grubu", "duzeltilen"],
                 "properties": {"yas": {"type": "integer"},
                                "kan_grubu": {"type": "string"},
                                "duzeltilen": {"type": "array", "minItems": 1,
                                               "items": {"type": "string"}}}},
        "beklenen": {"yas": 54, "duzeltilen": ["yas"]},
        "cozum": '{"yas": 54, "kan_grubu": "A Rh+", "duzeltilen": ["yas"]}',
    },
]
