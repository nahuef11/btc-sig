#!/usr/bin/env python3
"""Señales BTC: técnicos + Fear & Greed + noticias. Avisa por Telegram y se recalibra solo."""
import json, os, re, math, zlib, struct, time, base64, hmac, hashlib, urllib.request, urllib.parse, datetime as dt
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


def write_candles(*sets):
    """Velas (diario, 4h, 1h, 15m) para el gráfico de la app."""
    os.makedirs("docs", exist_ok=True)
    out = {k: [[int(r[0]), round(r[1], 1), round(r[2], 1), round(r[3], 1), round(r[4], 1), round(r[6], 1)] for r in rows[-300:]]
           for k, rows in zip(("c1440", "c240", "c60", "c15"), sets) if rows}
    json.dump(out, open("docs/candles.json", "w"), separators=(",", ":"))


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


PHR = {
    "rsi": ("el precio ha caído mucho y es probable un rebote", "el precio ha subido mucho y puede corregir"),
    "macd": ("el impulso del precio es alcista", "el impulso del precio es bajista"),
    "trend": ("el precio está por encima de su tendencia media", "el precio está por debajo de su tendencia media"),
    "bb": ("el precio está en la parte baja de su rango habitual", "el precio está en la parte alta de su rango habitual"),
    "fg": ("el mercado tiene miedo, y eso suele ser buena zona para comprar", "el mercado está eufórico, y eso suele ser zona de riesgo"),
    "news": ("las noticias recientes son positivas", "las noticias recientes son negativas"),
    "rsi4h": ("a corto plazo (4 horas) el precio parece barato", "a corto plazo (4 horas) el precio parece caro"),
    "macd4h": ("el impulso de las últimas horas es alcista", "el impulso de las últimas horas es bajista"),
    "rsi1h": ("en la última hora el precio parece barato", "en la última hora el precio parece caro"),
    "macd1h": ("el impulso de la última hora es alcista", "el impulso de la última hora es bajista"),
    "cross": ("la tendencia de fondo es alcista", "la tendencia de fondo es bajista"),
    "stoch": ("el precio está cerca de sus mínimos recientes", "el precio está cerca de sus máximos recientes"),
    "obv": ("el volumen acompaña a las subidas", "el volumen acompaña a las bajadas"),
    "funding": ("hay más apuestas a la baja que a la subida con apalancamiento, algo que suele preceder a rebotes",
                "hay demasiadas apuestas a la subida con apalancamiento, con riesgo de caída brusca"),
    "ls": ("hay más inversores en corto que en largo, algo que suele preceder a rebotes",
           "hay muchos más inversores en largo que en corto, con el mercado saturado de compradores"),
    "oi": ("entra dinero nuevo acompañando la subida", "entra dinero nuevo apostando a la baja"),
    "nasdaq": ("la bolsa tecnológica está fuerte, lo que suele ayudar a BTC", "la bolsa tecnológica está débil, lo que suele lastrar a BTC"),
    "dxy": ("el dólar está débil, favorable para BTC", "el dólar está fuerte, desfavorable para BTC"),
}


def explain(sc, W, score, action, raw, why, short=False):
    """Explicación en lenguaje claro de por qué se tomó la decisión (sin cifras)."""
    order = sorted(sc, key=lambda k: -abs(sc[k] * W[k]))
    up = [k for k in order if sc[k] >= .2 and k in PHR]
    down = [k for k in order if sc[k] <= -.2 and k in PHR]
    if why: head = f"Había señal de {'compra' if raw == 'COMPRAR' else 'venta'}, pero se prefiere esperar porque {'; '.join(why)}."
    elif action == "COMPRAR": head = "Se recomienda comprar: la mayoría de las señales apuntan al alza."
    elif action == "VENDER": head = "Se recomienda vender: la mayoría de las señales apuntan a la baja."
    else: head = "Se recomienda esperar: las señales no son lo bastante claras y se contradicen."
    nu, nd = (3, 1) if action == "COMPRAR" else (1, 3) if action == "VENDER" else (2, 2)
    if short: nu, nd = (2, 1) if action == "COMPRAR" else (1, 2) if action == "VENDER" else (1, 1)
    t = head
    if up: t += " Apuntan al alza: " + "; ".join(PHR[k][0] for k in up[:nu]) + "."
    if down: t += " Apuntan a la baja: " + "; ".join(PHR[k][1] for k in down[:nd]) + "."
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
        why.append("el mercado está en tendencia bajista y comprar contra la tendencia es arriesgado")
    if raw == "VENDER" and c[-1] > sma200 and sc.get("macd", 0) > 0 and score > -60:
        why.append("el mercado está en tendencia alcista y vender contra la tendencia puede hacerte perder subidas")
    trp = [max(r[2] - r[3], abs(r[2] - rd[i][4]), abs(r[3] - rd[i][4])) / r[4] for i, r in enumerate(rd[1:])]
    if raw != "ESPERAR" and sum(trp[-3:]) / 3 > 2 * sum(trp[-90:]) / 90: why.append("el mercado está demasiado agitado ahora mismo")
    lim = (now() - dt.timedelta(hours=6)).isoformat()
    if raw != "ESPERAR" and sum(1 for i in items if i["impact"] and i["ts"] >= lim) >= 3:
        why.append("hay una ráfaga de noticias importantes y conviene esperar a que se calme")
    return why


