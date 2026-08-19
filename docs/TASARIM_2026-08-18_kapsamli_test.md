# Kapsamlı LLM Değerlendirme Testi — Tasarım Dokümanı

**Tarih:** 18 Ağustos 2026
**Durum:** İnceleme bekliyor (onaydan sonra geliştirmeye başlanacak)
**Kapsam kararları:** Dört yeni branş grubu da dahil · Görsel branş YOK · Tüm sorular avg@3 · Model başına maksimum performans

---

## 1. Neden: mevcut test ölçmüyor

17 Ağustos koşusunda (`Model_raporları/calisma_20260817_173317`) dört modelin **80 puanlı sorunun her birindeki** geçti/kaldı durumu karşılaştırıldı:

| Durum | Soru | Oran |
|---|---:|---:|
| Dört model de GEÇTİ | 73 | %91 |
| Dört model de KALDI | 1 | %1 |
| **Modelleri ayırt eden** | **6** | **%7,5** |

Ayırt eden altı soru: SQL S5, S7, S13 · Medikal S3, S6 · Hata Ayıklama S5.
**Sıfır ayrım üreten branşlar:** Agentic (11 soru), Kod (13), Matematik (13), Kod-Okuma (3).

Sonuç: 75-79 arasındaki dört puanlık fark 80 sorunun değil, 6 sorunun eseri. Bu farkla model seçimi yapılamaz.

İkinci sorun: **ikili puanlama bilgi imha ediyor.** 10 gizli testin 9'unu geçen model ile hiçbirini geçemeyen model aynı 0'ı alıyor.

Üçüncü sorun: **ölçülmeyen yetenekler.** Uzun bağlam, talimata uyma, halüsinasyon direnci, yapılandırılmış çıktı, Türkçe dil yetkinliği ve gerçek ajan davranışı (hata kurtarma, çeldirici, bütçe) testte hiç yok — oysa modeller birbirinden en çok bu alanlarda ayrışıyor.

---

## 2. Puanlama modeli

### 2.1 Kısmi puan (ikili değil)

Her grader `0.0 - 1.0` arası sürekli puan döndürür:

| Grader | Kısmi puan tanımı |
|---|---|
| `code` | geçen gizli test / toplam gizli test |
| `sql` | satır kümesi F1 (beklenen ∩ gelen); sorgu hata verirse 0 |
| `medikal` | bulunan gerekli terim / toplam gerekli terim |
| `math` | ikili kalır (0 veya 1) — sayı ya doğrudur ya değil |
| `talimat` | sağlanan kısıt / toplam kısıt |
| `json` | şema uyumu: geçerli JSON (0,3) + şema geçer (0,4) + alan değerleri doğru (0,3) |
| `halusinasyon` | ikili: uydurma yaptı mı (0) / bilmediğini söyledi mi (1) |
| `uzun_baglam` | doğru çıkarılan olgu / istenen olgu |
| `agentic` | görev sonucu (0,7) + verimlilik (0,3: bütçe içinde kaldı mı, gereksiz çağrı yaptı mı) |

### 2.2 Zorluk kademesi ve ağırlık

Her soru bir kademeye etiketlenir; ağırlığı kademesinden gelir:

| Kademe | Ağırlık | Tanım |
|---|---:|---|
| `kolay` | 1 | Sınıfın tamamının geçmesi beklenir (taban kontrolü) |
| `orta` | 2 | Çoğu geçer |
| `zor` | 3 | Ayrım burada başlar |
| `acımasız` | 4 | Bugün hiçbiri geçmeyebilir — tavan ölçümü |

Model puanı = `Σ (ağırlık × kısmi_puan)`. Rapor ayrıca **"tam çözdüğü en zor kademe"**yi gösterir.

Doygunluk tekrar oluşursa çözüm bellidir: alt kademe emekliye ayrılır, üste yeni kademe eklenir.

### 2.3 avg@3 ve kararlılık

