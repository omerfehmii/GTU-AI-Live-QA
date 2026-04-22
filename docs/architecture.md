# GTU AI Live QA Mimari Notlari

## Servisler
- `frontend`: Next.js tabanli canli soru-cevap ve admin arayuzu.
- `backend`: FastAPI tabanli ingest, soru isleme, RAG ve yonetim API'leri.
- `worker`: Aktif YouTube stream oturumlarini tarayan ve yeni mesaji cevaba donusturen surec.
- `postgres + pgvector`: belge, chunk, stream, soru, cevap ve iz kayitlarinin ana depolamasi.
- `redis`: demo asamasinda altyapi hazirligi ve ileride queue/cache genislemesi icin ayrildi.
- `caddy`: tek alan adi altinda ters proxy ve HTTPS.

## Model Provider Katmani
- `AI_PROVIDER=openai` iken dogrudan OpenAI istemcisi kullanilir.
- `AI_PROVIDER=openrouter` iken ayni OpenAI uyumlu istemci OpenRouter base URL ve ek basliklarla calisir.
- Chat ve embedding model isimleri `AI_CHAT_MODEL` ve `AI_EMBEDDING_MODEL` ile ortak, provider-ozel degiskenlerle geriye uyumlu sekilde override edilebilir.

## Veri Akisi
1. Admin paneli seed URL veya PDF yukler.
2. Backend dokumani temizleyip chunk'lara ayirir ve embedding uretir.
3. Chunk'lar veritabani ve pgvector tarafina yazilir.
4. YouTube worker yeni canli sohbet mesaji gordugunde `Question` kaydi olusturur.
5. RAG servisi ilgili chunk'lari bulur, LLM cagrisi yapar veya fallback cevap uretir.
6. Cevap public arayuzde, iz kayitlari admin tarafinda gorulur.

## GTU Crawl Stratejisi
- `abl.gtu.edu.tr/ects/` once crawl edilir; ders ve AKTS verisi yuksek onceliklidir.
- `/kategori/` ve `/icerik/` path'leri link kesfinde filtre olarak kullanilir.
- Resmi PDF yonetmelik ve kilavuzlar uzak URL olarak dogrudan ingest edilir; sadece manuel upload'a bagli kalinmaz.

## Ilk Demo Operasyon Notlari
- Canli stream baglamadan once en az bir PDF ve bir resmi GTU sayfasi ingest edilmeli.
- Demo sirasinda YouTube arizasi icin `POST /api/questions/manual` akisi hazir tutulmali.
- `GET /api/metrics` panelde acik olmali; gecikme ve cevap sayisi buradan okunur.