def norm(t):
    return re.sub(r"[^a-z0-9]", "", re.sub(r" - [^-]{2,30}$", "", t.lower()))[:55]


def log_signal(price, score, action, sc, why, expl, lv=None):
    """Una señal por hora (docs/signals.json). La app permite verlas cada 1, 2, 4, 6 o 12 h."""
    os.makedirs("docs", exist_ok=True)
    L = load_log()
    n = now()
    slot = n.strftime("%Y-%m-%d") + str(n.hour)
    if not L or L[-1].get("slot") != slot:
        e = {"slot": slot, "ts": n.isoformat(timespec="seconds"), "price": round(price), "score": score,
             "action": action, "expl": expl, "sc": {k: round(v, 1) for k, v in sc.items()}}
        if why: e["gate"] = "; ".join(why)
        if lv: e["lv"] = {k: round(v) for k, v in lv.items()}
        L.append(e)
    L = L[-480:]
    for e in L[:-240]:
        e.pop("sc", None); e.pop("expl", None); e.pop("det", None)
    json.dump(L, open("docs/signals.json", "w"), ensure_ascii=False)


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


def telegram(text, chat=None):
    tok, chat = os.getenv("TELEGRAM_TOKEN"), chat or os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print(text); return
    try:
        get(f"https://api.telegram.org/bot{tok}/sendMessage",
            urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode())
    except Exception as e: print("Telegram falló:", e)


def admin(text):
    """Informes y alertas de noticias: solo a tu chat personal (TELEGRAM_ADMIN_CHAT_ID), nunca al canal."""
    chat = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
    if chat: telegram(text, chat)
    else: print(text)


def telegram_photo(path, caption):
    tok, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print(caption); return
    b = "----btc" + os.urandom(8).hex()
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in (("chat_id", chat), ("caption", caption[:1020]))]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="btc.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
                 + open(path, "rb").read() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendPhoto", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    urllib.request.urlopen(req, timeout=60)


