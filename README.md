# FindHouseInNL 🏠

Pararius, Funda, Holland2Stay, HouseHunting ve Findify'daki kiralık ilanları tek yerde toplar,
oda / stüdyo / daire / ev olarak filtreler, aynı evi farklı sitelerde görünce birleştirir ve
yeni ilan düşünce Telegram'dan haber verir. Kişisel kullanım içindir.

## Kurulum (bir kez)

```bash
cd evbul
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`config.example.yaml` dosyasını `config.yaml` adıyla kopyala, şehirleri ve bütçeni ayarla.
(`config.yaml` gizli bilgiler içerdiği için GitHub'a yüklenmez.)

### Tarayıcı modu
Uygulama sayfaları **kendi Chrome'unla (yoksa Edge)** ayrı bir profilde açar, böylece siteler
seni normal ziyaretçi olarak görür. Doğrulama ("Just a moment", captcha) çıkarsa uygulama durur,
terminalde ve Telegram'da haber verir; pencerede kendin tamamlarsın, sonra kendiliğinden devam eder.
Çerezler `browser_profile/` klasöründe kalır, bu yüzden genelde sadece ilk seferde sorulur.
Pencereyi küçültebilirsin ama kapatma.

## Kullanım

```bash
python run.py serve      # arayüz → http://127.0.0.1:8000  (arka planda her 10 dk tarar)
python run.py scrape     # tek seferlik tarama, yeni ilanları terminale yazar
python run.py watch      # sadece arka planda tara + Telegram
```

## Telegram bildirimi (2 dk)

1. Telegram'da **@BotFather** → `/newbot` → verdiği token'ı `bot_token`'a yaz.
2. Yeni botuna bir mesaj at, sonra tarayıcıda aç:
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → `"chat":{"id": ...}` değerini `chat_id`'ye yaz.
3. `python run.py telegram-test`

## Bir site bozulursa / yeni site eklemek

Siteler HTML'lerini değiştirebiliyor. Önce tek başına test et:

```bash
python run.py scrape --only househunting --debug
```

Çekilen sayfalar `debug/` klasörüne kaydedilir. 0 ilan geliyorsa o HTML'e bakıp
`config.yaml`'daki `link_pattern` ya da `card / title / price / area` seçicilerini güncelle.
Yeni bir site eklemek için `sources:` altına aynı formatta bir blok eklemen yeterli.

| Kaynak | Durum |
|---|---|
| Pararius | Ana kaynak, en stabil |
| Funda | Bot koruması güçlü, ara sıra engellenir (arayüzde ⚠ görünür) |
| Holland2Stay | Beta, GraphQL API, alanları kendi kendine uyarlar |
| HouseHunting / Findify | Genel adaptör, ilk çalıştırmada `--debug` ile ayarlanmalı |

## Testler

```bash
python tests/test_all.py
```
