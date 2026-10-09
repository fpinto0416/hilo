# -*- coding: utf-8 -*-
"""
Shadow (paper trading) do HiLo 50 long-only -- acao e call.

Acompanha, desde INICIO, o que teria acontecido seguindo a recomendacao
diaria do hilo_long_only.py de duas formas:

  ACOES  comprar o ativo quando o HiLo 50 entra comprado e zerar quando
         sai. Carteira de pesos iguais, CDI real no caixa, 30 bps por lado.
         Medido nos 81 ativos (a carteira do card) e nos 6 com opcao.
  CALLS  nos 6 ativos com opcao, a call ATM do vencimento mensal mais
         proximo de 60 dias, rolando quando faltam < 10 dias e zerando
         junto com a acao. Tamanho delta-equivalente (w = premio /
         (delta x spot) do slot), o resto do slot em CDI -- a mesma
         convencao da pesquisa (pesquisa/calls/acervo50/), para que o
         numero seja comparavel com a coluna "call - acao" do painel.

O QUE E CONGELADO E O QUE E RECALCULADO
---------------------------------------
shadow/sinal.csv e APPEND-ONLY: decisao do dia (comprado 0/1) e retorno
da acao, gravados na primeira vez que o pregao e processado e nunca mais
reescritos. Motivo: o yfinance reajusta o historico a cada provento, e um
shadow cujo passado muda depois nao e shadow. Todo o resto (pernas de
call, curvas, resumo) e recalculado a cada rodada a partir desse arquivo
+ acervo-opcoes-b3 + CDI do acervo, que sao imutaveis.

PRECO DA CALL: ultimo negocio do dia +- spread MEDIDO do ativo
------------------------------------------------------------------
O bid/ask de fechamento do COTAHIST nao serve para essas series: vem zerado
ou absurdo (16/09/2026: VALEK751 com bid 0,17 numa call negociada a 5,00).
Entao compra = ultimo x (1+s), venda = ultimo x (1-s), com s = spread
mediano por lado de pesquisa/calls/acervo50/spreads.csv. Liquidacao no
vencimento = intrinseco, sem spread. A versao "mid" (s = 0) sai junto,
como referencia -- a pesquisa mostrou que e justamente o spread que come
a vantagem da call.

Serie que nao negociou no dia fica marcada no ultimo preco conhecido; se
precisar sair nesse dia, a saida vai para o proximo pregao em que negociar
(ou liquida no vencimento).

Uso:  python3 shadow.py            -> atualiza shadow/ e imprime o resumo
      python3 shadow.py --html X    -> tambem escreve o bloco do painel em X
"""
import json
import sys
from math import erf, exp, log, sqrt
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, "/app/acervo_opcoes_b3/src")
import cdi as cdi_mod  # noqa: E402

from hilo_long_only import ATIVOS_COM_OPCAO, HILO_N, SPREAD_MEDIANO_PCT, TICKERS  # noqa: E402

AQUI = Path(__file__).resolve().parent
DIR = AQUI / "shadow"
ACERVO = Path("/app/acervo_opcoes_b3/data")

# 1a rodada com a regra atual de call (vencimento ~60 dias, ACHADOS §12.12).
# Compra-se no FECHAMENTO deste dia tudo o que o card mandava estar comprado.
INICIO = pd.Timestamp("2026-09-10")
CAPITAL = 100_000.0
CUSTO_ACAO = 30 / 10000
DC_ALVO, DC_MIN, DC_ROLA = 60, 22, 10
LIMITE_PRINT = 0.20


# ---------------------------------------------------------------- dados ---

def calendario():
    """Pregoes de INICIO ate o ultimo dia com opcao no acervo."""
    dias = sorted(pd.Timestamp(p.stem) for p in (ACERVO / "opcoes").glob("*/*.parquet"))
    return pd.DatetimeIndex([d for d in dias if d >= INICIO])


def carregar_cdi(cal):
    """Fator diario do CDI nos pregoes do calendario.

    O BCB publica o CDI de D so em D+1, e o acervo baixa de madrugada -- o
    ultimo pregao costuma chegar sem CDI. Esses dias usam o ultimo fator
    conhecido (diferenca de centavos, e o valor certo entra na rodada
    seguinte, porque a curva e recalculada inteira)."""
    s = cdi_mod.carregar(INICIO - pd.Timedelta(days=10), cal[-1])
    return s.reindex(s.index.union(cal)).ffill().reindex(cal)


