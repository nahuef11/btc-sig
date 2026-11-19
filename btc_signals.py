#!/usr/bin/env python3
"""Señales BTC: técnicos + Fear & Greed + noticias. Avisa por Telegram y se recalibra solo."""
import json, os, re, math, zlib, struct, urllib.request, urllib.parse, datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

H, TH = 7, 35  # horizonte de evaluación (días) y umbral de aviso
BASE = {"rsi": .20, "macd": .20, "trend": .15, "bb": .15, "fg": .20, "news": .10}
STATE = "state.json"
POS = ("surge", "rally", "bull", "record", "adopt", "approve", "inflow", "soar", "gain", "jump", "rise")
STRONG_POS = ("approve", "inflow", "record high", "all-time high", "adopt", "reserve", "rate cut")
STRONG_NEG = ("hack", "exploit", "ban ", "lawsuit", "crash", "plunge", "liquidat", "fraud", "collapse", "bankrupt", "rate hike")
NEG = ("crash", "plunge", "bear", "ban", "hack", "lawsuit", "outflow", "selloff", "sell-off", "drop", "fall", "fraud", "liquidat", "decline")

cl = lambda x, a=-1, b=1: max(a, min(b, x))
now = lambda: dt.datetime.now(dt.timezone.utc)


def get(url, data=None):
    r = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 (compatible; btc-signals/1.0)"})
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
         ("Google News", "https://news.google.com/rss/search?q=bitcoin+when:1d&hl=es-419&gl=AR&ceid=AR:es-419"),
         ("Google News Fed", "https://news.google.com/rss/search?q=federal+reserve+inflation+bitcoin+when:1d&hl=en-US&gl=US&ceid=US:en"),
         ("Google News SEC", "https://news.google.com/rss/search?q=SEC+crypto+regulation+when:1d&hl=en-US&gl=US&ceid=US:en")]
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
    w = (sum(2 for x in STRONG_POS if x in low) + sum(1 for x in POS if x in low)
         - sum(2 for x in STRONG_NEG if x in low) - sum(1 for x in NEG if x in low))
    i["w"] = max(-3, min(3, w))
    i["sent"] = (w > 0) - (w < 0)
    i["impact"] = any(x in low for x in HIGH)
    return i


def news_score(items):
    """Sentimiento ponderado por fuerza del titular y recencia (vida media 12 h, ventana 48 h)."""
    num = den = 0.0
    for i in items:
        age = (now() - dt.datetime.fromisoformat(i["ts"])).total_seconds() / 3600
        if age > 48 or not i["w"]: continue
        k = .5 ** (age / 12)
        num += i["w"] * k
        den += abs(i["w"]) * k
    return num / den if den else (0.0 if items else None)


def simulate(p, dates, fgmap, days=365, fee=.001):
    """Backtest con pesos base: con y sin filtro de tendencia, frente a comprar y mantener."""
    st = len(p) - days
    sig = []
    for i in range(st, len(p)):
        w_ = p[max(0, i - 299):i + 1]
        sc = scores(w_, fgmap.get(dates[i]))
        sig.append((combine(sc, BASE), w_[-1] < sum(w_[-200:]) / 200, sc["macd"]))

    def run(gate):
        e, inm, eq, marks = 1.0, False, [1.0], []
        for j, (s_, below, m) in enumerate(sig):
            if j:
                if inm: e *= p[st + j] / p[st + j - 1]
                eq.append(e)
            buy = s_ >= TH and not (gate and below and m < 0 and s_ < 60)
            sell = s_ <= -TH and not (gate and not below and m > 0 and s_ > -60)
            if buy and not inm: inm, e = True, e * (1 - fee); marks.append((j, "B"))
            elif sell and inm: inm, e = False, e * (1 - fee); marks.append((j, "S"))
        return eq, marks

    (eq, marks), (eq0, _) = run(True), run(False)
    hold = [x / p[st] for x in p[st:]]
    dd = lambda a: min(v / max(a[:j + 1]) - 1 for j, v in enumerate(a)) * 100
    return {"strat": round((eq[-1] - 1) * 100, 1), "strat0": round((eq0[-1] - 1) * 100, 1), "hold": round((hold[-1] - 1) * 100, 1),
            "dd_s": round(dd(eq), 1), "dd_h": round(dd(hold), 1), "trades": len(marks), "days": days}, \
        {"p": [round(x) for x in p[st:]], "m": marks, "d0": dates[st]}


