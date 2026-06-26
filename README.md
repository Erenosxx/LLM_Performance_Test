# LLM Performance Test

Lokal LLM'leri (llama-server / OpenAI-uyumlu `/v1` endpoint) sabit bir soru setiyle
test eder, yanıt sürelerini ve GPU kullanımını ölçer, kod/SQL/matematik cevaplarını
**otomatik puanlar** ve PDF rapor üretir.

## Kurulum
```bash
pip install -r requirements.txt
```

## Soru seti (her model için SABİT)
| Kategori | Soru sayısı | Otomatik puanlama |
|----------|-------------|-------------------|
| Yaratıcılık | 1 | Hayır — insan değerlendirmesi (kriterler PDF'te) |
| Kod / algoritma | 8 yazma + 3 okuma (çıktı tahmini) | Evet — fonksiyon çalıştırılıp test edilir / çıktı sayısı kıyas |
| SQL | 8 (kolay→çok zor) | Evet — SQLite'ta referans sorgu ile kıyas |
| Matematik | 8 (kolay→çok zor) | Evet — bilinen sonuçla kıyas |
| **Hata Ayıklama** (branş) | 9 (kolay→çok sinsi) | Evet — BOZUK kod verilir, düzeltilmiş kod çalıştırılıp test edilir |
| **Agentic** (branş) | 6 (3 orta + 3 çok zor) | Evet — çok-turlu ARAÇ kullanımı; model veriyi toplayıp doğru çıkarımı yapmalı |
| **Medikal** (branş) | 8 | Evet — cerrahi aşama/ekipman; gerekli tıbbi terim(ler) eş anlamlılarıyla aranır |

> **Tekrarlanabilirlik:** Varsayılan `temperature=0` (greedy) + `repeat_penalty=1.1` → aynı model aynı soruda HEP aynı cevabı verir (adil/deterministik kıyas). Eskiden temp 0.3 olduğundan skorlar tur-tur değişiyordu.

**Yarışma seviyesi** (LeetCode/AIME/Spider2.0 esinli — güçlü modelleri ayırt etmek için), her kategori 8 soru, kolay→çok zor:
- Kod: roman_sayi → editleme_mesafesi (Levenshtein) → kelime_bol (word break) → n_vezir (N-Queens) → en_uzun_artan_yol → **regex_eslesme (DP)** → **histogram_max_alan (stack)** → **kelime_merdiveni (BFS, word ladder)** — son 3'ü LeetCode **Hard**
- SQL (şema `calisanlar`+`satislar`): HAVING → self-join → RANK() → ROW_NUMBER top-2 → SUM() OVER kümülatif → **recursive CTE (hiyerarşi)** → **LAG (aya göre fark)** → **DENSE_RANK (2. en yüksek)**
- Matematik (AIME/olimpiyat, tek tam-sayı, `#### <sayı>` formatı): Fermat modüler → içerme-dışlama → kombinatorik → x²−y²=2025 → 1/x+1/y=1/12 → **100! sondaki sıfırlar** → **içerme-dışlama komite** → **3 zar kombinatorik**
- **Hata Ayıklama** (agentic modelin "teşhis-düzelt-doğrula" gücünü ölçer): bozuk `en_buyuk`/`carpim`/`tekrar_eden_var_mi`/`ortalama`/`fib` verilir, model düzeltir, otomatik test edilir.
- **Kod-Okuma** (read-before-act): bir kod parçasının çıktısını adım adım izleyip `#### <sayı>` ile verir.

- **Agentic** (`agentic.py` — çok-turlu araç kullanımı; modelin asıl gücünü ölçer): model araç çağırır → sandbox'ta çalıştırıp sonucu geri besleriz → çıkarım yapana kadar (tur limiti 25). 6 görev:
  - Orta: tutarsız muhasebe kaydı (invariant), 5 ipucu kesişimi (→462), çok-kaynaklı çıkarım (en çok satan→yöneticisi)
  - **Çok zor (ayırt edici):** kara kutu — gizli f(x)'i 1-6 deneyip kuralı çıkar, f(10) hesapla (tümevarım); mantık bulmacası — zebra-tarzı 4×şehir×meslek (tümdengelim); graf en kısa yol — A→F Dijkstra (algoritmik arama)
  - Tool-calling yapamayan/yanlış çıkaran model 0 alır. (Test: agentic-v2 kara-kutu+mantık'ı geçti, graf aramada optimali kaçırıp kaldı.)

## Cevaplar nasıl "doğru/yanlış" diye değerlendiriliyor?
- **KOD:** Modelin yazdığı fonksiyon koddan çıkarılır, ayrı bir Python sürecinde
  (15 sn timeout, sonsuz döngü koruması) sabit **girdi→beklenen çıktı** çiftlerine karşı
  çalıştırılır. Tüm girdilerde doğru sonuç verirse **GEÇTİ**. (örn. `faktoriyel(5)==120`)
- **SQL:** Bellek-içi SQLite'a sabit veri yüklenir; modelin sorgusu ile **referans sorgu**
  aynı veritabanında çalıştırılır, satır sonuçları **birebir** aynıysa **GEÇTİ**
  (sütun adı önemsiz, sıralama gerektiğinde sıra da kontrol edilir).
- **MATEMATİK:** Cevaptaki sayılar ve kesirler (örn. `12/5`, `2,4`) ayrıştırılır;
  bilinen doğru sonuç tolerans dahilinde bulunursa **GEÇTİ**.
- **YARATICILIK:** Otomatik puanlanmaz; cevap PDF'e yazılır, değerlendirme kriterleri
  (özgünlük, dil, kurgu, kısıt uyumu) belirtilir.

> Doğrulama: 5 kod + 5 SQL referans çözümünün tümü grader'dan GEÇER, yanlış cevaplar
> ELENİR (oracle tutarlılığı testten geçti).

## A) Tek model testi
```bash
# modeli aç (örnek)
~/Desktop/llama.cpp/build/bin/llama-server -m <model.gguf> -c 8192 -ngl 99 \
  -sm layer --host 0.0.0.0 --port 8080 --jinja
# test et
python llm_perf_test.py --url http://localhost:8080
```
PDF bu klasöre düşer: `rapor_<model>_<tarih>.pdf`.
Sunucusuz grader+PDF denemesi: `python llm_perf_test.py --selftest`

## B) Seçili modelleri otomatik test etme (orkestratör)
`run_models.py` her modeli **sırayla kendisi açar**, test eder, kapatır.

**HANGİ MODELLER? → SADECE `launch/` klasöründe `.sh` dosyası olanlar.**
Bir modeli testten çıkarmak için onun `open_*.sh` dosyasını `launch/` dışına taşı
(örn. yanına oluşturduğun `launch_1/` klasörüne). Geri dahil etmek için geri koy.
Kod `launch/`'ı kendiliğinden yeniden üretmez (taşıdıkların kalıcı olur).

```bash
# ÖNCE 8080'de açık llama-server OLMAMALI (betik modelleri kendi açar)
python run_models.py                       # launch/ içindeki modelleri test et
python run_models.py --gen-launchers       # TÜM modeller için launch/*.sh (yeniden) üret
python run_models.py --only gemma-3-4b-it-Q8_0.gguf   # ek filtre
python run_models.py --combined-selftest   # sahte veriyle PDF düzen testi
```
> İlk kez çalıştırırken `launch/` boşsa tüm modeller için launcher otomatik üretilir.
> Tüm seti geri istersen `--gen-launchers` (launch/ içine hepsini yeniden yazar).

**Çıktı yapısı** (her çalıştırmada YENİ, benzersiz klasör; eskiler silinmez):
```
Model_raporları/
    calisma_<tarih-saat>/                # bu çalıştırmaya özel klasör
        KARSILASTIRMA_<tarih>.pdf        # genel rapor
        model_raporlari/                 # tekli model PDF'leri (alt klasör)
            rapor_<model1>_<tarih>.pdf
            rapor_<model2>_<tarih>.pdf
            ...
```
Tek-model tester (`llm_perf_test.py`) de aynı yapıyı kullanır
(`Model_raporları/calisma_<tarih-saat>/model_raporlari/`).

- **GPU stratejisi (hız için):** ≤17 GB modeller **TEK GPU**'da açılır (bölme/senkron yükü yok → daha hızlı + GPU daha dolu); tek karta sığmayanlar **çift GPU**'ya bölünür (`-sm layer`). Tek GPU'da açılmazsa (32k KV ile sığmazsa) otomatik çift GPU'ya düşer.
- Test edilecek modeller: **`launch/` içindeki `.sh` dosyaları** (seçim için bunları taşı).
  Tam model havuzu + yollar `models_config.py`'de tanımlı (launcher'lar buradan üretilir).
- Bir model açılmazsa **durmaz**, hatayı `logs/<model>.log`'a yazıp sonrakine geçer
  (PDF'te "AÇILMADI"). Aynı model adı tekrarsa atlanır.
- `launch/open_<model>.sh` — her modeli **manuel** açmak için de kullanabilirsin.

**Birleşik PDF içeriği:**
- Üst kısım: skor karşılaştırması (Kod/5, SQL/5, Mat/5, Oto/15, süreler, tok/s, VRAM) +
  **genel performans sütun grafiği** (otomatik skor /15, yüksekten düşüğe, kategori kırılımlı) + süre tablosu
- "Sorular" bölümü: her soru + doğru cevabı (referans çözüm / beklenen sonuç)
- Alt kısım: her model ayrı sayfada, her soruya verdiği cevap kategori kategori, alt alta

## Ölçülen metrikler
- **TTFT** (ilk token süresi), **toplam süre**, **tokens/sec**, üretilen token
- **GPU/VRAM** (**GB** cinsinden): her GPU için min/ort/maks VRAM ve kullanım %; birleşik raporda tepe VRAM artışı

## Raporda kod/SQL çıktısı
Her kod sorusu için PDF'te bir tablo bulunur: **Çağrı | Beklenen çıktı | Modelin çıktısı | ✔/✘**
(modelin yazdığı fonksiyon gerçekten çalıştırılıp her girdideki çıktısı gösterilir).
SQL sorularında **beklenen sonuç** ve **modelin sorgu çıktısı** yan yana verilir.
Kod sorularında modellere "açıklama/yorum yazma, sadece kodu ver" talimatı verilir.

## Parametreler (ortak)
| Argüman | Varsayılan | Açıklama |
|---------|-----------|----------|
| `--temperature` | `0.3` | Tüm sorularda sabit (adil kıyas) |
| `--max-tokens` | `8192` | Yanıt başına maksimum token (düşünen modeller için yüksek) |
| `--no-think` | kapalı | Düşünmeyi (reasoning) kapat (`enable_thinking=false`) |
| `--gpu-interval` | `0.5` | GPU örnekleme aralığı (sn) |
| `--load-timeout` | `300` | (orkestratör) model yüklenme bekleme süresi |

## Reasoning (düşünen) modeller — neden boş cevap olur?
Qwen3 gibi modeller önce `reasoning_content` üretir, sonra nihai cevaba (`content`) geçer.
`max_tokens` düşükse model **düşünürken** limite takılır (`finish_reason=length`) ve nihai
cevabı hiç yazamaz → rapor boş görünür. Çözümler:
- `max_tokens` yüksek tutuldu (4096) — çoğu model düşünüp cevaplayabilsin diye.
- `--no-think` ile düşünmeyi kapat: model doğrudan cevap verir (daha hızlı, garanti cevap).
- Cevap yine boşsa rapor **nedenini** yazar (token limiti / düşünme aşaması) ve elde varsa
  düşünme içeriğinin bir kısmını gösterir — artık sessizce boş kalmaz.

## Not
Süre/UTF-8 kodlaması ve grader'lar gerçek modelle uçtan uca doğrulandı.
Tam tur (tüm modeller × 16 soru) modellerin boyutuna göre uzun sürebilir.
