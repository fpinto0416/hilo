"""
Hilo — Resultados: histórico de ordens → payoff realizado
=============================================================
Cruza as trocas de posição registradas em historico_ordens.xlsx e calcula
o retorno realizado de cada troca (holding-period return: do preço de
entrada até o preço da ordem seguinte do mesmo ticker — a estratégia é
position-based, não tem horizonte fixo).

Uso:
    python resultados.py

Output:
    resultados/resultados_YYYY_MM_DD.xlsx  (abas: trades_fechados,
    posicoes_abertas, resumo)
"""

from pathlib import Path
from datetime import date

import pandas as pd

PASTA     = Path(__file__).parent
HOJE      = date.today()
HISTORICO = PASTA / "historico_ordens.xlsx"
SAIDA     = PASTA / "resultados" / f"resultados_{HOJE:%Y_%m_%d}.xlsx"
SAIDA.parent.mkdir(parents=True, exist_ok=True)

N_MIN_AMOSTRA = 20  # abaixo disso, resumo é só indicativo


def _carregar_historico() -> pd.DataFrame:
    df = pd.read_excel(HISTORICO)
    # Reruns manuais do workflow (workflow_dispatch) recalculam o "change"
    # do dia a partir do zero e podem duplicar a mesma troca de posição
    # (mesmo ticker/data/ordem) -- mantém só a primeira ocorrência.
    df = df.drop_duplicates(subset=["ticker", "data", "ordem"]).copy()
    df["data"] = pd.to_datetime(df["data"])
    return df.sort_values(["ticker", "data"]).reset_index(drop=True)


def _trades(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Para cada ticker, cada ordem vira um trade que fecha na ordem
    seguinte do mesmo ticker (troca de posição). A última ordem de cada
    ticker fica em aberto (sem preço de saída ainda)."""
    fechados, abertos = [], []
    for ticker, sub in df.groupby("ticker"):
        sub = sub.sort_values("data").reset_index(drop=True)
        for i in range(len(sub) - 1):
            entrada, saida = sub.iloc[i], sub.iloc[i + 1]
            lado = 1 if entrada["ordem"] == "Compra" else -1
            ret = lado * (saida["price"] / entrada["price"] - 1)
            fechados.append({
                "ticker":        ticker,
                "ordem":         entrada["ordem"],
                "hilo":          int(entrada["hilo"]),
                "data_entrada":  entrada["data"].date(),
                "preco_entrada": float(entrada["price"]),
                "data_saida":    saida["data"].date(),
                "preco_saida":   float(saida["price"]),
                "retorno":       round(float(ret), 4),
                "acerto":        int(ret > 0),
            })
        ultima = sub.iloc[-1]
        abertos.append({
            "ticker":        ticker,
            "ordem":         ultima["ordem"],
            "hilo":          int(ultima["hilo"]),
            "data_entrada":  ultima["data"].date(),
            "preco_entrada": float(ultima["price"]),
        })
    return pd.DataFrame(fechados), pd.DataFrame(abertos)


def _resumo(df_fechados: pd.DataFrame) -> pd.DataFrame:
    if df_fechados.empty:
        return pd.DataFrame()
    linhas = [{
        "grupo":         "geral",
        "n":             len(df_fechados),
        "acerto":        round(float(df_fechados["acerto"].mean()), 3),
        "retorno_medio": round(float(df_fechados["retorno"].mean()), 4),
        "retorno_total": round(float(df_fechados["retorno"].sum()), 4),
    }]
    for ordem, sub in df_fechados.groupby("ordem"):
        linhas.append({
            "grupo":         f"ordem_{ordem}",
            "n":             len(sub),
            "acerto":        round(float(sub["acerto"].mean()), 3),
            "retorno_medio": round(float(sub["retorno"].mean()), 4),
            "retorno_total": round(float(sub["retorno"].sum()), 4),
        })
    return pd.DataFrame(linhas)


def main() -> None:
    if not HISTORICO.exists():
        print("historico_ordens.xlsx não encontrado.")
        return

    df = _carregar_historico()
    df_fechados, df_abertos = _trades(df)

    print(f"Trades fechados: {len(df_fechados)}  |  posições abertas: {len(df_abertos)}")
    if len(df_fechados) < N_MIN_AMOSTRA:
        print(f"AVISO: amostra pequena (N={len(df_fechados)} < {N_MIN_AMOSTRA}) "
              f"— acompanhar tendência, não tirar conclusão.")
    if not df_fechados.empty:
        print(f"Acerto: {df_fechados['acerto'].mean():.1%}  |  "
              f"retorno médio: {df_fechados['retorno'].mean():.2%}  |  "
              f"retorno total: {df_fechados['retorno'].sum():.2%}")

    df_resumo = _resumo(df_fechados)
    with pd.ExcelWriter(SAIDA, engine="openpyxl") as writer:
        df_fechados.to_excel(writer, sheet_name="trades_fechados", index=False)
        df_abertos.to_excel(writer, sheet_name="posicoes_abertas", index=False)
        df_resumo.to_excel(writer, sheet_name="resumo", index=False)

    print(f"\nSalvo em: {SAIDA}")


if __name__ == "__main__":
    main()