def write_pwa():
    if os.path.exists("docs/icon-512.png"): return
    os.makedirs("docs", exist_ok=True)
    B = ["11110", "10001", "10001", "11110", "10001", "10001", "11110"]
    for size in (192, 512):
        c, r, cell = size / 2, size * .46, size // 11
        ox, oy = (size - 5 * cell) // 2, (size - 7 * cell) // 2
        raw = b""
        for y in range(size):
            row = bytearray([0])
            for x in range(size):
                ins = (x - c) ** 2 + (y - c) ** 2 <= r * r
                gx, gy = (x - ox) // cell, (y - oy) // cell
                white = ins and x >= ox and y >= oy and 0 <= gx < 5 and 0 <= gy < 7 and B[gy][gx] == "1"
                row += bytes((255, 255, 255, 255) if white else (247, 147, 26, 255) if ins else (0, 0, 0, 0))
            raw += bytes(row)
        ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        open(f"docs/icon-{size}.png", "wb").write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                                                + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))
    json.dump({"name": "BTC Feed", "short_name": "BTC", "start_url": "btc.html", "scope": "./", "display": "standalone",
               "background_color": "#000000", "theme_color": "#000000",
               "icons": [{"src": f"icon-{s}.png", "sizes": f"{s}x{s}", "type": "image/png"} for s in (192, 512)]},
              open("docs/manifest.json", "w"))


XW = {"rsi4h": .06, "macd4h": .06, "rsi1h": .03, "macd1h": .03, "cross": .06, "stoch": .04, "obv": .04,
      "funding": .06, "ls": .03, "oi": .03, "nasdaq": .05, "dxy": .03}


def ohlc(interval):
    d = json.loads(get(f"https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval={interval}"))["result"]
    return [[float(x) for x in r[:7]] for r in [v for k, v in d.items() if k != "last"][0]]  # t,o,h,l,c,vwap,vol


def atr(rows, n=14):
    tr = [max(r[2] - r[3], abs(r[2] - rows[i][4]), abs(r[3] - rows[i][4])) for i, r in enumerate(rows[1:])]
    a = sum(tr[:n]) / n
    for x in tr[n:]: a = (a * (n - 1) + x) / n
    return a


def daily_extras(rd):
    c = [r[4] for r in rd]
    out = {"cross": cl((ema(c, 50)[-1] / ema(c, 200)[-1] - 1) * 10)}
    hh, ll = max(r[2] for r in rd[-14:]), min(r[3] for r in rd[-14:])
    out["stoch"] = cl((.5 - (c[-1] - ll) / ((hh - ll) or 1)) * 2.5)
    obv = [0]
    for i in range(1, len(rd)): obv.append(obv[-1] + (rd[i][6] if c[i] > c[i - 1] else -rd[i][6] if c[i] < c[i - 1] else 0))
    out["obv"] = cl((obv[-1] - obv[-15]) / (sum(r[6] for r in rd[-14:]) or 1) * 3)
    return out


def extras(rd, r4, r1):
    """Filtros adicionales: otras temporalidades, cruce de medias, estocástico y volumen (OBV)."""
    out = {}
    for tag, rows in (("4h", r4), ("1h", r1)):
        try:
            s = scores([r[4] for r in rows])
            out["rsi" + tag], out["macd" + tag] = s["rsi"], s["macd"]
        except Exception as e: print("temporalidad", tag, e)
    try: out.update(daily_extras(rd))
    except Exception as e: print("diario", e)
    return out


def okx(path):
    return json.loads(get("https://www.okx.com/api/v5/" + path))["data"]


def deriv(st, p):
    """Derivados (OKX): funding, ratio largos/cortos e interés abierto. Funding y largos/cortos se leen a la contra."""
    out = {}
    try: out["funding"] = cl(-float(okx("public/funding-rate?instId=BTC-USDT-SWAP")[0]["fundingRate"]) / .0005)
    except Exception as e: print("funding", e)
    try: out["ls"] = cl(-(float(okx("rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1H")[0][1]) - 1) / .8)
    except Exception as e: print("largos/cortos", e)
    try:
        oi = float(okx("public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP")[0]["oi"])
        st["oi"] = (st.get("oi", []) + [[now().isoformat(timespec="seconds"), oi]])[-60:]
        lim = (now() - dt.timedelta(hours=24)).isoformat()
        old = [x for x in st["oi"] if x[0] <= lim]
        if old: out["oi"] = cl((oi / old[-1][1] - 1) * 20) * (1 if p[-1] >= p[-2] else -1)
    except Exception as e: print("interés abierto", e)
    return out


