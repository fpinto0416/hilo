"""
Hilo — Resultados: histórico de ordens → payoff realizado
=============================================================
Cruza as trocas de posição registradas em historico_ordens.xlsx e calcula
o retorno realizado de cada troca (holding-period return: do preço de
entrada até o preço da ordem seguinte do mesmo ticker — a estratégia é
position-based, não tem horizonte fixo).

Três visões no resumo (discussão 19/08, mesmo ajuste do api_OMQS) --
"fechados" sozinho é enviesado: uma posição só "fecha" quando o HiLo troca
de lado, o que só acontece depois de um movimento contrário considerável.
Enquanto a tendência segue a favor, a posição nunca fecha e fica de fora da
conta de acerto -- viés de sobrevivência (só sobra quem já reverteu). Por
isso agora:
  - fechados     -- só o que já foi realizado (visão enviesada de sempre).
  - abertas_mtm  -- só as posições ainda abertas, marcadas a mercado com o
                     preço mais recente disponível em historico_diario.xlsx
                     (log diário completo, todo ticker/todo dia, adicionado
                     em projeto_hilo.py em 19/08 -- antes só existia
                     historico_ordens.xlsx, que só grava troca de posição e
                     não serve pra marcar a mercado). Enquanto esse log não
                     acumular histórico (começa a rodar no próximo cron),
                     essa visão fica vazia -- não quebra nada, só não tem
                     dado ainda.
  - combinado    -- as duas juntas. Leitura mais honesta do sinal como um
                     todo, sem o viés de só contar quem já perdeu.

Uso:
    python resultados.py

Output:
    resultados/resultados_YYYY_MM_DD.xlsx  (abas: trades_fechados,
    posicoes_abertas [com preco_atual/retorno MTM quando disponível], resumo)
"""

from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd

PASTA            = Path(__file__).parent
HOJE             = date.today()
HISTORICO        = PASTA / "historico_ordens.xlsx"
HISTORICO_DIARIO = PASTA / "historico_diario.xlsx"
SAIDA            = PASTA / "resultados" / f"resultados_{HOJE:%Y_%m_%d}.xlsx"
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


def _mtm_abertas(df_abertos: pd.DataFrame) -> pd.DataFrame:
    """Marca a mercado as posições ainda abertas com o preço mais recente
    disponível em historico_diario.xlsx (log diário completo -- todo
    ticker/todo dia, não só troca de posição). Se o arquivo ainda não
    existir, ou não tiver leitura mais nova que a entrada pro ticker,
    'retorno' fica NaN (sem quebrar nada -- só ainda sem dado)."""
    if df_abertos.empty:
        return df_abertos.assign(preco_atual=pd.Series(dtype=float), retorno=pd.Series(dtype=float))
    out = df_abertos.copy()
    if HISTORICO_DIARIO.exists():
        df_diario = pd.read_excel(HISTORICO_DIARIO)
        df_diario["data"] = pd.to_datetime(df_diario["data"])
        ultimo_preco = df_diario.sort_values("data").groupby("ticker")["price"].last()
    else:
        ultimo_preco = pd.Series(dtype=float)
    preco_atual = out["ticker"].map(ultimo_preco)
    out["preco_atual"] = preco_atual
    lado = np.where(out["ordem"] == "Compra", 1, -1)
    out["retorno"] = np.where(
        preco_atual.notna(),
        (lado * (preco_atual / out["preco_entrada"] - 1)).round(4),
        np.nan,
    )
    return out


# ── Métricas padrão de avaliação de sinal ─────────────────────────────────────

def _metricas(retornos: pd.Series) -> dict:
    """acerto, retorno médio/total, ganho/perda médios e profit factor (soma
    dos ganhos / soma das perdas em módulo — >1 significa que ganhos pesam
    mais que perdas). `retorno_medio` É o resultado esperado por operação
    (esperança matemática) -- com trades de tamanho uniforme (1 unidade por
    sinal, sem position sizing), esperança = acerto*ganho_medio +
    (1-acerto)*perda_media é algebricamente idêntico à média simples dos
    retornos, então não vira campo separado (reportar as duas seria
    redundante); só a leitura/rótulo muda conforme o contexto (20/08)."""
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


