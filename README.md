# GTU AI Live QA

GTU resmi web sayfalari ve PDF belgeleriyle beslenen, YouTube canli sohbetinden soru alip bunlari kurum odakli olarak yanitlayan bir demo urun iskeleti.

## Neler Var
- `backend/`: FastAPI API, ingest servisleri, RAG motoru, YouTube poller worker'i
- `frontend/`: Next.js canli akış ve admin paneli
- `docker-compose.yml`: tek VPS icin temel servis orkestrasyonu
- `docs/`: mimari ve rapor taslagi notlari

## Hemen Baslat
1. `.env.example` dosyasini `.env` olarak kopyalayin.
2. LLM provider secin:
   - OpenAI icin `AI_PROVIDER=openai` ve `OPENAI_API_KEY` doldurun.
   - OpenRouter icin `AI_PROVIDER=openrouter` ve `OPENROUTER_API_KEY` doldurun.
3. Gerekirse model isimlerini guncelleyin:
   - OpenAI: `OPENAI_CHAT_MODEL`, `OPENAI_EMBEDDING_MODEL`
   - Genel override: `AI_CHAT_MODEL`, `AI_EMBEDDING_MODEL`
4. `YOUTUBE_API_KEY` degerini doldurun.
5. `bash scripts/docker_up.sh` calistirin.
6. Public arayuz icin `http://localhost`, admin icin `http://localhost/admin` kullanin.
7. Prod domain kullanacaksaniz `.env` icinde `APP_DOMAIN=alanadiniz.com` yapin; lokal calismada `APP_DOMAIN=http://localhost` olarak birakin.

## Docker ile Calistirma
```bash
cd /Users/omer/Desktop/bitirme
bash scripts/docker_up.sh
```

Bu akista lokal public giris noktasi `http://localhost` olur. Caddy prod'da domain verildiginde HTTPS kullanir; lokalde ise tarayici sertifika uyarisina dusmemek icin HTTP ile calisir.

## Crawl, Arsiv, Index
- `Crawl`: seed URL'lerden baslayip yeni sayfa ve PDF baglantilarini kesfetme asamasi.
- `Kaynak arsivi`: indirilen HTML ve PDF dosyalarini disk uzerinde saklama katmani.
- `Index`: arsivdeki icerigi chunk + embedding'e cevirip veritabanina yazma asamasi.

Sistem artik uzak kaynaklari her seferinde yeniden indirmez. Ilk crawl sonrasinda parse edilmis icerik ve ham dosyalar `backend/data/source_archive` altinda tutulur. Sonraki calismalarda ayni URL'ler varsayilan olarak bu yerel arsivden okunur.

Admin panel akisi:
- `1. Arsive indir`: resmi GTU sayfalari ve PDF'leri indirip yerel arsive kaydeder.
- `2. Arsivden indexle`: arsivdeki parse edilmis kaynaklari veritabanina ve embedding index'ine yazar.
- `Arsiv istatistikleri`: toplam kaynak, web/PDF dagilimi, ham dosya varligi ve son cache zamani gorulur.

API endpointleri:
- `POST /api/admin/archive/crawl`
- `POST /api/admin/archive/index`
- `GET /api/admin/archive/stats`
- `POST /api/admin/ingest/web`:
  geriye donuk uyumluluk icin tek adimlik crawl + index akisi

Kaynak sayisini artirmak icin:
- `max_pages` degerini yukselterek daha fazla sayfa gezdir
- `discover_sitemaps=true` ile robots/sitemap kesfini acik tut
- seed URL listesini resmi GTU alanlarindaki kategori, icerik, faq ve aday sayfalariyla genislet

Zorla guncellemek istersen:
- Admin panelde `Kaynaklari agdan yeniden indir` secenegini ac
- veya istek govdesinde `refresh_cached_sources=true` gonder

Kapatmak icin:
```bash
cd /Users/omer/Desktop/bitirme
bash scripts/docker_down.sh
```

Kontrol komutlari:
```bash
docker compose ps
curl http://localhost:8000/api/health
find backend/data/source_archive -maxdepth 2 -type f | head
```

## OpenRouter Ornegi
```env
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
AI_CHAT_MODEL=openai/gpt-4.1-mini
AI_EMBEDDING_MODEL=openai/text-embedding-3-small
OPENROUTER_SITE_URL=http://localhost
OPENROUTER_APP_NAME=GTU AI Live QA
```

## Gelistirme
### Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Worker
```bash
cd backend
python -m app.worker
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Test
```bash
cd backend
pytest
```

## Tam Ingest ve Kalite Testi
```bash
cd backend
env -u OPENROUTER_API_KEY -u OPENAI_API_KEY .venv/bin/python scripts/run_gtu_quality_suite.py \
  --database-url sqlite:////Users/omer/Desktop/bitirme/backend/quality_suite.db
```

- Seed profil dosyasi: [sample_data/gtu_seed_urls.json](/Users/omer/Desktop/bitirme/sample_data/gtu_seed_urls.json)
- Resmi GTU kaynak katalogu: [docs/gtu_source_catalog.md](/Users/omer/Desktop/bitirme/docs/gtu_source_catalog.md)
- Degerlendirme soru seti: [sample_data/gtu_eval_questions.json](/Users/omer/Desktop/bitirme/sample_data/gtu_eval_questions.json)
- Rapor cikisi: [docs/gtu_quality_report.json](/Users/omer/Desktop/bitirme/docs/gtu_quality_report.json)

## Notlar
- API anahtari yoksa embedding ve cevap tarafinda deterministik fallback mekanizmasi devreye girer.
- OpenRouter secildiginde backend `OpenAI-compatible` istemciyi `https://openrouter.ai/api/v1` uzerinden kullanir.
- Web ingest artik uzak `PDF URL` listesi, `include_url_patterns` ve `prioritize_url_patterns` alanlarini destekler.
- Kullanici arayuzunde kaynak gostermiyoruz; ancak `AnswerTrace` verileri backend tarafinda saklaniyor.
- Redis servisi su an genisleme hazirligi icin eklendi; ilk demoda kritik akiş DB + worker uzerinden yuruyor.