def yahoo(sym):
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=1d"))
    c = [x for x in j["chart"]["result"][0]["indicators"]["quote"][0]["close"] if x]
    return c[-1] / (sum(c[-20:]) / 20) - 1


def markets():
    out = {}
    try: out["nasdaq"] = cl(yahoo("%5EIXIC") * 20)
    except Exception as e: print("nasdaq", e)
    try: out["dxy"] = cl(-yahoo("DX-Y.NYB") * 60)
    except Exception as e: print("dxy", e)
    return out


LAB = {"rsi": "RSI diario", "macd": "MACD diario", "trend": "tendencia (precio vs media)", "bb": "Bandas de Bollinger",
       "fg": "Miedo/Codicia", "news": "noticias", "rsi4h": "RSI 4h", "macd4h": "MACD 4h", "rsi1h": "RSI 1h", "macd1h": "MACD 1h",
       "cross": "cruce de medias 50/200", "stoch": "estocástico", "obv": "volumen (OBV)", "funding": "funding de futuros",
       "ls": "largos/cortos", "oi": "interés abierto", "nasdaq": "Nasdaq", "dxy": "dólar (DXY)"}


def explain(sc, W, score, action, raw, why):
    """Explicación corta de por qué se tomó la decisión."""
    top = sorted(sc, key=lambda k: abs(sc[k] * W[k]), reverse=True)[:3]
    pro = ", ".join(f"{LAB[k]} ({'compra' if sc[k] > 0 else 'venta'})" for k in top)
    nb, ns = sum(v >= .2 for v in sc.values()), sum(v <= -.2 for v in sc.values())
    t = f"Puntuación {score:+d} (umbral ±{TH}): {nb} filtros a favor de comprar y {ns} de vender. Pesan más: {pro}."
    if why: t += f" La señal de {raw.lower()} se bloqueó por: {'; '.join(why)}."
    elif action == "ESPERAR": t += " No llega al umbral, por eso espera."
    return t


def compare(rd, p, dates, fgmap, days=365, fee=.001):
    """Prueba cada variante sobre los mismos días: total, 1ª mitad, 2ª mitad, caída máxima y operaciones."""
    st = len(p) - days
    A, X = [], []
    for i in range(st, len(p)):
        w_, r_ = p[max(0, i - 299):i + 1], rd[max(0, i - 299):i + 1]
        sc = scores(w_, fgmap.get(dates[i]))
        below, m = w_[-1] < sum(w_[-200:]) / 200, sc["macd"]
        A.append((combine(sc, BASE), below, m))
        X.append((combine({**sc, **daily_extras(r_)}, {**BASE, **XW}), below, m))
    S = [(-100 if b else 100, b, m) for _, b, m in A]

    def run(sig, gate):
        e, inm, eq, n = 1.0, False, [1.0], 0
        for j, (s_, below, m) in enumerate(sig):
            if j:
                if inm: e *= p[st + j] / p[st + j - 1]
                eq.append(e)
            buy = s_ >= TH and not (gate and below and m < 0 and s_ < 60)
            sell = s_ <= -TH and not (gate and not below and m > 0 and s_ > -60)
            if buy and not inm: inm, e, n = True, e * (1 - fee), n + 1
            elif sell and inm: inm, e, n = False, e * (1 - fee), n + 1
        return eq, n

    def stat(name, eq, n):
        mid = len(eq) // 2
        dd = min(v / max(eq[:j + 1]) - 1 for j, v in enumerate(eq)) * 100
        return {"name": name, "ret": round((eq[-1] - 1) * 100, 1), "h1": round((eq[mid] / eq[0] - 1) * 100, 1),
                "h2": round((eq[-1] / eq[mid] - 1) * 100, 1), "dd": round(dd, 1), "n": n}

    out = [stat(nm, *run(sg, g)) for nm, sg, g in (("Base", A, False), ("Base + tendencia", A, True), ("Base + extras", X, False),
                                                    ("Extras + tendencia", X, True), ("Solo SMA200", S, False))]
    return out + [stat("Mantener", [x / p[st] for x in p[st:]], 0)]


