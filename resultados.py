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

import numpy as np
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


# ── Métricas padrão de avaliação de sinal ─────────────────────────────────────

def _metricas(retornos: pd.Series) -> dict:
    """acerto, retorno médio/total, ganho/perda médios e profit factor (soma
    dos ganhos / soma das perdas em módulo — >1 significa que ganhos pesam
    mais que perdas). Esperança matemática não entra aqui: com trades de
    tamanho uniforme (1 unidade por sinal, sem position sizing), ela é
    idêntica a retorno_medio — reportar as duas seria redundante."""
    ganhos = retornos[retornos > 0]
    perdas = retornos[retornos <= 0]
    acerto = float((retornos > 0).mean())
    ganho_medio = float(ganhos.mean()) if len(ganhos) else 0.0
    perda_media = float(perdas.mean()) if len(perdas) else 0.0  # já <= 0
    soma_perdas = float(perdas.sum())
    profit_factor = (float(ganhos.sum()) / abs(soma_perdas)) if soma_perdas != 0 else np.nan
    return {
        "n":             len(retornos),
        "acerto":        round(acerto, 3),
        "retorno_medio": round(float(retornos.mean()), 4),
        "retorno_total": round(float(retornos.sum()), 4),
        "ganho_medio":   round(ganho_medio, 4),
        "perda_media":   round(perda_media, 4),
        "profit_factor": round(profit_factor, 3) if pd.notna(profit_factor) else np.nan,
    }


def _resumo(df_fechados: pd.DataFrame) -> pd.DataFrame:
    if df_fechados.empty:
        return pd.DataFrame()
    linhas = [{"grupo": "geral", **_metricas(df_fechados["retorno"])}]
    for ordem, sub in df_fechados.groupby("ordem"):
        linhas.append({"grupo": f"ordem_{ordem}", **_metricas(sub["retorno"])})
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
    df_resumo = _resumo(df_fechados)
    if not df_resumo.empty:
        geral = df_resumo[df_resumo["grupo"] == "geral"].iloc[0]
        print(f"Acerto: {geral['acerto']:.1%}  |  retorno médio: {geral['retorno_medio']:.2%}  |  "
              f"retorno total: {geral['retorno_total']:.2%}  |  "
              f"profit factor: {geral['profit_factor']:.2f}")
    with pd.ExcelWriter(SAIDA, engine="openpyxl") as writer:
        df_fechados.to_excel(writer, sheet_name="trades_fechados", index=False)
        df_abertos.to_excel(writer, sheet_name="posicoes_abertas", index=False)
        df_resumo.to_excel(writer, sheet_name="resumo", index=False)

    print(f"\nSalvo em: {SAIDA}")


if __name__ == "__main__":
    main()
