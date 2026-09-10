# -*- coding: utf-8 -*-
"""
HiLo 50 long-only — rodada diaria.

Irmao do projeto_hilo.py (raiz do repo), com tres diferencas que vem
direto da pesquisa em pesquisa/ (ver RESULTADOS.md):

  1. HiLo FIXO em 50 pregoes, igual pra todo ativo. Nenhum criterio de
     selecao de janela bateu hilo fixo, e o agregado e plano de ~36 a 95
     pregoes -- selecionar dentro de regiao plana nao adiciona retorno.
     (O projeto_hilo.py usa janela por ativo, 24 das 29 abaixo de 36.)
  2. LONG-ONLY. A perna vendida e negativa na mediana em toda a faixa de
     hilo; cortar o short vence long+short em 99/99 hilos diarios.
     Aqui "Venda" nao e short: e zerar a posicao e ir pra caixa.
  3. Universo dos 81 ativos limpos (exclui os 17 com desdobramento nao
     ajustado + os 2 sem historico suficiente).

Sai no mesmo Telegram do hilo normal, com uma secao a parte.
"""
import os
import time
import datetime
import numpy as np
import pandas as pd
import requests
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HILO_N = int(os.getenv("HILO_LO_N", "50"))
# BRT, nao a hora do sistema (UTC no runner) -- mesmo motivo do projeto_hilo.py
hoje = pd.Timestamp.now(tz="America/Sao_Paulo").date()
hoje_string = hoje.strftime("%d-%m-%Y")

# 81 ativos limpos: a lista de 100 da pesquisa menos os 17 marcados como
# suspeitos (desdobramento nao ajustado) e menos AUAU3/IBOV11 (sem historico).
TICKERS = [
    "BOVA11", "BBAS3", "PETR4", "ITUB4", "SMAL11", "CSNA3", "BBDC4", "VALE3",
    "CSAN3", "ITSA4", "TAEE11", "SUZB3", "TIMS3", "VAMO3", "MGLU3", "POMO4",
    "JHSF3", "ABEV3", "EZTC3", "SBSP3", "BRAV3", "WEGE3", "CSMG3", "BBSE3",
    "EQTL3", "COGN3", "EMBJ3", "RENT3", "DIRR3", "MRVE3", "RAIZ4", "SIMH3",
    "AXIA3", "CXSE3", "EGIE3", "AURA33", "BPAC11", "VBBR3", "RAIL3", "ALOS3",
    "ECOR3", "KLBN11", "IRBR3", "VIVT3", "AZZA3", "PSSA3", "ITUB3", "USIM5",
    "CMIN3", "IGTI11", "ENEV3", "FLRY3", "CEAB3", "GMAT3", "XPBR31", "TOTS3",
    "BRAP4", "HAPV3", "MOVI3", "SLCE3", "BBDC3", "CVCB3", "QUAL3", "SMFT3",
    "BEEF3", "MBRF3", "VIVA3", "CYRE3", "RDOR3", "ORVR3", "BRSR6", "HYPE3",
    "RECV3", "MULT3", "WIZC3", "RAPT4", "ROXO34", "GRND3", "CPLE3", "ENGI11",
    "YDUQ3",
]

# Ativos com spread de call ATM MEDIDO (pesquisa/ACHADOS.md §12.4).
# ATENCAO: nao sao os unicos com opcao liquida -- o COTAHIST de 2025 tem
# call negociada em 155 raizes, e ~74 dos 81 ativos daqui estao entre
# elas. Estes 6 sao os que a base consultada na epoca cobria, e portanto
# os unicos com spread medido. Ampliar quando o acervo Parquet de
# opcoes-sinal-diario (data/opcoes/) tiver historico -- ver ACHADOS.md
# §12.1 e §12.6.
ATIVOS_COM_OPCAO = ["PETR4", "VALE3", "BOVA11", "BBDC4", "BBAS3", "ITUB4"]
# Spread mediano por lado, MEDIDO NO ACERVO (acervo-opcoes-b3, 2015-2026).
# Substituiu em 10/09 os valores que vinham de uma base de 12 ativos
# (6,7 / 8,3 / 8,1 / 15,0 / 17,8 / 22,8) -- amostra maior, todos menores.
SPREAD_MEDIANO_PCT = {"PETR4": 5.6, "VALE3": 7.7, "BOVA11": 8.3,
                      "BBDC4": 13.0, "BBAS3": 15.7, "ITUB4": 20.4}

# Prazo ALVO do vencimento, em dias corridos. Antes era "1o vencimento com
# mais de 20 dias". Mudou para ~60 em 10/09: a grade 30/45/60 mostrou que
# 60 corta a rolagem de 0,63 para 0,35 por episodio e e o unico prazo que
# melhora o resultado no custo realista (p25 4,95% contra 3,88-4,04%).
# ATENCAO: o ganho e economia de pedagio, nao retorno -- no mid-a-mid 60d e
# o PIOR dos quatro. Ver ACHADOS.md §12.12.
DC_ENTRADA_ALVO = 60
DC_ENTRADA_MIN = 22     # nunca entrar com menos que isso ate o vencimento