def atualizar_sinal(cal):
    """Acrescenta a sinal.csv os pregoes ainda nao gravados. Nunca reescreve."""
    arq = DIR / "sinal.csv"
    velho = pd.read_csv(arq, parse_dates=["data"]) if arq.exists() else pd.DataFrame()
    feitos = set(velho["data"]) if len(velho) else set()
    novos = [d for d in cal if d not in feitos]
    if not novos:
        return velho
    ini = INICIO - pd.Timedelta(days=200)          # sobra para o HiLo 50 aquecer
    linhas = []
    for t in TICKERS:
        df = yf.download(t + ".SA", start=ini, end=novos[-1] + pd.Timedelta(days=1),
                         progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty:
            continue
        df = df[df["Volume"] != 0]
        # mesma regra do hilo_long_only.calcular()
        hi = df["High"].rolling(HILO_N).mean().shift(1)
        lo = df["Low"].rolling(HILO_N).mean().shift(1)
        s = np.where(df["Close"] > hi, 1, np.where(df["Close"] < lo, -1, 0))
        pos = (pd.Series(s, index=df.index).replace(0, np.nan).ffill().fillna(0) > 0).astype(int)
        ret = df["Close"].pct_change()
        for d in novos:
            if d in df.index:
                linhas.append(dict(data=d, ticker=t, comprado=int(pos.loc[d]),
                                   close=round(float(df.loc[d, "Close"]), 4),
                                   ret=round(float(ret.loc[d]), 6)))
    novo = pd.DataFrame(linhas)
    tudo = pd.concat([velho, novo], ignore_index=True).sort_values(["data", "ticker"])
    DIR.mkdir(exist_ok=True)
    tudo.to_csv(arq, index=False, date_format="%Y-%m-%d")
    return tudo


def opcoes(cal):
    """Calls mensais dos 6 ativos, precos ja divididos por fatcot."""
    isin = json.load(open(AQUI / "pesquisa/calls/acervo50/mapa.json"))["isin"]
    alvo = {isin[t]: t for t in ATIVOS_COM_OPCAO}
    out, spot = [], []
    for d in cal:
        o = pd.read_parquet(ACERVO / f"opcoes/{d.year}/{d.date()}.parquet")
        o = o[(o["tipo"] == "C") & o["isin"].isin(list(alvo))].copy()
        o["venc"] = pd.to_datetime(o["vencimento"], format="%Y%m%d")
        f = o["fatcot"].replace(0, 1).astype(float)
        o["strike"] = o["strike"] / f
        o["ultimo"] = o["ultimo"] / f
        o["medio"] = o["medio"] / f
        out.append(o)
        s = pd.read_parquet(ACERVO / f"spot/{d.year}/{d.date()}.parquet")
        spot.append(s[s["isin"].isin(list(alvo))][["data", "isin", "ultimo"]])
    C = pd.concat(out, ignore_index=True)
    C["data"] = pd.to_datetime(C["data"])
    C["ticker"] = C["isin"].map(alvo)
    C["dc"] = (C["venc"] - C["data"]).dt.days
    # so mensais: vencimento a <= 3 dias da 3a sexta (feriado antecipa -- nov/2026
    # vence 19/11, nao 20/11). Mesmo criterio de acervo_opcoes_b3/src/ler.py.
    prim = C["venc"] - pd.to_timedelta(C["venc"].dt.day - 1, unit="D")
    terc = prim + pd.to_timedelta((4 - prim.dt.weekday) % 7 + 14, unit="D")
    C = C[((C["venc"] - terc).dt.days.abs() <= 3) & (C["ultimo"] > 0)]
    # Print fora da curva: ultimo a mais de 20% do preco medio da PROPRIA
    # serie no dia vira "nao negociou". Caso real: BOVAK185 em 10/09/2026
    # fechou a 17,00 com medio 11,63 e as vizinhas 184/186 a 12,34/11,60 --
    # sozinho, esse print tirava 7 p.p. do shadow da BOVA11. O medio NAO e
    # usado como preco (VWAP do dia e look-ahead para quem decide no
    # fechamento, ver pesquisa/calls/acervo50/README.md); serve so de teste.
    fora = (C["medio"] > 0) & ((C["ultimo"] / C["medio"] - 1).abs() > LIMITE_PRINT)
    C = C[~fora]
    S = pd.concat(spot, ignore_index=True)
    S["data"] = pd.to_datetime(S["data"])
    S["ticker"] = S["isin"].map(alvo)
    return C, S.set_index(["data", "ticker"])["ultimo"]


# ------------------------------------------------------- Black-Scholes ---
# Mesmas formulas de pesquisa/calls/acervo50/motor2.py (copiadas para nao
# acoplar producao a P&D). Taxa = CDI real do dia de entrada.

def _N(x):
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _bs(S, K, T, sig, r):
    d1 = (log(S / K) + (r + 0.5 * sig * sig) * T) / (sig * sqrt(T))
    return S * _N(d1) - K * exp(-r * T) * _N(d1 - sig * sqrt(T)), _N(d1)


def delta_de(preco, S, K, T, r):
    lo, hi = 1e-4, 5.0
    if T <= 0 or preco <= _bs(S, K, T, lo, r)[0] or preco >= _bs(S, K, T, hi, r)[0]:
        return np.nan
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _bs(S, K, T, mid, r)[0] < preco else (lo, mid)
    return _bs(S, K, T, (lo + hi) / 2, r)[1]


# ---------------------------------------------------------------- motor ---

def acoes(sig, fcdi, cal, tickers):
    """Riqueza diaria da carteira em acao (pesos iguais) e do buy-and-hold."""
    s = sig[sig["ticker"].isin(tickers)]
    comp = s.pivot(index="data", columns="ticker", values="comprado").reindex(cal)
    ret = s.pivot(index="data", columns="ticker", values="ret").reindex(cal).fillna(0.0)
    tks = [t for t in tickers if t in comp.columns and comp[t].notna().iloc[0]]
    v = pd.Series(CAPITAL / len(tks), index=tks)
    bh = v.copy()
    est = comp.iloc[0][tks].astype(int)
    v[est == 1] *= 1 - CUSTO_ACAO
    bh *= 1 - CUSTO_ACAO
    curva, bhc = [v.sum()], [bh.sum()]
    for i in range(1, len(cal)):
        d = cal[i]
        f = fcdi.get(d, 1.0)
        v = v * np.where(est == 1, 1 + ret.loc[d, tks], f)
        bh = bh * (1 + ret.loc[d, tks])
        novo = comp.loc[d, tks].fillna(est).astype(int)
        v[novo != est] *= 1 - CUSTO_ACAO
        est = novo
        curva.append(v.sum())
        bhc.append(bh.sum())
    return pd.Series(curva, index=cal), pd.Series(bhc, index=cal), est


def calls(sig, fcdi, cal, C, S, com_spread=True):
    """Riqueza diaria da carteira em call (6 slots) + registro das pernas."""
    tks = ATIVOS_COM_OPCAO
    comp = sig.pivot(index="data", columns="ticker", values="comprado").reindex(cal)
    Q = {k: g.set_index("data")["ultimo"] for k, g in C.groupby("codneg")}
    pernas, vals = [], {t: [] for t in tks}
    anual = lambda d: np.log(fcdi.get(d, 1.0)) * 252

    for t in tks:
        sp = SPREAD_MEDIANO_PCT[t] / 100 if com_spread else 0.0
        V, leg, pend_saida = CAPITAL / len(tks), None, False
        ct = C[C["ticker"] == t]
        for i, d in enumerate(cal):
            if i > 0 and leg is None:
                V *= fcdi.get(d, 1.0)
            if leg is not None:
                u = Q[leg["cod"]].get(d, np.nan)
                if np.isfinite(u):
                    leg["u"] = u
                leg["caixa"] *= fcdi.get(d, 1.0) if i > 0 and d > leg["d_ent"] else 1.0
                V = leg["n"] * leg["u"] * (1 - sp) + leg["caixa"]

            def fechar(preco, motivo, data, liq=False):
                nonlocal V, leg
                V = leg["n"] * preco * (1.0 if liq else (1 - sp)) + leg["caixa"]
                pernas.append(dict(ticker=t, codneg=leg["cod"], strike=round(leg["K"], 2),
                                   venc=leg["venc"].date(), entrada=leg["d_ent"].date(),
                                   p_ult_ent=leg["p_ult"], saida=data.date(), p_ult_sai=round(preco, 4),
                                   motivo=motivo, delta=round(leg["delta"], 3), w=round(leg["w"], 4),
                                   resultado_pct=round((V / leg["V0"] - 1) * 100, 2)))
                leg = None

            quer = int(comp.loc[d, t]) if pd.notna(comp.loc[d, t]) else 0
            if quer:
                pend_saida = False          # sinal voltou antes de conseguir sair
            if leg is not None:
                negociou = d in Q[leg["cod"]].index
                if d >= leg["venc"]:
                    sv = S.get((leg["venc"], t), S.get((d, t), np.nan))
                    fechar(max(sv - leg["K"], 0.0), "liquidacao", d, liq=True)
                elif (not quer or pend_saida) and negociou:
                    fechar(leg["u"], "saida" if not pend_saida else "saida_atrasada", d)
                    pend_saida = False
                elif not quer:
                    pend_saida = True
                elif (leg["venc"] - d).days < DC_ROLA and negociou:
                    fechar(leg["u"], "rolagem", d)
            if leg is None and quer and d < cal[-1] + pd.Timedelta(days=1):
                g = ct[(ct["data"] == d) & (ct["dc"] > DC_MIN)]
                spot = S.get((d, t), np.nan)
                if not g.empty and np.isfinite(spot):
                    g = g.assign(m=np.abs(np.log(g["strike"] / spot)))
                    cand = g.loc[g.groupby("venc")["m"].idxmin()]
                    x = cand.loc[(cand["dc"] - DC_ALVO).abs().idxmin()]
                    T = x["dc"] / 365.0
                    dl = delta_de(x["ultimo"], spot, x["strike"], T, anual(d))
                    if not (0.05 < dl < 0.98):
                        dl = 0.5            # IV fora do modelo: aproxima ATM
                    w = min(x["ultimo"] / (dl * spot), 1.0)
                    premio = w * V
                    n = premio / (x["ultimo"] * (1 + sp))
                    leg = dict(cod=x["codneg"], K=float(x["strike"]), venc=x["venc"], d_ent=d,
                               p_ult=float(x["ultimo"]), u=float(x["ultimo"]), n=n,
                               caixa=V - premio, delta=dl, w=w, V0=V)
                    V = n * leg["u"] * (1 - sp) + leg["caixa"]
            vals[t].append(V)
        if leg is not None:
            pernas.append(dict(ticker=t, codneg=leg["cod"], strike=round(leg["K"], 2),
                               venc=leg["venc"].date(), entrada=leg["d_ent"].date(),
                               p_ult_ent=leg["p_ult"], saida=None, p_ult_sai=round(leg["u"], 4),
                               motivo="aberta" + (" (saida pendente)" if pend_saida else ""),
                               delta=round(leg["delta"], 3), w=round(leg["w"], 4),
                               resultado_pct=round((V / leg["V0"] - 1) * 100, 2)))
    return pd.DataFrame(vals, index=cal).sum(axis=1), pd.DataFrame(pernas)


# --------------------------------------------------------------- rodar ---

def rodar():
    cal = calendario()
    sig = atualizar_sinal(cal)
    cal = cal[cal <= sig["data"].max()]
    fcdi = carregar_cdi(cal)
    cdi_estimado = [str(d.date()) for d in cal if d > cdi_mod.carregar().index.max()]
    C, S = opcoes(cal)
    a81, bh81, est81 = acoes(sig, fcdi, cal, TICKERS)
    a6, bh6, _ = acoes(sig, fcdi, cal, ATIVOS_COM_OPCAO)
    c6, pernas = calls(sig, fcdi, cal, C, S, com_spread=True)
    c6m, _ = calls(sig, fcdi, cal, C, S, com_spread=False)
    cdi = pd.Series(np.cumprod([1.0] + [fcdi.get(d, 1.0) for d in cal[1:]]) * CAPITAL, index=cal)
    curva = pd.DataFrame({"acoes_81": a81, "bh_81": bh81, "acoes_6": a6, "bh_6": bh6,
                          "calls_6_spread": c6, "calls_6_mid": c6m, "cdi": cdi}).round(2)
    curva.index.name = "data"
    curva.to_csv(DIR / "curva.csv", date_format="%Y-%m-%d")
    pernas.to_csv(DIR / "pernas_call.csv", index=False)
    ult = sig[sig["data"] == cal[-1]]
    resumo = dict(inicio=str(INICIO.date()), fim=str(cal[-1].date()), pregoes=len(cal) - 1,
                  retorno_pct={k: round((curva[k].iloc[-1] / CAPITAL - 1) * 100, 2) for k in curva},
                  cdi_estimado=cdi_estimado,
                  comprados_81=int(ult["comprado"].sum()), universo_81=int(ult["ticker"].nunique()),
                  trocas_81=int(sig.sort_values("data").groupby("ticker")["comprado"]
                                .apply(lambda x: (x.diff().abs() > 0).sum()).sum()))
    json.dump(resumo, open(DIR / "resumo.json", "w"), indent=2)
    return curva, pernas, resumo


# ---------------------------------------------------------------- html ---

def _pct(v, casas=2):
    s = f"{abs(v):.{casas}f}".replace(".", ",")
    return ("+" if v > 0 else "−" if v < 0 else "") + s + "%"


def _cor(v):
    return "var(--pos)" if v > 0 else "var(--neg)" if v < 0 else "var(--text-dim)"


def _data(d):
    return pd.Timestamp(d).strftime("%d/%m")


def html(curva, pernas, resumo):
    """Bloco pronto para o card Hilo do Painel de Sinais (classes do painel)."""
    r = resumo["retorno_pct"]
    def rs(k):
        v = curva[k].iloc[-1] - CAPITAL
        return ("+" if v > 0 else "−" if v < 0 else "") + f"R$ {abs(v):,.0f}".replace(",", ".")
    linhas = [
        ("Ações — carteira do card (81 ativos)", "acoes_81", None),
        ("Ações — só os 6 com opção", "acoes_6", None),
        ("Calls — 6 ativos, spread medido", "calls_6_spread", "acoes_6"),
        ("Calls — 6 ativos, a mid (referência)", "calls_6_mid", "acoes_6"),
        ("Buy &amp; hold dos 81 (controle)", "bh_81", None),
        ("CDI", "cdi", None),
    ]
    tr = []
    for rot, k, vs in linhas:
        dif = (f'<td class="num" style="color:{_cor(r[k] - r[vs])}">{_pct(r[k] - r[vs]).replace("%", " p.p.")}</td>'
               if vs else '<td class="num" style="color:var(--text-faint)">—</td>')
        tr.append(f'<tr><td>{rot}</td><td class="num" style="color:{_cor(r[k])}">{_pct(r[k])}</td>'
                  f'<td class="num">{rs(k)}</td>{dif}</tr>')
    pos = []
    for _, x in pernas.iterrows():
        aberta = str(x["motivo"]).startswith("aberta")
        pos.append(
            f'<tr><td>{x["ticker"]}</td><td class="num">{x["codneg"]}</td>'
            f'<td class="num">{x["strike"]:.2f}'.replace(".", ",") + '</td>'
            f'<td class="num">{_data(x["venc"])}</td>'
            f'<td class="num">{_data(x["entrada"])} a {x["p_ult_ent"]:.2f}'.replace(".", ",") + '</td>'
            f'<td class="num">{(_data(resumo["fim"]) + " a ") if aberta else (_data(x["saida"]) + " a ")}{x["p_ult_sai"]:.2f}'.replace(".", ",") + '</td>'
            f'<td class="num" style="color:{_cor(x["resultado_pct"])}">{_pct(x["resultado_pct"])}</td>'
            f'<td>{x["motivo"]}</td></tr>')
    n = resumo["pregoes"]
    return f"""      <!--
        SHADOW DO LONG-ONLY -- gerado por hilo_50_long_only/shadow.py --html,
        NAO editar a mao. Fonte congelada: hilo_50_long_only/shadow/sinal.csv
        (append-only). Metodo no docstring do shadow.py.
      -->
      <div class="card-body" style="grid-template-columns: 1fr; border-top: 1px solid var(--border);">
        <div style="padding: 18px 24px 0;">
          <span class="stat-label" style="display:block;">Shadow — seguindo a recomendação do long-only desde {_data(resumo["inicio"])}</span>
          <span class="card-updated" style="margin-top:4px;">{_data(resumo["inicio"])} a {_data(resumo["fim"])}/{resumo["fim"][:4]} · {n} pregões de resultado · R$ 100 mil por forma de operar</span>
        </div>
        <div class="side">
          <div class="scroll-x">
            <table class="mini">
              <caption>resultado acumulado por forma de operar</caption>
              <thead><tr><th>como</th><th>retorno</th><th>em R$</th><th>call − ação (mesmos 6)</th></tr></thead>
              <tbody>
                {chr(10).join("                " + x for x in tr).strip()}
              </tbody>
            </table>
          </div>
          <div class="scroll-x">
            <table class="mini">
              <caption>pernas de call (abertas e encerradas)</caption>
              <thead><tr><th>ativo</th><th>contrato</th><th>strike</th><th>venc.</th><th>entrada (último)</th><th>marcação (último)</th><th>resultado do slot</th><th>situação</th></tr></thead>
              <tbody>
                {chr(10).join("                " + x for x in pos).strip()}
              </tbody>
            </table>
          </div>
        </div>
      </div>
"""


if __name__ == "__main__":
    curva, pernas, resumo = rodar()
    if "--html" in sys.argv:
        Path(sys.argv[sys.argv.index("--html") + 1]).write_text(html(curva, pernas, resumo), encoding="utf-8")
    print(json.dumps(resumo, indent=2))
    print(curva.to_string())
    print(pernas.to_string())
