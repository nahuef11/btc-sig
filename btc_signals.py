#!/usr/bin/env python3
"""Señales BTC: técnicos + Fear & Greed + noticias. Avisa por Telegram y se recalibra solo."""
import json, os, math, urllib.request, urllib.parse, datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

H, TH = 7, 35  # horizonte de evaluación (días) y umbral de aviso
BASE = {"rsi": .20, "macd": .20, "trend": .15, "bb": .15, "fg": .20, "news": .10}
STATE = "state.json"
POS = ("surge", "rally", "bull", "record", "adopt", "approve", "inflow", "soar", "gain", "jump", "rise")
NEG = ("crash", "plunge", "bear", "ban", "hack", "lawsuit", "outflow", "selloff", "sell-off", "drop", "fall", "fraud", "liquidat", "decline")

cl = lambda x, a=-1, b=1: max(a, min(b, x))
now = lambda: dt.datetime.now(dt.timezone.utc)


def get(url, data=None):
    r = urllib.request.Request(url, data=data, headers={"User-Agent": "btc-signals/1.0"})
    return urllib.request.urlopen(r, timeout=30).read()


def ema(a, n):
    k, e, o = 2 / (n + 1), a[0], [a[0]]
    for x in a[1:]:
        e = x * k + e * (1 - k)
        o.append(e)
    return o


def rsi(a, n=14):
    g = l = 0
    for i in range(1, n + 1):
        d = a[i] - a[i - 1]
        g, l = (g + d, l) if d >= 0 else (g, l - d)
    g, l = g / n, l / n
    for i in range(n + 1, len(a)):
        d = a[i] - a[i - 1]
        g, l = (g * (n - 1) + max(d, 0)) / n, (l * (n - 1) + max(-d, 0)) / n
    return 100 if l == 0 else 100 - 100 / (1 + g / l)


def scores(p, fg=None, news=None):
    last, out = p[-1], {}
    out["rsi"] = cl((50 - rsi(p)) / 20)
    m = [x - y for x, y in zip(ema(p, 12), ema(p, 26))]
    sg = ema(m, 9)
    out["macd"] = cl((m[-1] - sg[-1]) / (last * .005))
    n = 200 if len(p) >= 200 else 50
    out["trend"] = cl((last / (sum(p[-n:]) / n) - 1) * 10)
    w = p[-20:]
    mu = sum(w) / 20
    sd = math.sqrt(sum((x - mu) ** 2 for x in w) / 20) or 1
    out["bb"] = cl((.5 - (last - (mu - 2 * sd)) / (4 * sd)) * 2)
    if fg is not None: out["fg"] = cl((50 - fg) / 30)
    if news is not None: out["news"] = cl(news)
    return out


def combine(sc, w):
    return round(sum(sc[k] * w[k] for k in sc) / sum(w[k] for k in sc) * 100)


def recalibrate(p, dates, fgmap):
    """Pesos nuevos según aciertos a 7 días en los últimos ~400 días (solo mira hacia atrás en cada punto)."""
    st = {k: [0, 0] for k in BASE if k != "news"}
    for i in range(max(200, len(p) - H - 400), len(p) - H):
        sc = scores(p[max(0, i - 299):i + 1], fgmap.get(dates[i]))
        ret = p[i + H] / p[i] - 1
        for k, s in sc.items():
            if k in st and abs(s) >= .2:
                st[k][0] += 1
                st[k][1] += (s > 0) == (ret > 0)
    w, info = dict(BASE), {}
    for k, (n, h) in st.items():
        if n >= 40:
            hr = h / n
            info[k] = (round(hr * 100), n)
            w[k] = BASE[k] * max(.25, min(1.75, 1 + 4 * (hr - .5)))
    t = sum(w.values())
    return {k: v / t for k, v in w.items()}, info


