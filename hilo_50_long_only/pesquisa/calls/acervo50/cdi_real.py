# -*- coding: utf-8 -*-
"""Refaz a comparacao call x acao com o CDI REAL do Banco Central.

Ate 10/09/2026 tudo aqui usava CDI fixo em 10% a.a. -- a premissa mais
fragil do estudo (§12.13: 57% do retorno da call vinha do CDI, e a
conclusao mudava de sinal conforme a taxa suposta). A serie real vem de
acervo-opcoes-b3/data/cdi (SGS/BCB serie 12, % ao dia).

Por que importa o TIMING e nao so a media: a SELIC foi de 14,25% (2015-16)
a 2,00% (2020) e voltou a 14,5%. Taxa fixa credita juro demais em 2020,
justamente o ano de maior movimento de mercado do periodo.
"""
import os, sys, warnings, pathlib, pandas as pd, numpy as np
warnings.filterwarnings("ignore")

ACERVO = pathlib.Path("/app/acervo_opcoes_b3")
sys.path.insert(0, str(ACERVO / "src"))
import cdi as mcdi
mcdi.DIR_CDI = ACERVO / "data" / "cdi"

DB = "/app/projeto_MIA26/database"
CUSTO_ACAO = 30 / 10000
INI = pd.Timestamp("2015-01-02"); FIM = pd.Timestamp("2026-09-09")
ANOS = (FIM - INI).days / 365.25
CDI_FIXO_D = (1.10) ** (1 / 252) - 1     # o que se usava antes

P = pd.read_parquet("pernas3f.parquet")
P = P[P.delta.notna() & (P.delta > 0.05) & (P.delta < 0.98)].copy()
P["w"] = P.p_ent / (P.delta * P.s_ent); P = P[(P.w > 0) & (P.w <= 1)]
P = P.sort_values(["ticker", "d_ent"]).reset_index(drop=True)
G = pd.read_csv("spreads.csv").set_index("ticker")

C = pd.read_parquet("calls.parquet")
C = C[C.ultimo > 0][["codneg", "data", "ultimo"]].drop_duplicates(["codneg", "data"])
Q = {k: v.set_index("data").ultimo.sort_index() for k, v in C.groupby("codneg")}
cal = pd.DatetimeIndex(sorted(pd.read_parquet("spot.parquet").data.unique()))
cal = cal[(cal >= INI) & (cal <= FIM)]
loc = {d: i for i, d in enumerate(cal)}; N = len(cal)

# ---- CDI real alinhado ao calendario de pregoes ----
S_CDI = mcdi.carregar(INI, FIM)
fat = S_CDI.reindex(cal)
faltando = int(fat.isna().sum())
fat = fat.fillna(1.0)                    # dia de bolsa sem CDI publicado: sem juro
FC = np.concatenate([[1.0], np.cumprod(fat.values)])   # FC[i] = fator ate cal[i-1]
print(f"CDI real: {mcdi.taxa_aa(S_CDI):.2f}% a.a. equivalente no periodo "
      f"(fixo antigo: 10,00%) | pregoes sem CDI publicado: {faltando}")
print("por ano: " + "  ".join(
    f"{a}:{mcdi.taxa_aa(S_CDI[S_CDI.index.year==a]):.1f}%" for a in range(2015, 2027)))

def fator(i0, i1):
    """Fator do CDI em (cal[i0], cal[i1]] -- exclui o dia de entrada."""
    return FC[i1 + 1] / FC[i0 + 1] if i1 > i0 else 1.0

_aj = {}
def aj(t):
    if t not in _aj:
        p = f"{DB}/{t}.xlsx"
        if not os.path.exists(p): _aj[t] = None
        else:
            s = pd.read_excel(p, index_col=0, parse_dates=True).sort_index()["Close"]
            _aj[t] = s[~s.index.duplicated()].reindex(cal).ffill()
    return _aj[t]