Her soru **3 kez** sorulur (yaratıcılık branşı hariç — insan değerlendirmesi, 1 kez yeter).

- **Puan** = üç denemenin kısmi puan ortalaması
- **Kararlılık** = üç denemenin aynı sonucu verme oranı (1,0 = üçünde de aynı; 0,33 = tamamen tutarsız)

Kararlılık ayrı bir metrik olarak raporlanır: kart ayarıyla (rastgele örnekleme) koşulduğu için "şansa geçen" sorular böyle görünür hale gelir.

### 2.4 Madde analizi (testin kendini denetlemesi)

Koşu sonunda her soru için modeller arası puan varyansı hesaplanır ve rapora yazılır:

- **σ = 0** → soru ayırt etmiyor, emekliye aday (bugün 74 soru bu durumda)
- **σ yüksek** → soru çalışıyor

Bu, bugün elle yaptığımız analizin araca gömülmüş hâli. En az 2 model koşulmuş olmalı, yoksa hesaplanmaz.

---

## 3. Branş tasarımları

Hedef: **~135 puanlı soru** (bugün 80). Sayılar `--brans` ve `--tekrar` ile daraltılabilir.

### 3.1 Mevcut branşların sertleştirilmesi

Mevcut 80 soru silinmez, `kolay`/`orta` kademesine indirilir; üstlerine yeni kademeler eklenir.

| Branş | Bugün | Hedef | Eklenecek zor kademe |
|---|---:|---:|---|
| Kod | 13 | 16 | Çok fonksiyonlu görev, karmaşıklık kısıtı (O(n log n) — zaman aşımıyla ölçülür), tuzak kenar durumları |
| Kod-Okuma | 3 | 4 | Yan etkili / kapanış (closure) davranışı izleme |
| SQL | 13 | 16 | Çok tablolu CTE + pencere fonksiyonu; "çalışan ama yanlış" sorguyu eleyen karşı-örnek satırlar |
| Matematik | 13 | 15 | Çok parçalı, ara adımı da doğrulanan sorular |
| Hata Ayıklama | 14 | 16 | Tek bug yerine iki etkileşimli bug, sessiz veri bozulması |
| Medikal | 13 | 16 | WP6 transkriptlerindeki gerçek terim karışıklıklarından türetilmiş ayrım soruları |

### 3.2 Uzun bağlam (yeni, 6 soru)

Dört model de 262k native context destekliyor; bu branş bugün tamamen ölçülmeyen bir yeteneği açar.

- **Üretim:** belgeler sabit tohumlu bir üreteçle programatik oluşturulur (dış veri yok, PII yok, cevap kesin bilinir).
- **Görevler:** (a) iğne bulma — olgu %10/%50/%90 derinliğe gömülür; (b) çelişki yakalama — belgenin iki yerinde çakışan ifade; (c) çok kaynaklı sentez — üç ayrı bölümden olgu birleştirme.
- **Kademeler:** 8k / 32k / 64k / 128k. Her model **VRAM'inin izin verdiği en uzun kademeye kadar** koşar; erişebildiği tavan ayrıca bir yetenek metriği olarak raporlanır.
- **Grader:** `uzun_baglam` — çıkarılan olgu / istenen olgu.

### 3.3 Talimata uyma (yeni, 10 soru)

Bileşik ve makineyle sayılabilir kısıtlar; IFBench mantığı.

Örnek: *"Tam 5 madde yaz. Her madde 'K' harfiyle başlasın. Hiçbir maddede 've' bağlacı geçmesin. Maddeleri en uzundan en kısaya sırala. Sonuna açıklama ekleme."*

- **Grader:** `talimat` — her kısıt bağımsız denetlenir (regex/sayım), puan = sağlanan/toplam.
- **Zorluk:** kısıt sayısı 3'ten 8'e çıkar; bazı kısıtlar birbirini zorlaştırır (negatif kısıt + sıralama + uzunluk).