def make_chart(path, rows, action, price, lv, log):
    """Velas de 4 h con EMA50, líneas de tendencia (soporte/resistencia), flechas de señales y stop/objetivo."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    R = rows[-90:]
    n = len(R)
    BG, FG, UP, DN = "#0f1115", "#e7e9ea", "#16c784", "#ea3943"
    buy = action == "COMPRAR"
    if action:
        lines = [(lv["sl"], DN, "-", f"SL fut {lv['sl']:,.0f}"), (lv["tp1"], UP, "-", f"TP1 {lv['tp1']:,.0f}"),
                 (lv["tp2"], UP, "-", f"TP2 {lv['tp2']:,.0f}"),
                 (lv["stop_spot"], DN, ":", f"Stop spot {lv['stop_spot']:,.0f}"), (lv["obj_spot"], UP, ":", f"Obj. spot {lv['obj_spot']:,.0f}")]
    else:
        lines = [(lv["sup"], UP, ":", f"Soporte {lv['sup']:,.0f}"), (lv["res"], DN, ":", f"Resistencia {lv['res']:,.0f}")]
    ys = [l[0] for l in lines]
    lo, hi = min(min(r[3] for r in R), *ys), max(max(r[2] for r in R), *ys)
    off = (hi - lo) * .05
    fig, ax = plt.subplots(figsize=(10, 6), dpi=100, facecolor=BG)
    ax.set_facecolor(BG)
    for i, r in enumerate(R):
        col = UP if r[4] >= r[1] else DN
        ax.vlines(i, r[3], r[2], color=col, linewidth=1)
        ax.bar(i, max(abs(r[4] - r[1]), (hi - lo) * .002), bottom=min(r[1], r[4]), width=.65, color=col)
    ax.plot(range(n), ema([r[4] for r in rows], 50)[-n:], color="#f5c542", lw=1.2, label="EMA 50")
    for key, col, name in ((3, UP, "Soporte"), (2, DN, "Resistencia")):
        f = max if key == 2 else min
        ps = [i for i in range(4, n - 4) if R[i][key] == f(R[j][key] for j in range(i - 4, i + 5))][-2:]
        if len(ps) == 2:
            (x1, x2), (y1, y2) = ps, (R[ps[0]][key], R[ps[1]][key])
            m = (y2 - y1) / (x2 - x1)
            ax.plot([x1, n + 4], [y1, y1 + m * (n + 4 - x1)], color=col, ls="--", lw=1.5, alpha=.85, label=name)
    prev = None
    for e in sorted(log, key=lambda e: e["ts"]):
        ch, prev = e["action"] != prev, e["action"]
        if not ch or e["action"] == "ESPERAR": continue
        t = dt.datetime.fromisoformat(e["ts"]).timestamp()
        idx = max((i for i in range(n) if R[i][0] <= t), default=None)
        if idx is None or idx >= n - 1: continue
        b_ = e["action"] == "COMPRAR"
        ax.scatter(idx, R[idx][3] - off * .8 if b_ else R[idx][2] + off * .8, marker="^" if b_ else "v", s=110,
                   color=UP if b_ else DN, zorder=5)
    if action:
        x, c = n - 1, UP if buy else DN
        ax.annotate(action, xy=(x, R[-1][3] - off * .2 if buy else R[-1][2] + off * .2),
                    xytext=(x, R[-1][3] - off * 2.4 if buy else R[-1][2] + off * 2.4), ha="center", va="top" if buy else "bottom",
                    color=c, fontsize=11, fontweight="bold", arrowprops=dict(arrowstyle="-|>", color=c, lw=3, mutation_scale=22))
    for y, col, ls, lab in lines:
        ax.hlines(y, n - 14, n + 4, color=col, ls=ls, lw=1.2)
        ax.text(n + 4.5, y, lab, color=col, fontsize=8, va="center")
    ax.set_xlim(-1, n + 19)
    ax.set_ylim(lo - off * 3.2, hi + off * 3.2)
    ticks = list(range(0, n, 15))
    ax.set_xticks(ticks)
    ax.set_xticklabels([dt.datetime.fromtimestamp(R[i][0], dt.timezone.utc).strftime("%d/%m") for i in ticks])
    ax.yaxis.tick_right()
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.tick_params(colors="#8899a6")
    ax.grid(color="#1f2328", lw=.6)
    for sp in ax.spines.values(): sp.set_color("#2f3336")
    ax.set_title(f"BTC/USD · 4h · {action} a ${price:,.0f}" if action else f"BTC/USD · 4h · Informe · ${price:,.0f}", color=FG, fontsize=14, loc="left")
    ax.legend(loc="upper left", facecolor=BG, edgecolor="none", labelcolor=FG, fontsize=9)
    fig.text(.01, .01, "Información orientativa · no es asesoramiento financiero", color="#8899a6", fontsize=8)
    fig.savefig(path, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


def oauth1(method, url, ck, cs, tk, ts):
    q = lambda v: urllib.parse.quote(str(v), safe="~")
    p = {"oauth_consumer_key": ck, "oauth_nonce": os.urandom(16).hex(), "oauth_signature_method": "HMAC-SHA1",
         "oauth_timestamp": str(int(time.time())), "oauth_token": tk, "oauth_version": "1.0"}
    base = "&".join([method, q(url), q("&".join(f"{q(k)}={q(v)}" for k, v in sorted(p.items())))])
    p["oauth_signature"] = base64.b64encode(hmac.new(f"{q(cs)}&{q(ts)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(p.items()))


def x_post(text, image=None):
    """Publica en X (cuenta del bot). Sin enlaces en el texto: en X de pago por uso un post con URL cuesta mucho más."""
    keys = [os.getenv(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")]
    if not all(keys):
        print("X (sin configurar):", text); return
    try:
        media = None
        if image:
            b = "----x" + os.urandom(8).hex()
            body = (f'--{b}\r\nContent-Disposition: form-data; name="media"; filename="btc.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
                    + open(image, "rb").read() + f"\r\n--{b}--\r\n".encode())
            for host in ("upload.x.com", "upload.twitter.com"):
                url = f"https://{host}/1.1/media/upload.json"
                try:
                    req = urllib.request.Request(url, data=body, headers={"Authorization": oauth1("POST", url, *keys),
                                                 "Content-Type": f"multipart/form-data; boundary={b}"})
                    media = json.loads(urllib.request.urlopen(req, timeout=60).read())["media_id_string"]
                    break
                except Exception as e: print("Subida de imagen a X falló:", host, e)
        data = {"text": text}
        if media: data["media"] = {"media_ids": [media]}
        url = "https://api.x.com/2/tweets"
        req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                     headers={"Authorization": oauth1("POST", url, *keys), "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30)
    except Exception as e: print("X falló:", e)


def key_levels(rows, price):
    R = rows[-120:]
    n = len(R)
    lows = [R[i][3] for i in range(3, n - 3) if R[i][3] == min(R[j][3] for j in range(i - 3, i + 4))]
    highs = [R[i][2] for i in range(3, n - 3) if R[i][2] == max(R[j][2] for j in range(i - 3, i + 4))]
    return (max([x for x in lows if x < price], default=min(r[3] for r in R)),
            min([x for x in highs if x > price], default=max(r[2] for r in R)))


def fg_word(v):
    return "miedo extremo" if v < 25 else "miedo" if v < 45 else "neutral" if v < 55 else "codicia" if v < 75 else "codicia extrema"


def top_reason(sc, W, action):
    g = 1 if action == "COMPRAR" else -1
    ks = [k for k in sc if sc[k] * g >= .2 and k in PHR]
    return PHR[max(ks, key=lambda k: abs(sc[k] * W.get(k, 0)))][0 if g > 0 else 1] if ks else None


def learn_update(st, L):
    """Estadística acumulada de aciertos por filtro a 24 h sobre el registro real, con olvido gradual (≈ 2 meses)."""
    ls = st.setdefault("learn", {"ptr": "", "s": {}})
    lim = (now() - dt.timedelta(hours=24)).isoformat()
    for i, e in enumerate(L):
        if e["ts"] <= ls["ptr"] or e["ts"] > lim or "sc" not in e: continue
        t = dt.datetime.fromisoformat(e["ts"]) + dt.timedelta(hours=24)
        f = next((x for x in L[i + 1:] if dt.datetime.fromisoformat(x["ts"]) >= t), None)
        if not f: continue
        ret = f["price"] / e["price"] - 1
        for k, s_ in e["sc"].items():
            if abs(s_) >= .2:
                a = ls["s"].setdefault(k, [0.0, 0.0])
                a[0] = a[0] * .999 + 1
                a[1] = a[1] * .999 + ((s_ > 0) == (ret > 0))
        ls["ptr"] = e["ts"]
    return ls


def learn_mult(ls):
    """Multiplicador de peso por filtro según sus aciertos reales (los nuevos más sensibles que los clásicos)."""
    mult, info = {}, {}
    for k, (n_, h_) in ls["s"].items():
        if n_ < 1: continue
        hr = h_ / n_
        info[k] = (round(hr * 100), round(n_))
        if k in XW and n_ >= 40: mult[k] = max(.25, min(1.75, 1 + 4 * (hr - .5)))
        elif k in BASE and n_ >= 60: mult[k] = max(.6, min(1.4, 1 + 2 * (hr - .5)))
    return mult, info


def log_mult(st, mult):
    prev, lg = st.get("mult", {}), st.setdefault("learn_log", [])
    for k, m in mult.items():
        if k in LAB and abs(m - prev.get(k, 1)) >= .25:
            lg.append({"ts": now().isoformat(timespec="seconds"),
                       "text": f"Peso de «{LAB[k]}» {'subido' if m > prev.get(k, 1) else 'bajado'} según sus aciertos recientes"})
    st["mult"] = mult


def tune_threshold(p, dates, fgmap, th, fee=.002, days=400, h=7):
    """Prueba umbrales sobre el pasado (pesos base): elige en el 70 % inicial y lo comprueba en el 30 % final. Máx. un escalón."""
    sc_ = []
    for i in range(max(200, len(p) - h - days), len(p) - h):
        sc_.append((combine(scores(p[max(0, i - 299):i + 1], fgmap.get(dates[i])), BASE), p[i + h] / p[i] - 1))
    cut = int(len(sc_) * .7)

    def ev(rows_, t):
        r = [(1 if s_ >= t else -1) * ret - fee for s_, ret in rows_ if abs(s_) >= t]
        return (sum(r) / len(r), len(r)) if r else (0.0, 0)

    best = None
    for t in (25, 30, 35, 40, 45):
        (mt, nt), (me, ne) = ev(sc_[:cut], t), ev(sc_[cut:], t)
        if nt >= 15 and ne >= 8 and (best is None or mt > best[1]): best = (t, mt, me)
    if best and best[0] != th and best[2] > ev(sc_[cut:], th)[0] + .002 and best[2] > 0:
        return max(25, min(45, th + (5 if best[0] > th else -5)))
    return th


def live_record(L):
    """Aciertos de las señales reales (cambios de estado) completadas en los últimos 30 días."""
    ch, prev = [], None
    for e in sorted(L, key=lambda e: e["ts"]):
        if e["action"] != prev: ch.append(e); prev = e["action"]
    lim, ok, tot = (now() - dt.timedelta(days=30)).isoformat(), 0, 0
    for i, e in enumerate(ch[:-1]):
        if e["ts"] < lim: continue
        nx = ch[i + 1]
        mv = nx["price"] / e["price"] - 1
        d = (dt.datetime.fromisoformat(nx["ts"]) - dt.datetime.fromisoformat(e["ts"])).total_seconds() / 86400
        ok += (mv > 0) if e["action"] == "COMPRAR" else (mv < 0) if e["action"] == "VENDER" else abs(mv) < .015 * math.sqrt(max(1, d))
        tot += 1
    return ok, tot


def adjust_threshold(st, p, dates, fgmap, L):
    lg = st.setdefault("learn_log", [])

    def note(t):
        lg.append({"ts": now().isoformat(timespec="seconds"), "text": t})
        admin("🧠 " + t)

    th, last = st.get("th", 35), st.get("th_ts", "")
    if not last or now() - dt.datetime.fromisoformat(last) >= dt.timedelta(days=7):
        try: new = tune_threshold(p, dates, fgmap, th)
        except Exception as e: print("ajuste de umbral", e); new = th
        st["th_ts"] = now().isoformat(timespec="seconds")
        if new != th: note(f"Umbral de aviso {'subido' if new > th else 'bajado'} de {th} a {new} tras comprobarlo en datos pasados")
        st["th"] = new
    ok, tot = live_record(L)
    c = st.get("caution", False)
    if tot >= 8 and ok / tot < .45 and not c:
        st["caution"] = True; note(f"Modo cautela activado: solo {ok} de {tot} señales recientes acertaron")
    elif tot >= 8 and ok / tot >= .52 and c:
        st["caution"] = False; note("Modo cautela desactivado: los aciertos recientes se han recuperado")
    st["rec30"] = [ok, tot]
    st["learn_log"] = lg[-10:]


def learn_view(st, info):
    rank = sorted(((k, h, n) for k, (h, n) in info.items() if n >= 30 and k in LAB), key=lambda t: -t[1])
    nm = lambda t: f"{LAB[t[0]]} ({t[1]} %)"
    return {"th": st.get("th", 35), "caution": bool(st.get("caution")), "rec": st.get("rec30", [0, 0]),
            "best": [nm(t) for t in rank[:3]], "worst": [nm(t) for t in rank[-3:][::-1]] if len(rank) > 3 else [],
            "log": st.get("learn_log", [])[-5:], "samples": max((n for _, (h, n) in info.items()), default=0)}


def build_report(sc, W, score, p, rd, r4, items, fg, why, caution=False):
    """Informe de mercado en lenguaje claro (no es una señal)."""
    rows, price = r4 or rd, p[-1]
    chg = (r4[-1][4] / r4[-7][4] - 1) * 100 if len(r4) > 7 else (p[-1] / p[-2] - 1) * 100
    sup, res = key_levels(rows, price)
    bias = ("claramente alcista" if score >= 35 else "ligeramente alcista" if score >= 15 else "neutral, con señales que se compensan"
            if score > -15 else "ligeramente bajista" if score > -35 else "claramente bajista")
    cr = sc.get("cross", 0)
    trend = "alcista" if cr > .2 else "bajista" if cr < -.2 else "poco definida"
    mom = sc.get("macd4h")
    mom_t = "" if mom is None else ", y a corto plazo el impulso es " + ("alcista" if mom > .2 else "bajista" if mom < -.2 else "mixto")
    ctx = [PHR[k][0 if sc[k] > 0 else 1] for k in sorted((k for k in ("funding", "ls", "oi", "nasdaq", "dxy") if k in sc and abs(sc[k]) >= .3),
                                                         key=lambda k: -abs(sc[k] * W.get(k, 0)))[:2]]
    nw_ = sc.get("news")
    tone = "" if nw_ is None else "positivas" if nw_ > .2 else "negativas" if nw_ < -.2 else "mixtas"
    hl = next((i for i in sorted(items, key=lambda i: i["ts"], reverse=True) if i["impact"]), None)
    mood = (f"Ánimo del mercado: {fg_word(fg)}" if fg is not None else "") + (f"; noticias {tone}" if tone else "") + "."
    t = [f"Precio: ${price:,.0f} ({chg:+.1f} % en 24 h)", "",
         f"Sesgo {bias}. La tendencia de fondo es {trend}{mom_t}.", mood]
    if ctx: t.append("Contexto: " + "; ".join(ctx) + ".")
    t.append(f"Niveles clave: soporte {sup:,.0f} · resistencia {res:,.0f}")
    if hl: t.append(f"Titular a vigilar ({hl['source']}): {hl['text'][:110]}")
    if why: t.append("Ojo: " + why[0] + ".")
    if caution: t.append("Modo cautela activo: las señales recientes han acertado poco, así que solo se avisa con señales más fuertes.")
    t += ["", "ℹ️ Esto no es una señal de compra o venta. Información orientativa, no es asesoramiento financiero."]
    short = (f"📊 BTC · ${price:,.0f} ({chg:+.1f} % 24 h)\nSesgo {bias.split(',')[0]}, tendencia de fondo {trend}.\n"
             f"Soporte {sup:,.0f} · Resistencia {res:,.0f}\n" + (f"Ánimo: {fg_word(fg)}\n" if fg is not None else "")
             + "No es asesoramiento financiero #BTC")
    return {"text": "\n".join(t), "short": short[:280], "levels": {"sup": sup, "res": res}, "price": price}


def publish_report(rep, rows, label, test=False):
    cap = (("🧪 PRUEBA del canal (no es un informe real)\n\n" if test else "") + f"📊 Informe BTC · {label}\n" + rep["text"])[:1020]
    img = None
    try:
        make_chart("report.png", rows, None, rep["price"], rep["levels"], load_log())
        img = "report.png"
    except Exception as e: print("Gráfico del informe falló:", e)
    try:
        telegram_photo(img, cap) if img else telegram(cap)
    except Exception as e:
        print("Telegram falló:", e); telegram(cap)
    x_post(("🧪 PRUEBA\n" if test else "") + rep["short"], img)


def x_signal_text(action, price, lv, reason, test=False):
    long_ = action == "COMPRAR"
    t = [f"{'🟢' if long_ else '🔴'} {action} BTC · ${price:,.0f}"]
    if reason: t.append(reason[0].upper() + reason[1:] + ".")
    t += [f"Spot: {'stop' if long_ else 'invalidación'} {lv['stop_spot']:,.0f} · obj. {lv['obj_spot']:,.0f}",
          f"{'LONG' if long_ else 'SHORT'}: stop {lv['sl']:,.0f} · TP {lv['tp1']:,.0f}/{lv['tp2']:,.0f}",
          "⚠️ No es asesoramiento financiero #BTC"]
    if test: t.insert(0, "🧪 PRUEBA")
    s = "\n".join(t)
    return s if len(s) <= 270 else "\n".join(t[:1] + t[2:])[:280]


def levels(action, price, a, a4):
    """Niveles: spot con el rango diario (stop 2x, objetivo 3x) y futuros con el de 4 h (stop 1,5x, objetivos 2x y 3,5x)."""
    g = 1 if action == "COMPRAR" else -1
    return {"stop_spot": price - g * 2 * a, "obj_spot": price + g * 3 * a,
            "sl": price - g * 1.5 * a4, "tp1": price + g * 2 * a4, "tp2": price + g * 3.5 * a4,
            "lev": max(1, min(5, int(1 / (2 * 1.5 * a4 / price))))}  # liquidación al menos al doble de distancia que el stop


def publish_signal(action, price, a, expl, rows, test=False, real=None, reason=None):
    lv = levels(action, price, a, atr(rows))
    long_ = action == "COMPRAR"
    spot = (f"📈 Spot: comprar · stop {lv['stop_spot']:,.0f} · objetivo {lv['obj_spot']:,.0f}" if long_
            else f"📉 Spot: vender o salir · invalidación sobre {lv['stop_spot']:,.0f} · objetivo bajista {lv['obj_spot']:,.0f}")
    fut = (f"⚡ Futuros: {'LONG' if long_ else 'SHORT'} · stop {lv['sl']:,.0f} · objetivos {lv['tp1']:,.0f} / {lv['tp2']:,.0f} · "
           f"apalancamiento máx. sugerido {lv['lev']}x")
    cap = ((f"🧪 PRUEBA del canal (no es una señal real; ahora mismo la señal es {real})\n\n" if test else "")
           + f"{'🟢' if long_ else '🔴'} {action} BTC · ${price:,.0f}\n\n{expl}\n\n{spot}\n{fut}\n\n"
           "⚠️ Información orientativa, no es asesoramiento financiero. Los futuros con apalancamiento pueden liquidarte: "
           "arriesga como máximo el 1-2 % de tu capital por operación.")
    img = None
    try:
        make_chart("chart.png", rows, action, price, lv, load_log())
        img = "chart.png"
    except Exception as e: print("Gráfico falló:", e)
    try:
        telegram_photo(img, cap) if img else telegram(cap)
    except Exception as e:
        print("Telegram falló:", e); telegram(cap)
    x_post(x_signal_text(action, price, lv, reason, test), img)


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
    global TH
    rd = ohlc(1440)
    p = [r[4] for r in rd]
    dates = [dt.datetime.fromtimestamp(r[0], dt.timezone.utc).strftime("%Y-%m-%d") for r in rd]
    try: r4, r1 = ohlc(240), ohlc(60)
    except Exception as e: r4, r1 = [], []; print("OHLC intradía", e)
    try: r15 = ohlc(15)
    except Exception as e: r15 = []; print("OHLC 15m", e)
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
    L0 = load_log()
    mult, xinfo = learn_mult(learn_update(st, L0))
    log_mult(st, mult)
    w = {k: v * mult.get(k, 1) for k, v in w.items()}
    xw = {k: v * mult.get(k, 1) for k, v in XW.items()}
    adjust_threshold(st, p, dates, fgmap, L0)
    TH = st.get("th", 35) + (10 if st.get("caution") else 0)
    score = combine(sc, {**w, **xw})
    raw = "COMPRAR" if score >= TH else "VENDER" if score <= -TH else "ESPERAR"
    why = gates(raw, score, rd, items, sc)
    action = "ESPERAR" if why else raw
    st["history"].append({"ts": now().isoformat(timespec="seconds"), "price": p[-1], "score": score, "action": action})
    st["history"] = st["history"][-4000:]
    evaluate(st["history"])

    det = " | ".join(f"{k} {v:+.2f}" for k, v in sc.items())
    sigs, ts0 = [], st["history"][-1]["ts"]
    expl = explain(sc, {**w, **xw}, score, action, raw, why)
    lv = levels(action, p[-1], atr(rd), atr(r4 or rd)) if action != "ESPERAR" else None
    log_signal(p[-1], score, action, sc, why, expl, lv)
    if action != st.get("last"):
        sigs.append({"id": "sig-" + ts0, "type": "signal", "source": "Señales BTC", "action": action, "detail": expl,
                     "text": f"{action}" + (f" (señal {raw} bloqueada: {'; '.join(why)})" if why else "") + f" · puntuación {score} · BTC {p[-1]:,.0f} USD", "ts": ts0})
        if action != "ESPERAR":
            publish_signal(action, p[-1], atr(rd), explain(sc, {**w, **xw}, score, action, raw, why, short=True), r4 or rd,
                           reason=top_reason(sc, {**w, **xw}, action))
    nw = now()
    hrs = {int(x) for x in (os.getenv("REPORT_HOURS") or "7,19").split(",") if x.strip().isdigit()}
    try: RP = json.load(open("docs/reports.json"))
    except Exception: RP = []
    rslot = nw.strftime("%Y-%m-%d-") + str(nw.hour)
    if nw.hour in hrs and (not RP or RP[-1].get("slot") != rslot):
        label = "mañana" if nw.hour < 13 else "tarde"
        rep_ = build_report(sc, {**w, **xw}, score, p, rd, r4, items, fg, why, st.get("caution"))
        RP.append({"slot": rslot, "ts": nw.isoformat(timespec="seconds"), "title": f"Informe de la {label}", "text": rep_["text"]})
        os.makedirs("docs", exist_ok=True)
        json.dump(RP[-60:], open("docs/reports.json", "w"), ensure_ascii=False)
        publish_report(rep_, r4 or rd, label)
    if os.getenv("TEST_POST") == "true":
        publish_report(build_report(sc, {**w, **xw}, score, p, rd, r4, items, fg, why, st.get("caution")), r4 or rd, "prueba", test=True)
    if os.getenv("TEST_POST") == "true":
        publish_signal(action if action != "ESPERAR" else "COMPRAR", p[-1], atr(rd),
                       explain(sc, {**w, **xw}, score, action, raw, why, short=True), r4 or rd, test=True, real=action,
                       reason=top_reason(sc, {**w, **xw}, action if action != "ESPERAR" else "COMPRAR"))
    st["last"] = action

    n = now()
    if n.weekday() == 0 and n.hour == 7:
        tot, ok = accuracy(st["history"])
        live = f"{ok}/{tot} avisos acertados a {H} días" if tot else "aún sin avisos evaluables"
        ws = ", ".join(f"{k} {v * 100:.0f}%" for k, v in w.items())
        hi = ", ".join(f"{k} {h}% ({c})" for k, (h, c) in info.items())
        xi = ", ".join(f"{k} {h}% ({c})" for k, (h, c) in xinfo.items()) or "aún sin datos"
        admin(f"📊 Informe semanal BTC\nPrecio {p[-1]:,.0f} · puntuación {score} ({action})\nAciertos en vivo: {live}\n"
                 f"Aciertos históricos por indicador: {hi}\nPesos actuales: {ws}\nFiltros nuevos a 24 h: {xi}")
    try: seen = {i["id"] for i in json.load(open("docs/feed.json"))["items"]}
    except Exception: seen = None
    if seen is not None:
        for i in [x for x in items if x["impact"] and x["id"] not in seen][:3]:
            admin(f"⚡ {i['source']}: {i['text']}\n{i['link']}")
    tot, ok = accuracy(st["history"])
    try:
        for v in compare(rd, p, dates, fgmap): print("COMPARATIVA", v)  # solo en el registro del workflow
    except Exception as e: print("comparativa", e)
    write_pwa()
    write_candles(rd, r4, r1, r15)
    write_feed(items, {"learn": learn_view(st, xinfo), "expl": expl, "lv": ({k: round(v) for k, v in lv.items()} if lv else None), "gates": why, "price": p[-1], "score": score, "action": action, "fg": fg, "acc": [tot, ok],
                       "weights": {k: round(v, 3) for k, v in w.items()}}, sigs)
    st["weights"] = {k: round(v, 3) for k, v in w.items()}
    json.dump(st, open(STATE, "w"), indent=1)
    print(action, score, st["weights"])


if __name__ == "__main__":
    main()