def estimar_ohlc_intraday(ticker, dia):
    """OHLC de hoje agregado dos candles de 1h -- mesma funcao do
    projeto_hilo.py (o candle diario do yfinance so sai depois do
    fechamento, e as vezes vem com OHLV zerados)."""
    for tentativa in range(5):
        try:
            df_1h = yf.download(ticker + ".SA", period="5d", interval="1h",
                                progress=False)
            if isinstance(df_1h.columns, pd.MultiIndex):
                df_1h.columns = df_1h.columns.get_level_values(0)
            df_1h.index = pd.to_datetime(df_1h.index)
            dh = df_1h[df_1h.index.date == dia]
            if dh.empty:
                return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
            o = pd.DataFrame({"Open": [dh["Open"].iloc[0]], "High": [dh["High"].max()],
                              "Low": [dh["Low"].min()], "Close": [dh["Close"].iloc[-1]],
                              "Volume": [dh["Volume"].sum()]}, index=[dia])
            o.index.name = "Date"
            return o
        except Exception as e:
            print(f"Erro OHLC intraday {ticker}: {e}")
            if tentativa < 4:
                time.sleep(15)
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])


def terceira_sexta(ano, mes):
    d = datetime.date(ano, mes, 1)
    return d + datetime.timedelta(days=(4 - d.weekday() + 7) % 7) + datetime.timedelta(weeks=2)


def vencimento_alvo(dia, dc_alvo=DC_ENTRADA_ALVO, dc_min=DC_ENTRADA_MIN):
    """Vencimento mensal (3a sexta) com prazo mais proximo de dc_alvo.

    Os vencimentos mensais sao ~30 dias apartados, entao "60 dias" nunca cai
    exato: dependendo do dia do mes o escolhido tem de ~36 a ~71 dias. Isso e
    do desenho da B3, nao da regra.
    """
    ano, mes = dia.year, dia.month
    cands = []
    for _ in range(6):
        v = terceira_sexta(ano, mes)
        dc = (v - dia).days
        if dc > dc_min:
            cands.append((abs(dc - dc_alvo), v))
        mes += 1
        if mes > 12:
            mes, ano = 1, ano + 1
    return min(cands)[1] if cands else None


# letra da serie de CALL por mes de vencimento (padrao B3)
LETRA_CALL = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F",
              7: "G", 8: "H", 9: "I", 10: "J", 11: "K", 12: "L"}


def recomendar_call(ticker, spot, dia):
    """Contrato alvo: call ATM do vencimento mensal mais proximo de 60 dias.

    Nao consulta cotacao de opcao -- o vencimento e deterministico (3a sexta)
    e o strike alvo e o spot. Na hora de executar, pegue o strike LISTADO mais
    proximo do alvo. O codigo do contrato sai como raiz+letra; o sufixo
    numerico varia por strike e nao e derivavel, por isso vai como prefixo.
    """
    v = vencimento_alvo(dia)
    if v is None:
        return None
    raiz = ticker[:4].upper()
    return {
        "ticker": ticker,
        "spot": round(float(spot), 2),
        "strike_alvo": round(float(spot), 2),
        "vencimento": v,
        "dias_corridos": (v - dia).days,
        "serie": f"{raiz}{LETRA_CALL[v.month]}",
        "spread_mediano_pct": SPREAD_MEDIANO_PCT.get(ticker, float("nan")),
    }