### 3.4 Halüsinasyon direnci (yeni, 10 soru)

- **Cevaplanamaz sorular:** var olmayan çalışma/ilaç/protokol hakkında spesifik sayı isteyen sorular.
- **Yanlış öncül:** *"X ameliyatında kullanılan Y kanülünün 2023 revizyonunda çap neden 4 mm'ye düşürüldü?"* — böyle bir revizyon yok; doğru davranış öncülü reddetmek.
- **Grader:** `halusinasyon` — cevapta (a) belirsizlik/bilmeme ifadesi VAR mı, (b) uydurma spesifik sayı/isim YOK mu. İkisi de sağlanırsa 1, değilse 0.
- **Neden önemli:** hasta güvenliği ile doğrudan ilgili; WP6'da Qwen3.8'in en düşük kritik-bozma oranını vermesi bu eksenin ölçülmeye değer olduğunu gösteriyor.

### 3.5 Türkçe dil yetkinliği (yeni, 10 soru)

Hazır benchmark'ların ölçmediği, senin gerçek işine en yakın eksen.

- Biçimbilim: ek çözümleme, çok ekli sözcük üretimi
- Noktalama ve şapka restorasyonu (`kar`/`kâr`, `adet`/`âdet`)
- Kayıt dönüşümü: konuşma dilinden tıbbi rapor diline (WP6 işinin çekirdeği)
- Terim ayrımı: sesteş tıbbi terimler
- **Grader:** çoğunlukla `talimat`/`medikal` graderlarının yeniden kullanımı + normalize edilmiş kesin eşleşme.

### 3.6 Yapılandırılmış çıktı (yeni, 8 soru)

- İç içe JSON şeması, enum kısıtı, zorunlu/opsiyonel alan, `null` ile boş string ayrımı, Türkçe karakter kaçışı.
- Baskı unsuru: veri metin içinde dağınık verilir; model hem çıkarım hem biçim uyumu yapmalı.
- **Grader:** `json` — `jsonschema` kütüphanesi mevcut (doğrulandı), üç aşamalı kısmi puan (§2.1).

### 3.7 Agentic branşının yeniden inşası (11 → 12 soru)

Mevcut 11 görev bulmaca ve hepsi 11/11. Gerçek ajan yeteneği şu eksenlerle ölçülür:

| Eksen | Tasarım |
|---|---|
| Hata kurtarma | Araç ilk çağrıda hata döndürür, ikincide çalışır — model tekrar deniyor mu? |
| Çeldirici araç | 12 araç sunulur, 3'ü ilgili; gereksiz çağrı puan düşürür |
| Bütçe kısıtı | En fazla N çağrı; verimsiz keşif cezalandırılır |
| Uzun ufuk | 30+ tur, ara durumu hatırlamayı gerektiren görev |
| Kirli veri | Araç çıktısında çelişki var; model fark edip doğrulamalı |
| Belirsiz talimat | Eksik bilgi araçla kapatılmalı |

- **Grader:** `agentic` — sonuç (0,7) + verimlilik (0,3).
- Mevcut 11 görev korunur ama `kolay` kademesine iner.

---

## 4. Maksimum performans koşusu

Bugüne kadar tüm modeller aynı parametrelerle koştu. Yeni koşuda her model **kendi en iyi hâlinde** açılır.

### 4.1 Model profilleri

`models_config.py` içine model başına profil eklenir. Örnekleme değerleri modellerin kendi `generation_config.json` dosyalarından alındı:

| Model | temperature | top_p | top_k | reasoning_effort |
|---|---:|---:|---:|---|
| gemma-4-26B-A4B | 1,0 | 0,95 | 64 | — (desteklemiyor) |
| gemma-4-31B-qat | 1,0 | 0,95 | 64 | — |
| Qwen3.5-27B | 0,6 | 0,95 | 20 | — |
| Qwen3.8-27B | 1,0 | 0,95 | 20 | **medium** |