def kraken():
    d = json.loads(get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440"))["result"]
    rows = [v for k, v in d.items() if k != "last"][0]
    return ([float(r[4]) for r in rows],
            [dt.datetime.fromtimestamp(r[0], dt.timezone.utc).strftime("%Y-%m-%d") for r in rows])


def fng():
    d = json.loads(get("https://api.alternative.me/fng/?limit=0"))["data"]
    return {dt.datetime.fromtimestamp(int(x["timestamp"]), dt.timezone.utc).strftime("%Y-%m-%d"): int(x["value"]) for x in d}


FEEDS = [("CoinDesk", "https://www.coindesk.com/arc/outputs/rss/"), ("Cointelegraph", "https://cointelegraph.com/rss"),
         ("Decrypt", "https://decrypt.co/feed"), ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
         ("The Block", "https://www.theblock.co/rss.xml"),
         ("Google News", "https://news.google.com/rss/search?q=bitcoin+when:1d&hl=es-419&gl=AR&ceid=AR:es-419")]
TOPICS = {"ETF": ("etf",), "Regulación": ("sec ", "regulat", "ban ", "lawsuit", "court", "cftc", "ley "),
          "Macro": ("fed ", "inflation", "rate cut", "rate hike", "tariff", "fomc", "tasas", "inflaci"),
          "Seguridad": ("hack", "exploit", "stolen", "breach"), "Mercado": ("price", "rally", "crash", "liquidat", "whale", "precio"),
          "Adopción": ("adopt", "treasury", "reserve", "bank", "institution")}
HIGH = ("hack", "exploit", "sec ", "etf", "ban ", "fed ", "fomc", "lawsuit", "liquidat", "crash", "reserve")


def fetch_news():
    out = []
    for src, u in FEEDS:
        try:
            for i in list(ET.fromstring(get(u)).iter("item"))[:20]:
                t, link = (i.findtext("title") or "").strip(), (i.findtext("link") or "").strip()
                if not t or not link: continue
                try: ts = parsedate_to_datetime(i.findtext("pubDate")).astimezone(dt.timezone.utc)
                except Exception: ts = now()
                out.append({"id": link, "type": "news", "source": i.findtext("source") or src, "text": t,
                            "link": link, "ts": ts.isoformat(timespec="seconds")})
        except Exception as e:
            print("RSS falló:", src, e)
    return out


def enrich(i):
    low = f" {i['text'].lower()} "
    i["topics"] = [k for k, ws in TOPICS.items() if any(w in low for w in ws)]
    p, n = any(w in low for w in POS), any(w in low for w in NEG)
    i["sent"] = 1 if p and not n else -1 if n and not p else 0
    i["impact"] = any(w in low for w in HIGH)
    return i


def news_score(items):
    lim = (now() - dt.timedelta(hours=24)).isoformat()
    r = [i["sent"] for i in items if i["ts"] >= lim and i["sent"]]
    return (sum(r) / len(r)) if r else (0.0 if items else None)


def write_feed(items, pulse, sigs):
    os.makedirs("docs", exist_ok=True)
    try: old = json.load(open("docs/feed.json"))["items"]
    except Exception: old = []
    d = {i["id"]: i for i in old + items + sigs}
    allv = sorted(d.values(), key=lambda i: i["ts"], reverse=True)[:300]
    json.dump({"updated": now().isoformat(timespec="seconds"), "pulse": pulse, "items": allv},
              open("docs/feed.json", "w"), ensure_ascii=False)


def telegram(text):
    tok, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print(text); return
    get(f"https://api.telegram.org/bot{tok}/sendMessage",
        urllib.parse.urlencode({"chat_id": chat, "text": text}).encode())


def evaluate(hist):
    for i, e in enumerate(hist):
        if "ret" in e: continue
        t = dt.datetime.fromisoformat(e["ts"]) + dt.timedelta(days=H)
        for f in hist[i + 1:]:
            if dt.datetime.fromisoformat(f["ts"]) >= t:
                e["ret"] = round(f["price"] / e["price"] - 1, 4)
                break


def accuracy(hist):
    a = [e for e in hist if e["action"] != "ESPERAR" and "ret" in e]
    ok = sum((e["action"] == "COMPRAR") == (e["ret"] > 0) for e in a)
    return len(a), ok


def main():
    p, dates = kraken()
    fgmap = fng()
    w, info = recalibrate(p, dates, fgmap)
    fg = fgmap.get(dates[-1], next(iter(fgmap.values())) if fgmap else None)
    items = [enrich(i) for i in fetch_news()]
    sc = scores(p, fg, news_score(items))
    score = combine(sc, w)
    action = "COMPRAR" if score >= TH else "VENDER" if score <= -TH else "ESPERAR"

    try: st = json.load(open(STATE))
    except Exception: st = {"last": "ESPERAR", "history": []}
    st["history"].append({"ts": now().isoformat(timespec="seconds"), "price": p[-1], "score": score, "action": action})
    st["history"] = st["history"][-4000:]
    evaluate(st["history"])

    det = " | ".join(f"{k} {v:+.2f}" for k, v in sc.items())
    sigs, ts0 = [], st["history"][-1]["ts"]
    if action != st.get("last"):
        sigs.append({"id": "sig-" + ts0, "type": "signal", "source": "Señales BTC", "action": action, "detail": det,
                     "text": f"{action} · puntuación {score} · BTC {p[-1]:,.0f} USD", "ts": ts0})
        if action != "ESPERAR":
            telegram(f"{'🟢' if action == 'COMPRAR' else '🔴'} {action} BTC\nPrecio {p[-1]:,.0f} USD · puntuación {score}\n{det}")
    st["last"] = action

    n = now()
    if n.weekday() == 0 and n.hour == 7:
        tot, ok = accuracy(st["history"])
        live = f"{ok}/{tot} avisos acertados a {H} días" if tot else "aún sin avisos evaluables"
        ws = ", ".join(f"{k} {v * 100:.0f}%" for k, v in w.items())
        hi = ", ".join(f"{k} {h}% ({c})" for k, (h, c) in info.items())
        telegram(f"📊 Informe semanal BTC\nPrecio {p[-1]:,.0f} · puntuación {score} ({action})\nAciertos en vivo: {live}\n"
                 f"Aciertos históricos por indicador: {hi}\nPesos actuales: {ws}")
    try: seen = {i["id"] for i in json.load(open("docs/feed.json"))["items"]}
    except Exception: seen = None
    if seen is not None:
        for i in [x for x in items if x["impact"] and x["id"] not in seen][:3]:
            telegram(f"⚡ {i['source']}: {i['text']}\n{i['link']}")
    tot, ok = accuracy(st["history"])
    write_feed(items, {"price": p[-1], "score": score, "action": action, "fg": fg, "acc": [tot, ok],
                       "weights": {k: round(v, 3) for k, v in w.items()}}, sigs)
    st["weights"] = {k: round(v, 3) for k, v in w.items()}
    json.dump(st, open(STATE, "w"), indent=1)
    print(action, score, st["weights"])


if __name__ == "__main__":
    main()