def load_log():
    try: return json.load(open("docs/signals.json"))
    except Exception: return []


def learn_extras(L):
    """Pesos de los filtros nuevos según sus aciertos a 24 h en el registro real (mínimo 40 casos)."""
    stt = {}
    for i, e in enumerate(L):
        t = dt.datetime.fromisoformat(e["ts"]) + dt.timedelta(hours=24)
        f = next((x for x in L[i + 1:] if dt.datetime.fromisoformat(x["ts"]) >= t), None)
        if not f or "sc" not in e: continue
        ret = f["price"] / e["price"] - 1
        for k, s in e["sc"].items():
            if k in XW and abs(s) >= .2:
                n_, h_ = stt.get(k, (0, 0))
                stt[k] = (n_ + 1, h_ + ((s > 0) == (ret > 0)))
    w, info = dict(XW), {}
    for k, (n_, h_) in stt.items():
        info[k] = (round(h_ / n_ * 100), n_)
        if n_ >= 40: w[k] = XW[k] * max(.25, min(1.75, 1 + 4 * (h_ / n_ - .5)))
    return w, info


def gates(raw, score, rd, items, sc):
    """Filtros que bloquean el aviso: contra tendencia, volatilidad extrema y ráfaga de noticias."""
    why, c = [], [r[4] for r in rd]
    sma200 = sum(c[-200:]) / 200
    if raw == "COMPRAR" and c[-1] < sma200 and sc.get("macd", 0) < 0 and score < 60:
        why.append("tendencia bajista (bajo SMA200 y MACD negativo)")
    if raw == "VENDER" and c[-1] > sma200 and sc.get("macd", 0) > 0 and score > -60:
        why.append("tendencia alcista (sobre SMA200 y MACD positivo)")
    trp = [max(r[2] - r[3], abs(r[2] - rd[i][4]), abs(r[3] - rd[i][4])) / r[4] for i, r in enumerate(rd[1:])]
    if raw != "ESPERAR" and sum(trp[-3:]) / 3 > 2 * sum(trp[-90:]) / 90: why.append("volatilidad extrema")
    lim = (now() - dt.timedelta(hours=6)).isoformat()
    if raw != "ESPERAR" and sum(1 for i in items if i["impact"] and i["ts"] >= lim) >= 3:
        why.append("ráfaga de noticias de alto impacto")
    return why


def norm(t):
    return re.sub(r"[^a-z0-9]", "", re.sub(r" - [^-]{2,30}$", "", t.lower()))[:55]


