# -*- coding: utf-8 -*-
"""
HiLo 50 long-only por SETOR -- existe setor que funciona melhor?

Pedido em 22/09/2026. O ACHADOS.md §7 ja registra "efeito setorial:
ranking nao persiste (Spearman 0,17, p = 0,53)", mas aquele teste nao
esta no repo e nao mostra a tabela. Este script refaz a conta inteira e,
principalmente, mostra as duas coisas que a tabela sozinha esconde:

  1. O BUY-AND-HOLD DO MESMO SETOR como controle. Setor que subiu muito
     no periodo faz a estrategia subir junto -- isso e beta do setor, nao
     qualidade do sinal. O que a estrategia adiciona e `alfa = estrategia
     - B&H do proprio setor` (regra do CLAUDE.md do subprojeto).
  2. PERSISTENCIA. Dividir a amostra em duas metades e ver se o ranking
     de setores da 1a metade sobrevive na 2a. Sem isso, "o setor X e o
     melhor" e so o vencedor in-sample -- sempre existe um.

Convencoes (iguais as do resto do subprojeto):
  - HiLo 50 fixo, long-only: -1 nao e short, e caixa remunerado no CDI.
  - Sinal DEFASADO contra o retorno (pesquisa/calls/acervo50/README.md:
    sem isso o baseline dava 54% a.a. com Sharpe 3,66).
  - Piso rigido em 2000 (memoria do acervo: barreiras cambiais pre-1999
    distorcem a serie).
  - 30 bps POR EPISODIO (cobrado na entrada), que e a convencao do
    subprojeto (pesquisa/calls/acervo50/README.md: "a acao paga 30 bps por
    episodio, nao por perna"). Sao 8,4 trocas/ano/ativo, entao cobrar as
    duas pontas tira 2,5 pp a.a. -- desloca todos os setores junto e nao
    muda o ranking, mas desalinha do numero de referencia do §8.
  - Carteira do setor = equal-weight dos ativos disponiveis no dia.
  - CDI real diario (SGS/BCB serie 12), nao taxa fixa.

Uso: python3 setores.py [--csv saida.csv]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, "/app/acervo_opcoes_b3/src")
import cdi as cdi_mod  # noqa: E402

from hilo_long_only import HILO_N, TICKERS  # noqa: E402

DB = Path("/app/projeto_MIA26/database")
SNAP = Path("/app/acoes_fundamentalista/dados/snapshot_diario.csv")
INICIO = pd.Timestamp("2000-01-01")     # piso rigido, nao mexer
CUSTO = 30 / 10000
CORTE = pd.Timestamp("2013-12-31")      # divisao das metades

# Os 7 que o snapshot de fundamentos nao cobre, classificados a mao.
# ETF nao e setor -- fica num balde proprio e fora do teste de persistencia.
MANUAL = {
    "BOVA11": "Índice (ETF)", "SMAL11": "Índice (ETF)",
    "AURA33": "Basic Materials",        # Aura Minerals, BDR
    "XPBR31": "Financial Services",     # XP Inc, BDR
    "ROXO34": "Financial Services",     # Nu Holdings, BDR
    "RAIZ4": "Energy",                  # Raízen
    "WIZC3": "Financial Services",      # Wiz Co, corretagem de seguros
}


def setores():
    d = pd.read_csv(SNAP).sort_values("data").drop_duplicates("ticker", keep="last")
    m = d.set_index("ticker")["setor"].to_dict()
    return {t: MANUAL.get(t, m.get(t)) for t in TICKERS}


def serie(ticker, cdi):
    """Retorno diario da estrategia e do buy-and-hold do ativo."""
    p = DB / f"{ticker}.xlsx"
    if not p.exists():
        return None
    d = pd.read_excel(p, index_col=0, parse_dates=True).sort_index()
    d = d.dropna(subset=["High", "Low", "Close"])
    d = d[~d.index.duplicated(keep="first")]
    d = d[d.index >= INICIO]
    if len(d) < HILO_N + 250:
        return None
    hi = d["High"].rolling(HILO_N).mean().shift(1)
    lo = d["Low"].rolling(HILO_N).mean().shift(1)
    s = np.where(d["Close"] > hi, 1, np.where(d["Close"] < lo, -1, 0))
    comprado = (pd.Series(s, index=d.index).replace(0, np.nan).ffill().fillna(0) > 0).astype(int)
    # DEFASAGEM: a posicao de hoje foi decidida no fechamento de ontem.
    pos = comprado.shift(1).fillna(0)
    ret = d["Close"].pct_change().fillna(0.0)
    juro = cdi.reindex(d.index).ffill().fillna(1.0) - 1.0
    entrada = (pos.diff() > 0).astype(float)      # 30 bps por episodio
    estrat = pos * ret + (1 - pos) * juro - entrada * CUSTO
    aquece = d.index[HILO_N + 1]          # nao contar o aquecimento do indicador
    return pd.DataFrame({"estrat": estrat, "bh": ret, "pos": pos}).loc[aquece:]


def metricas(r, nome, bh=None):
    c = (1 + r).cumprod()
    anos = (r.index[-1] - r.index[0]).days / 365.25
    aa = (c.iloc[-1] ** (1 / anos) - 1) * 100
    vol = r.std() * np.sqrt(252) * 100
    dd = (c / c.cummax() - 1).min() * 100
    out = dict(recorte=nome, anos=round(anos, 1), aa=round(aa, 2),
               vol=round(vol, 2), dd=round(dd, 1))
    if bh is not None:
        cb = (1 + bh).cumprod()
        aab = (cb.iloc[-1] ** (1 / anos) - 1) * 100
        ddb = (cb / cb.cummax() - 1).min() * 100
        out.update(bh_aa=round(aab, 2), alfa=round(aa - aab, 2),
                   vol_bh=round(vol / (bh.std() * np.sqrt(252) * 100), 3),
                   dd_bh=round(dd / ddb, 3))
    return out


def carteira(series, tickers, col):
    """Equal-weight diario dos ativos disponiveis no dia."""
    df = pd.DataFrame({t: series[t][col] for t in tickers if t in series})
    return df.mean(axis=1).dropna()


def main():
    cdi = cdi_mod.carregar()
    if cdi.index.min() > INICIO:                     # acervo so tem 2015+
        extra = [cdi_mod.baixar(a) for a in range(INICIO.year, cdi.index.min().year)]
        e = pd.concat(extra).drop_duplicates("data").set_index("data")["fator"]
        cdi = pd.concat([e, cdi]).sort_index()
        cdi = cdi[~cdi.index.duplicated()]

    setor = setores()
    series = {}
    for t in TICKERS:
        s = serie(t, cdi)
        if s is not None:
            series[t] = s
    print(f"ativos com serie: {len(series)}/{len(TICKERS)}\n")

    por_setor, linhas = {}, []
    for sec in sorted(set(setor.values())):
        tk = [t for t in series if setor[t] == sec]
        if not tk:
            continue
        por_setor[sec] = tk
        e, b = carteira(series, tk, "estrat"), carteira(series, tk, "bh")
        m = metricas(e, sec, b)
        m["n"] = len(tk)
        m["tempo_comprado"] = round(carteira(series, tk, "pos").mean() * 100, 1)
        linhas.append(m)
    todos = list(series)
    m = metricas(carteira(series, todos, "estrat"), "TODOS (81)", carteira(series, todos, "bh"))
    m["n"] = len(todos)
    m["tempo_comprado"] = round(carteira(series, todos, "pos").mean() * 100, 1)
    linhas.append(m)

    T = pd.DataFrame(linhas).set_index("recorte")
    T = T[["n", "anos", "aa", "bh_aa", "alfa", "vol", "vol_bh", "dd", "dd_bh", "tempo_comprado"]]
    print("=== Setor: estrategia x buy-and-hold DO PROPRIO SETOR (2000-2026) ===")
    print(T.sort_values("alfa", ascending=False).to_string())

    # ---- persistencia: o ranking de alfa da 1a metade sobrevive na 2a? ----
    metades = {}
    for nome, sl in [("1a metade (ate 2013)", slice(None, CORTE)),
                     ("2a metade (2014+)", slice(CORTE, None))]:
        d = {}
        for sec, tk in por_setor.items():
            if sec.startswith("Índice"):
                continue
            e, b = carteira(series, tk, "estrat")[sl], carteira(series, tk, "bh")[sl]
            if len(e) < 250:
                continue
            d[sec] = metricas(e, sec, b)["alfa"]
        metades[nome] = pd.Series(d)
    P = pd.DataFrame(metades).dropna()
    print("\n=== Alfa (pp a.a.) por metade -- o ranking persiste? ===")
    print(P.assign(rank1=P.iloc[:, 0].rank(ascending=False).astype(int),
                   rank2=P.iloc[:, 1].rank(ascending=False).astype(int))
           .sort_values(P.columns[0], ascending=False).to_string())
    from scipy.stats import spearmanr, ttest_1samp
    ativo = {}
    for t_ in series:
        d = series[t_]
        v = []
        for sl in [slice(None, CORTE), slice(CORTE, None)]:
            x = d.loc[sl]
            if len(x) < 250:
                v = None
                break
            v.append(metricas(x["estrat"], t_, x["bh"])["alfa"])
        if v:
            ativo[t_] = v
    A = pd.DataFrame(ativo, index=["1a", "2a"]).T
    ra, pa = spearmanr(A["1a"], A["2a"])
    print(f"\nPersistencia POR ATIVO (n = {len(A)} com as duas metades): "
          f"Spearman rho = {ra:.2f}, p = {pa:.3f}")
    q = A["1a"].rank(ascending=False) <= len(A) / 3
    print(f"  alfa medio na 2a metade: terco melhor da 1a = {A.loc[q, '2a'].mean():+.2f} pp | "
          f"resto = {A.loc[~q, '2a'].mean():+.2f} pp")
    rho, p = spearmanr(P.iloc[:, 0], P.iloc[:, 1])
    print(f"\nSpearman entre as duas metades: rho = {rho:.2f}, p = {p:.3f} (n = {len(P)} setores)")
    t, pt = ttest_1samp(T.drop(index="TODOS (81)")["alfa"].dropna(), 0)
    print(f"Alfa setorial medio = {T.drop(index='TODOS (81)')['alfa'].mean():+.2f} pp "
          f"(t = {t:.2f}, p = {pt:.3f})")

    rodar_wf(series, setor)

    if "--csv" in sys.argv:
        T.to_csv(sys.argv[sys.argv.index("--csv") + 1])
    return T, P




# --------------------------------------------------------------------------
# Teste que decide: SELECIONAR setor pelo passado funciona no futuro?
#
# A tabela acima e in-sample -- sempre existe um setor melhor. O §7 ja
# rejeitou "selecao de ativos por esperanca acumulada" (4,69% vs 6,19% a.a.);
# aqui a mesma pergunta para setor, em walk-forward: a cada 1o de janeiro,
# ranqueia os setores SO com o que aconteceu ate ali e opera o ano seguinte
# apenas nos k melhores.

def walkforward(series, setor, k=3, ini_treino=5):
    anos = sorted({d.year for t in series for d in [series[t].index[0]]} | set(range(2000, 2027)))
    cal_ini = min(series[t].index[0] for t in series).year + ini_treino
    escolhas, r_sel, r_bh_sel, r_todos, r_bh = {}, [], [], [], []
    for ano in range(cal_ini, 2027):
        treino = slice(None, pd.Timestamp(f"{ano-1}-12-31"))
        teste = slice(pd.Timestamp(f"{ano}-01-01"), pd.Timestamp(f"{ano}-12-31"))
        alfas = {}
        for sec in sorted(set(setor.values())):
            tk = [t for t in series if setor[t] == sec]
            if not tk:
                continue
            e, b = carteira(series, tk, "estrat")[treino], carteira(series, tk, "bh")[treino]
            if len(e) < 250:
                continue
            alfas[sec] = metricas(e, sec, b)["alfa"]
        if len(alfas) < k + 1:
            continue
        top = sorted(alfas, key=alfas.get, reverse=True)[:k]
        tk = [t for t in series if setor[t] in top]
        e = carteira(series, tk, "estrat")[teste]
        if len(e) < 60:
            continue
        escolhas[ano] = top
        r_sel.append(e)
        # CONTROLE OBRIGATORIO: B&H DOS MESMOS SETORES ESCOLHIDOS. Comparar a
        # selecao com o B&H dos 81 compara universos diferentes -- se o ganho
        # vier do beta do setor escolhido, ele aparece aqui tambem.
        r_bh_sel.append(carteira(series, tk, "bh")[teste])
        r_todos.append(carteira(series, list(series), "estrat")[teste])
        r_bh.append(carteira(series, list(series), "bh")[teste])
    return (pd.concat(r_sel), pd.concat(r_bh_sel), pd.concat(r_todos),
            pd.concat(r_bh), escolhas)


def rodar_wf(series, setor):
    print("\n=== Walk-forward: operar so os k setores com melhor alfa passado ===")
    guardado = {}
    f = lambda r: ((1 + r).cumprod().iloc[-1] ** (252 / len(r)) - 1) * 100
    import numpy as _np
    vol = lambda r: r.std() * _np.sqrt(252) * 100
    dd = lambda r: ((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min() * 100
    print(f"  {'':14s} {'estrategia':>11s} {'B&H mesmos':>11s} {'ALFA':>6s}"
          f" {'vol/BH':>7s} {'DD/BH':>6s} {'| todos 81':>11s} {'B&H 81':>8s}")
    for k in (2, 3, 5):
        sel, bh_sel, todos, bh, esc = walkforward(series, setor, k=k)
        guardado[k] = esc
        print(f"  top {k} setores: {f(sel):10.2f}% {f(bh_sel):10.2f}% "
              f"{f(sel)-f(bh_sel):+5.2f} {vol(sel)/vol(bh_sel):7.2f} {dd(sel)/dd(bh_sel):6.2f}"
              f" {f(todos):10.2f}% {f(bh):8.2f}%   ({len(esc)} anos: {min(esc)}-{max(esc)})")
    esc = guardado[3]
    print("\n  setores escolhidos por ano (top 3):")
    for ano in sorted(esc):
        print(f"    {ano}: {', '.join(esc[ano])}")


if __name__ == "__main__":
    main()