def series(tickers, spf, cdi_real=True):
    """Riqueza diaria: call+caixa e acao. Passada unica (ver §12.14)."""
    A = {}; B = {}
    for t in tickers:
        a = aj(t)
        if a is None: continue
        sp = spf(t); L = P[P.ticker == t]
        if L.empty: continue
        r = a.pct_change().fillna(0.0).values
        inicio = {}; dentro = np.zeros(N, bool)
        for _, x in L.iterrows():
            i0, i1 = loc.get(x.d_ent), loc.get(x.d_sai)
            if i0 is None or i1 is None or i1 <= i0: continue
            jan = cal[i0:i1 + 1]; q = Q.get(x.codneg)
            px = q.reindex(jan) if q is not None else pd.Series(np.nan, index=jan)
            px = px.ffill(); px.iloc[0] = x.p_ent; px.iloc[-1] = x.p_sai
            px = px.ffill().bfill()
            liq = str(x.motivo).startswith("liquidacao")
            rc = px.values * (1.0 if liq else (1 - sp)) / (x.p_ent * (1 + sp)) - 1
            if cdi_real:
                cx = np.array([fator(i0, i0 + k) for k in range(len(jan))])
            else:
                ndu = np.maximum(((jan - jan[0]).days * 252 / 365).astype(int), 0)
                cx = (1 + CDI_FIXO_D) ** ndu
            inicio.setdefault(i0, []).append((i1, x.w * rc + (1 - x.w) * (cx - 1)))
            dentro[i0:i1 + 1] = True
        ep_ini = {}; ep_d = np.zeros(N, bool)
        for ep, g in L.groupby("ep"):
            i0, i1 = loc.get(g.d_ent.min()), loc.get(g.d_sai.max())
            if i0 is None or i1 is None or i1 <= i0: continue
            ep_ini[i0] = i1; ep_d[i0:i1 + 1] = True
        wc = np.empty(N); wa = np.empty(N); Wc = Wa = 1.0
        base = 1.0; sl = None; sl_i0 = 0; fim = -1; fim_a = -1
        for i in range(N):
            passo = (fat.values[i] if cdi_real else 1 + CDI_FIXO_D)
            if i in inicio:
                for i1, s in inicio[i]:
                    if sl is not None and fim == i: Wc = base * (1 + sl[i - sl_i0])
                    base = Wc; sl, sl_i0, fim = s, i, i1
            if sl is not None and sl_i0 <= i <= fim: Wc = base * (1 + sl[i - sl_i0])
            elif not dentro[i]: Wc *= passo
            wc[i] = Wc
            if i in ep_ini: fim_a = ep_ini[i]; Wa *= 1 - CUSTO_ACAO
            if i <= fim_a and ep_d[i]:
                if i > 0 and ep_d[i - 1] and i not in ep_ini: Wa *= 1 + r[i]
                if i == fim_a: Wa *= 1 - CUSTO_ACAO
            elif not ep_d[i]: Wa *= passo
            wa[i] = Wa
        A[t] = wc; B[t] = wa
    f = lambda D: pd.DataFrame(D, index=cal).mean(axis=1)
    return f(A), f(B)

dd = lambda x: (np.asarray(x, float) / np.maximum.accumulate(np.asarray(x, float)) - 1).min() * 100
aa = lambda x: (x.iloc[-1] ** (1 / ANOS) - 1) * 100

import json
bons = json.load(open("mapa.json"))["bons"]
t50 = [t for t in P.ticker.unique() if t in bons]
for rot, ts in [("50 ATIVOS", t50), ("PETR4/VALE3/BOVA11", ["PETR4", "VALE3", "BOVA11"])]:
    print(f"\n=== {rot} ===")
    print(f"{'cenario':>22} {'call':>8} {'DD call':>9} {'acao':>8} {'DD acao':>9} {'dif':>8}")
    for spr, sfn in [("mid", lambda t: 0.0),
                     ("p25", lambda t: G.loc[t, "p25"] / 100 if t in G.index else 0.0),
                     ("mediana", lambda t: G.loc[t, "mediana"] / 100 if t in G.index else 0.0)]:
        for real, tag in [(False, "CDI 10% fixo"), (True, "CDI REAL")]:
            c, s = series(ts, sfn, cdi_real=real)
            print(f"{spr+' / '+tag:>22} {aa(c):>7.2f}% {dd(c):>8.1f}% "
                  f"{aa(s):>7.2f}% {dd(s):>8.1f}% {aa(c)-aa(s):>+7.2f}")