def log_signal(price, score, action, det, sc, why, expl):
    """Una señal cada 2 horas (docs/signals.json), para el registro por días."""
    os.makedirs("docs", exist_ok=True)
    L = load_log()
    n = now()
    slot = n.strftime("%Y-%m-%d") + str(n.hour // 2)
    if not L or L[-1].get("slot") != slot:
        e = {"slot": slot, "ts": n.isoformat(timespec="seconds"), "price": round(price), "score": score,
             "action": action, "det": det, "expl": expl, "sc": {k: round(v, 2) for k, v in sc.items()}}
        if why: e["gate"] = "; ".join(why)
        L.append(e)
    json.dump(L[-400:], open("docs/signals.json", "w"), ensure_ascii=False)


def write_feed(items, pulse, sigs):
    os.makedirs("docs", exist_ok=True)
    try: old = json.load(open("docs/feed.json"))["items"]
    except Exception: old = []
    d = {i["id"]: i for i in old + items + sigs}
    allv, keys = [], set()
    for i in sorted(d.values(), key=lambda i: i["ts"], reverse=True):
        k = i["id"] if i["type"] == "signal" else norm(i["text"])
        if k not in keys: keys.add(k); allv.append(i)
    allv = allv[:300]
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
    rd = ohlc(1440)
    p = [r[4] for r in rd]
    dates = [dt.datetime.fromtimestamp(r[0], dt.timezone.utc).strftime("%Y-%m-%d") for r in rd]
    try: r4, r1 = ohlc(240), ohlc(60)
    except Exception as e: r4, r1 = [], []; print("OHLC intradía", e)
    fgmap = fng()
    w, info = recalibrate(p, dates, fgmap)
    fg = fgmap.get(dates[-1], next(iter(fgmap.values())) if fgmap else None)
    items = [enrich(i) for i in fetch_news()]
    try: st = json.load(open(STATE))
    except Exception: st = {"last": "ESPERAR", "history": []}
    sc = scores(p, fg, news_score(items))
    sc.update(extras(rd, r4, r1))
    sc.update(deriv(st, p))
    sc.update(markets())
    xw, xinfo = learn_extras(load_log())
    score = combine(sc, {**w, **xw})
    raw = "COMPRAR" if score >= TH else "VENDER" if score <= -TH else "ESPERAR"
    why = gates(raw, score, rd, items, sc)
    action = "ESPERAR" if why else raw
    st["history"].append({"ts": now().isoformat(timespec="seconds"), "price": p[-1], "score": score, "action": action})
    st["history"] = st["history"][-4000:]
    evaluate(st["history"])

    det = " | ".join(f"{k} {v:+.2f}" for k, v in sc.items())
    sigs, ts0 = [], st["history"][-1]["ts"]
    log_signal(p[-1], score, action, det, sc, why, explain(sc, {**w, **xw}, score, action, raw, why))
    if action != st.get("last"):
        sigs.append({"id": "sig-" + ts0, "type": "signal", "source": "Señales BTC", "action": action, "detail": det,
                     "text": f"{action}" + (f" (señal {raw} bloqueada: {'; '.join(why)})" if why else "") + f" · puntuación {score} · BTC {p[-1]:,.0f} USD", "ts": ts0})
        if action != "ESPERAR":
            a, px = atr(rd), p[-1]
            lv = (f"Stop sugerido {px - 2 * a:,.0f} · objetivo {px + 3 * a:,.0f}" if action == "COMPRAR"
                  else f"Invalidación sobre {px + 2 * a:,.0f} · objetivo bajista {px - 3 * a:,.0f}")
            telegram(f"{'🟢' if action == 'COMPRAR' else '🔴'} {action} BTC\nPrecio {px:,.0f} USD · puntuación {score}\n{lv} (ATR diario)\n{det}")
    st["last"] = action

    n = now()
    if n.weekday() == 0 and n.hour == 7:
        tot, ok = accuracy(st["history"])
        live = f"{ok}/{tot} avisos acertados a {H} días" if tot else "aún sin avisos evaluables"
        ws = ", ".join(f"{k} {v * 100:.0f}%" for k, v in w.items())
        hi = ", ".join(f"{k} {h}% ({c})" for k, (h, c) in info.items())
        xi = ", ".join(f"{k} {h}% ({c})" for k, (h, c) in xinfo.items()) or "aún sin datos"
        telegram(f"📊 Informe semanal BTC\nPrecio {p[-1]:,.0f} · puntuación {score} ({action})\nAciertos en vivo: {live}\n"
                 f"Aciertos históricos por indicador: {hi}\nPesos actuales: {ws}\nFiltros nuevos a 24 h: {xi}")
    try: seen = {i["id"] for i in json.load(open("docs/feed.json"))["items"]}
    except Exception: seen = None
    if seen is not None:
        for i in [x for x in items if x["impact"] and x["id"] not in seen][:3]:
            telegram(f"⚡ {i['source']}: {i['text']}\n{i['link']}")
    tot, ok = accuracy(st["history"])
    sim, chart = simulate(p, dates, fgmap)
    try: variants = compare(rd, p, dates, fgmap)
    except Exception as e: variants = []; print('comparativa', e)
    write_pwa()
    write_feed(items, {"cmp": variants, "gates": why, "sim": sim, "chart": chart, "price": p[-1], "score": score, "action": action, "fg": fg, "acc": [tot, ok],
                       "weights": {k: round(v, 3) for k, v in w.items()}}, sigs)
    st["weights"] = {k: round(v, 3) for k, v in w.items()}
    json.dump(st, open(STATE, "w"), indent=1)
    print(action, score, st["weights"])


if __name__ == "__main__":
    main()