def _resumo_grupo(sub: pd.DataFrame, prefixo: str) -> list[dict]:
    """Linha 'prefixo' (todos) + uma por direção (prefixo_compra/venda).
    sub precisa ter colunas 'ordem' e 'retorno'; linhas sem retorno (NaN,
    ex. ainda sem leitura em historico_diario.xlsx) são descartadas antes de
    calcular; vazio não gera linha nenhuma (silencioso)."""
    sub = sub.dropna(subset=["retorno"]) if "retorno" in sub.columns else sub
    if sub.empty:
        return []
    linhas = [{"grupo": prefixo, **_metricas(sub["retorno"])}]
    for ordem, g in sub.groupby("ordem"):
        linhas.append({"grupo": f"{prefixo}_{ordem.lower()}", **_metricas(g["retorno"])})
    return linhas


def _resumo(df_fechados: pd.DataFrame, df_abertos_mtm: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    linhas += _resumo_grupo(df_fechados, "fechados")
    linhas += _resumo_grupo(df_abertos_mtm, "abertas_mtm")

    cols = ["ordem", "retorno"]
    partes = [d[cols] for d in (df_fechados, df_abertos_mtm) if not d.empty]
    combinado = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=cols)
    linhas += _resumo_grupo(combinado, "combinado")

    return pd.DataFrame(linhas)


def main() -> None:
    if not HISTORICO.exists():
        print("historico_ordens.xlsx não encontrado.")
        return

    df = _carregar_historico()
    df_fechados, df_abertos = _trades(df)
    df_abertos_mtm = _mtm_abertas(df_abertos)

    print(f"Trades fechados: {len(df_fechados)}  |  posições abertas: {len(df_abertos)}")
    if len(df_fechados) < N_MIN_AMOSTRA:
        print(f"AVISO: amostra pequena (N={len(df_fechados)} < {N_MIN_AMOSTRA}) "
              f"— acompanhar tendência, não tirar conclusão.")

    df_resumo = _resumo(df_fechados, df_abertos_mtm)

    def _print_grupo(rotulo: str, grupo: str) -> None:
        linha = df_resumo[df_resumo["grupo"] == grupo]
        if linha.empty:
            return
        g = linha.iloc[0]
        print(f"{rotulo}: acerto {g['acerto']:.1%}  |  resultado esperado por operação "
              f"{g['retorno_medio']:.2%}  |  retorno total {g['retorno_total']:.2%}  |  "
              f"profit factor {g['profit_factor']:.2f}  (N={int(g['n'])})")

    print()
    print("AVISO: 'fechados' sozinho é enviesado pra baixo -- uma posição só fecha quando o HiLo")
    print("troca de lado (movimento contrário considerável); quem está indo bem fica em 'abertas'")
    print("e nunca entra nessa conta. Ver 'combinado'.")
    _print_grupo("Fechados (viés: só quem já reverteu o suficiente pra trocar de lado)", "fechados")
    _print_grupo("Abertas, marcadas a mercado (retorno NÃO realizado)", "abertas_mtm")
    _print_grupo("Combinado (fechados + abertas MTM -- leitura mais honesta)", "combinado")
    if not HISTORICO_DIARIO.exists():
        print("\n(historico_diario.xlsx ainda não existe -- 'abertas_mtm'/'combinado' ficam vazios "
              "até o próximo cron gravar o primeiro log diário completo.)")

    with pd.ExcelWriter(SAIDA, engine="openpyxl") as writer:
        df_fechados.to_excel(writer, sheet_name="trades_fechados", index=False)
        df_abertos_mtm.to_excel(writer, sheet_name="posicoes_abertas", index=False)
        df_resumo.to_excel(writer, sheet_name="resumo", index=False)

    print(f"\nSalvo em: {SAIDA}")


if __name__ == "__main__":
    main()