def calcular():
    linhas = []
    for ticker in TICKERS:
        try:
            df = yf.download(ticker + ".SA", start="2000-01-01", end=hoje, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df.empty:
                continue
            df.index = df.index.date
            df = df[df["Volume"] != 0]

            est = estimar_ohlc_intraday(ticker, hoje)
            if not est.empty:
                est = est.loc[est.index > df.index[-1]]
                if not est.empty:
                    df = pd.concat([df, est[df.columns]])
            if len(df) < HILO_N + 5:
                continue

            hi = df["High"].rolling(HILO_N).mean().shift(1)
            lo = df["Low"].rolling(HILO_N).mean().shift(1)
            sinal = np.where(df["Close"] > hi, 1, np.where(df["Close"] < lo, -1, 0))
            pos = pd.Series(sinal, index=df.index).replace(0, np.nan).ffill().fillna(0)
            # LONG-ONLY: -1 nao e short, e caixa
            comprado = (pos > 0).astype(int)
            trocou = int(comprado.iloc[-1] != comprado.iloc[-2]) if len(comprado) > 1 else 0

            linhas.append({
                "data": hoje, "ticker": ticker,
                "price": round(float(df["Close"].iloc[-1]), 2),
                "hilo": HILO_N,
                "hi": round(float(hi.iloc[-1]), 2) if pd.notna(hi.iloc[-1]) else np.nan,
                "lo": round(float(lo.iloc[-1]), 2) if pd.notna(lo.iloc[-1]) else np.nan,
                "posicao": int(comprado.iloc[-1]),
                "change": trocou,
            })
        except Exception as e:
            print(f"Erro ao processar {ticker}: {e}")
    return pd.DataFrame(linhas)


HIST_DIARIO = "historico_diario_long_only.xlsx"
HIST_ORDENS = "historico_ordens_long_only.xlsx"


def gravar(df):
    """Grava o log diario completo e o log de trocas.

    Idempotente por dia nos dois arquivos: substitui as linhas de 'hoje' em
    vez de so concatenar. Mesmo bug ja visto no projeto_hilo.py em 27/08,
    quando um rerun duplicou 29 linhas.
    """
    diario = df[["data", "ticker", "price", "hilo", "hi", "lo", "posicao"]].copy()
    diario["estado"] = np.where(diario["posicao"] == 1, "Comprado", "Caixa")
    diario = diario.drop(columns=["posicao"])
    if os.path.exists(HIST_DIARIO):
        h = pd.read_excel(HIST_DIARIO)
        h = h[h["data"] != hoje]
        diario = pd.concat([h, diario], ignore_index=True)
    diario.to_excel(HIST_DIARIO, index=False)

    trocas = df[df["change"] == 1].copy()
    if trocas.empty:
        return trocas
    trocas["ordem"] = np.where(trocas["posicao"] == 1, "Compra", "Zera")
    trocas = trocas[["data", "ticker", "ordem", "price", "hilo"]]
    if os.path.exists(HIST_ORDENS):
        h = pd.read_excel(HIST_ORDENS)
        h = h[~((h["data"] == hoje) & (h["ticker"].isin(trocas["ticker"])))]
        trocas = pd.concat([h, trocas], ignore_index=True)
        trocas.to_excel(HIST_ORDENS, index=False)
        return trocas[trocas["data"] == hoje]
    trocas.to_excel(HIST_ORDENS, index=False)
    return trocas


def montar_mensagem(df, trocas):
    comprados = df[df["posicao"] == 1]["ticker"].tolist()
    novas = trocas[trocas["ordem"] == "Compra"]["ticker"].tolist() if not trocas.empty else []
    zerou = trocas[trocas["ordem"] == "Zera"]["ticker"].tolist() if not trocas.empty else []

    p = [f"HiLo {HILO_N} LONG-ONLY — {hoje_string}", ""]
    p.append(f"Comprado em {len(comprados)} de {len(df)} ativos "
             f"({len(comprados)/max(len(df),1)*100:.0f}% do capital exposto)")
    p.append("")
    p.append(f"NOVAS COMPRAS ({len(novas)}): " + (", ".join(novas) if novas else "nenhuma"))
    p.append(f"ZEROU / FOI PRA CAIXA ({len(zerou)}): " + (", ".join(zerou) if zerou else "nenhuma"))
    p.append("")
    p.append("CARTEIRA COMPRADA:")
    p.append(", ".join(comprados) if comprados else "(vazia — tudo em caixa)")

    # calls sugeridas para os ativos comprados que tem opcao liquida
    alvo = [t for t in comprados if t in ATIVOS_COM_OPCAO]
    if alvo:
        p.append("")
        p.append("CALL ATM SUGERIDA (vencimento >20 dias corridos, rolar a <10):")
        for t in alvo:
            spot = float(df.loc[df["ticker"] == t, "price"].iloc[0])
            c = recomendar_call(t, spot, hoje)
            if c is None:
                continue
            p.append(f"  {t}: strike alvo ~{c['strike_alvo']:.2f} | venc "
                     f"{c['vencimento'].strftime('%d/%m/%Y')} ({c['dias_corridos']}d) | "
                     f"serie {c['serie']}* | spread tipico {c['spread_mediano_pct']:.0f}%/lado")
        p.append("")
        p.append("Aviso: a mid-a-mid a call rolada bate a acao (+3,3 pp a.a.), mas o")
        p.append("ponto de equilibrio e ~4-5% de spread por lado e o spread medido e")
        p.append("maior que isso em todos os 6 ativos. So execute perto do mid.")
    return "\n".join(p)


def enviar(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("(sem credenciais do Telegram — nao enviado)")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=30)
    print(r.json())


if __name__ == "__main__":
    df = calcular()
    if df.empty:
        raise SystemExit("nenhum ativo processado")
    trocas = gravar(df)
    msg = montar_mensagem(df, trocas)
    print(msg)
    enviar(msg)