`reasoning_effort` gerekçesi (17 Ağustos'ta ölçüldü, `kelime_merdiveni` sorusu):

| Ayar | Süre | Token | Sonuç |
|---|---:|---:|---|
| low | 10 s | 441 | cevap üretildi |
| medium | 14 s | 590 | cevap üretildi |
| xhigh (varsayılan) | 133 s | 6000 | **tavana çarptı, cevap yok** |

Varsayılan `xhigh` testte 12,5 dakika yakıp 0 aldırmıştı. `medium` hem düşünmeyi korur hem kaçağı önler.

### 4.2 Context ve VRAM

Tek RTX 4090 (24564 MiB). Ölçülen: en dar model (gemma-4-31B-qat) 32k'da 23423 MiB, üretim sırasında +12 MiB.

- Her model için sığan **en büyük context** ölçülerek belirlenir, tek tip dayatılmaz.
- Uzun bağlam branşının üst kademeleri için KV kuantizasyonu (`-ctk q8_0 -ctv q8_0`) devreye alınır; hangi kademede kullanıldığı raporda belirtilir.
- Her modelin ulaşabildiği context tavanı ayrıca yetenek metriği olarak yazılır.

### 4.3 Token tavanı ve kesilme

- Yapay `max_tokens` sınırı kalkar; yerine context'ten türetilen soru başına üst sınır gelir.
- **Tavana çarpma ayrı metrik olarak raporlanır.** Bugün sessizce 0 yazılıyor; artık "cevapsız kaldı (kesildi)" olarak görünecek — yetenek eksikliği ile bütçe tükenmesi karışmayacak.

### 4.4 Yöntemsel not (rapora da girecek)

Koşullar model başına farklı olduğu için sonuç **"aynı koşulda hangisi iyi"** değil, **"her biri en iyi hâliyle ne yapabiliyor"** sorusunu cevaplar. Model seçimi için doğru soru budur, ama karşılaştırma tablosunun altına bu not düşülecek ve her modelin parametreleri raporda listelenecek.

---

## 5. Mimari

`llm_perf_test.py` bugün 117 KB / ~2000 satır ve altı yeni branş + yeni puanlama bu dosyaya sığmaz. Yapı bölünür:

```
bench/
    banks/          her branş kendi modülünde (kod.py, sql.py, uzun_baglam.py, ...)
    graders.py      tüm grader'lar, hepsi 0-1 arası puan döndürür
    scoring.py      kısmi puan, kademe ağırlıkları, avg@3, kararlılık, madde analizi
    profiles.py     model başına örnekleme/context/reasoning_effort profilleri
llm_perf_test.py    koşum motoru + PDF (banks/graders'ı import eder)
run_models.py       orkestratör (profil bazlı launcher üretimi)
agentic.py          araç tanımları + çok turlu döngü (yeni eksenlerle genişler)
```

**Taşıma riski ve önlemi:** mevcut soru bankalarının `bench/banks/` altına taşınması mekanik bir işlem; güvenlik ağı hâlihazırda var — `--selftest` tüm referans çözümlerin geçtiğini ve yanlışların elendiğini sunucusuz doğruluyor. Taşımadan sonra selftest'in aynı sonucu vermesi şart koşulur.

### Entegrasyon noktaları

| Dosya | Değişiklik |
|---|---|
| `llm_perf_test.py:1105 build_questions` | banks modüllerinden toplama |
| `llm_perf_test.py:1351 grade_answer` | 0-1 puan döndürme; ikili `passed` türetilir (>= 0,999) |
| `llm_perf_test.py:1425 category_summary` | ağırlıklı puan + kademe + kararlılık |
| `llm_perf_test.py:1560 ask_llm` | profil parametreleri (top_p/top_k/reasoning_effort) |
| `llm_perf_test.py:1888 run_questions` | avg@3 döngüsü, kesilme kaydı |
| `llm_perf_test.py:1719 build_pdf` | yeni tablolar |
| `run_models.py:511 gen_launchers` | profil bazlı, model başına context/KV |
| `models_config.py` | `PROFILES` sözlüğü |

---

## 6. Raporlama

Karşılaştırma PDF'ine eklenecekler:

1. **Ağırlıklı puan tablosu** — branş × model, kademe kırılımıyla
2. **Çözülen en zor kademe** — model başına
3. **Kararlılık** — avg@3 tutarlılık oranı
4. **Verimlilik** — doğru cevap başına token ve saniye
5. **Kesilme oranı** — tavana çarpıp cevapsız kalan soru yüzdesi
6. **Madde analizi** — ayırt etmeyen sorular listesi (emeklilik adayları)
7. **Model parametreleri** — her modelin hangi ayarla koştuğu

Not: yeni puanlama eski koşularla kıyaslanamaz; eski PDF'ler arşiv olarak kalır.

---

## 7. Süre bütçesi

Son koşu: 86 soru × 4 model = 3 sa 23 dk. Soru başına ortalama ~35 s (modele göre 16-62 s).

| Mod | Soru | Tekrar | Tahmin (4 model) |
|---|---:|---:|---:|
| `--hizli` (geliştirme sırasında) | ~40 çekirdek | 1 | ~1,5 saat |
| Tam koşu (karar verilen) | ~135 | 3 | **~15-16 saat** |

Tam koşu gecelik bırakılacak şekilde tasarlanır: model açılmazsa durmaz, ara sonuçlar diske yazılır, kesilirse kaldığı yerden devam edebilir.

---

## 8. Riskler

| Risk | Önlem |
|---|---|
| Taşıma sırasında mevcut sorular bozulur | `--selftest` taşıma öncesi/sonrası aynı sonucu vermeli |
| Yeni sorular da doygun çıkar | Madde analizi her koşuda uyarır; `acımasız` kademesi tavan bırakır |
| Uzun bağlam VRAM'e sığmaz | Kademeli tasarım; model erişebildiği yere kadar koşar, tavanı raporlanır |
| avg@3 süreyi 3 katına çıkarır | `--tekrar` ayarlanabilir; geliştirme `--hizli` ile yapılır |
| Yeni grader'lar hatalı puan verir | Her grader için referans çözüm GEÇMELİ + kasten bozuk cevap KALMALI testi (mevcut selftest deseni) |
| Kart ayarıyla rastgelelik | Kararlılık metriği bunu görünür kılar |

---

## 9. Teslim sırası

| Faz | İçerik | Doğrulama |
|---|---|---|
| 0 | Modül yapısı + kısmi puanlama + kademe ağırlıkları + madde analizi | selftest aynı sonucu verir; eski sorularla ayrım hesaplanır |
| 1 | avg@3, kesilme metriği, profil desteği (`ask_llm`, launcher) | `--hizli` koşusu 2 modelle |
| 2 | Talimata uyma + JSON + halüsinasyon (yazması en hızlı, ayrımı yüksek) | grader başına pozitif/negatif test |
| 3 | Türkçe + Medikal derinleştirme | aynı |
| 4 | Uzun bağlam (üreteç + kademeler + KV kuantizasyon yolu) | 8k/32k canlı prova |
| 5 | Agentic yeniden inşa | araç hatası/çeldirici/bütçe senaryolarının canlı provası |
| 6 | Mevcut branşların sertleştirilmesi | madde analizi ayrımın arttığını göstermeli |
| 7 | Rapor tabloları | `--combined-selftest` ile düzen kontrolü |
| 8 | Tam koşu (gecelik) | — |

---

## 10. Kapsam dışı

- Görsel/multimodal branş (ayrı iş kalemi olarak ertelendi)
- Yaratıcılık branşının otomatik puanlanması (insan değerlendirmesi kalır, avg@3 uygulanmaz)
- Eski koşularla geriye dönük karşılaştırma (puanlama değiştiği için mümkün değil)
