'''
------------------------------------------------------------
Author: Fabio da Costa Pinto
Email: fpinto0416@gmail.com
Created: Abril 2025
Last Update: 03/09/2026  (versão 4h)
License: Proprietary / Private Use
------------------------------------------------------------
Description:
    Coleta de candles de 4 HORAS via TradingView (tvDatafeed).

    Diferenças estruturais em relação à versão diária:
      - yfinance foi REMOVIDO. O Yahoo não oferece intervalo de 4h
        (só 1m/2m/5m/15m/30m/60m/90m/1d...) e limita intraday a ~730 dias.
        Não existe caminho híbrido para 4h.
      - O índice deixa de ser `date` e passa a ser DatetimeIndex tz-aware.
      - Barra em formação é descartada (evita vazamento de futuro).
      - Tratamento de outliers desligado por padrão em intraday.
------------------------------------------------------------
'''

import os
import time
import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from tvDatafeed import TvDatafeed, Interval

# ====================== CONFIGURAÇÃO ======================

USERNAME = os.getenv("TV_USERNAME", "YourTradingViewUsername")
PASSWORD = os.getenv("TV_PASSWORD", "YourTradingViewPassword")

PASTA_SAIDA = "database_4h"          # não sobrescreve a base diária
FORMATO = "parquet"                  # "parquet" (recomendado) | "xlsx"

MODO_4H = "nativo"                   # "nativo" = pede 4h ao TV
                                     # "resample_1h" = baixa 1h e agrega com âncora explícita
N_BARS = 20000                       # o TV corta bem antes disso em intraday
TZ_ALVO = "America/Sao_Paulo"
TZ_ORIGEM = "local"                  # "local" | "exchange"  (ver validar_timezone)
DESCARTAR_BARRA_EM_FORMACAO = True
TRATAR_OUTLIERS = False              # em 4h isso apaga gap de abertura, que é informação
PAUSA_ENTRE_REQS = 2.0               # o TV estrangula requisições em sequência
MAX_TENTATIVAS = 5

INTERVALO_HORAS = 4

# ====================== MAPEAMENTOS ======================

EXCHANGE_ESPECIAL = {
    'US10Y': 'TVC', 'GOLD': 'TVC', 'DXY': 'TVC',
    'UKOIL': 'FXCM',
    'BRENT': 'ActivTrades',
    'FEF1!': 'SGX',
    'CCM1!': 'BMFBOVESPA', 'IBOV': 'BMFBOVESPA',
    'SPX': 'SPCFD',
    'VIX': 'CBOE', 'ARKK': 'CBOE',
    'BTCUSD': 'Coinbase',
    'TFLO': 'NYSEArca', 'GLD': 'NYSEArca', 'SPY': 'NYSEArca',
}

# Fuso de cada exchange. Só o BMFBOVESPA é certo; o resto vale conferir
# com validar_timezone() antes de usar em feature cross-asset.
TZ_EXCHANGE = {
    'BMFBOVESPA': 'America/Sao_Paulo',
    'CBOE': 'America/New_York',
    'NYSEArca': 'America/New_York',
    'SPCFD': 'America/New_York',
    'TVC': 'UTC',
    'FXCM': 'UTC',
    'ActivTrades': 'UTC',
    'SGX': 'Asia/Singapore',
    'Coinbase': 'UTC',
}

# Hora de abertura do pregão, usada como âncora quando MODO_4H == "resample_1h".
ABERTURA_EXCHANGE = {
    'BMFBOVESPA': 9,
    'CBOE': 9,
    'NYSEArca': 9,
    'SPCFD': 0,
    'TVC': 0,
    'FXCM': 0,
    'ActivTrades': 0,
    'SGX': 9,
    'Coinbase': 0,
}


def exchange_de(ticker: str) -> str:
    return EXCHANGE_ESPECIAL.get(ticker, 'BMFBOVESPA')


# ====================== TRATAMENTO ======================

def _normalizar_indice(df: pd.DataFrame, exchange: str) -> pd.DataFrame:
    """
    O tvDatafeed devolve datetime NAIVE. A convenção depende da versão do
    pacote: normalmente é datetime.fromtimestamp(), ou seja, fuso da MÁQUINA.
    Em barra diária isso passa despercebido; em 4h desloca o candle inteiro.

    TZ_ORIGEM = "local"    -> assume fuso da máquina (comportamento padrão do pacote)
    TZ_ORIGEM = "exchange" -> assume que já veio no fuso da bolsa
    """
    idx = pd.DatetimeIndex(df.index)

    if TZ_ORIGEM == "local":
        tz_origem = dt.datetime.now().astimezone().tzinfo
    else:
        tz_origem = ZoneInfo(TZ_EXCHANGE.get(exchange, 'UTC'))

    idx = idx.tz_localize(tz_origem, ambiguous='NaT', nonexistent='shift_forward')
    df = df.copy()
    df.index = idx.tz_convert(ZoneInfo(TZ_ALVO))
    df.index.name = 'datetime'
    df = df[~df.index.isna()]
    df = df[~df.index.duplicated(keep='last')].sort_index()
    return df


def _descartar_barra_parcial(df: pd.DataFrame) -> pd.DataFrame:
    """
    A última barra de intraday quase sempre está em formação. Mantê-la é
    vazamento clássico: o backtest enxerga o close de um candle que ainda
    não fechou.
    """
    if df.empty:
        return df
    agora = pd.Timestamp.now(tz=ZoneInfo(TZ_ALVO))
    fim_da_ultima = df.index[-1] + pd.Timedelta(hours=INTERVALO_HORAS)
    if fim_da_ultima > agora:
        return df.iloc[:-1]
    return df


def _tratar_outliers(df: pd.DataFrame) -> pd.DataFrame:
    ret = df["Close"].pct_change()
    med = ret.median()
    mad = np.median(np.abs(ret - med))
    if mad == 0 or np.isnan(mad):
        return df
    z = 0.6745 * (ret - med) / mad
    df.loc[np.abs(z) > 8, "Close"] = np.nan
    df["Close"] = df["Close"].interpolate(method="linear")
    return df


def _resample_para_4h(df: pd.DataFrame, exchange: str) -> pd.DataFrame:
    """Agrega barras de 1h em 4h com âncora na abertura do pregão."""
    abertura = ABERTURA_EXCHANGE.get(exchange, 0)
    regra = {
        'Open': 'first', 'High': 'max', 'Low': 'min',
        'Close': 'last', 'Volume': 'sum',
    }
    regra = {k: v for k, v in regra.items() if k in df.columns}
    out = df.resample(
        f'{INTERVALO_HORAS}h',
        origin='start_day',
        offset=f'{abertura}h',
        label='left',
        closed='left',
    ).agg(regra)
    return out.dropna(subset=['Open'])


# ====================== DOWNLOAD ======================

tv = TvDatafeed(USERNAME, PASSWORD)


def importar_tradingview(ticker: str) -> pd.DataFrame | None:
    exchange = exchange_de(ticker)
    intervalo = Interval.in_4_hour if MODO_4H == "nativo" else Interval.in_1_hour

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            df = tv.get_hist(ticker, exchange, interval=intervalo, n_bars=N_BARS)
            if df is None or df.empty:
                raise ValueError("retorno vazio do TradingView")

            df = df.drop(columns=["symbol"], errors="ignore")
            df = df.rename(columns={
                'open': 'Open', 'high': 'High', 'low': 'Low',
                'close': 'Close', 'volume': 'Volume',
            })

            df = _normalizar_indice(df, exchange)

            if MODO_4H == "resample_1h":
                df = _resample_para_4h(df, exchange)

            if DESCARTAR_BARRA_EM_FORMACAO:
                df = _descartar_barra_parcial(df)

            if TRATAR_OUTLIERS:
                df = _tratar_outliers(df)

            return df

        except Exception as e:
            print(f"  [{tentativa}/{MAX_TENTATIVAS}] erro em {ticker}: {e}")
            if tentativa < MAX_TENTATIVAS:
                time.sleep(15)
    print(f"  falha definitiva em {ticker}")
    return None


def validar_timezone(ticker: str = "IBOV") -> None:
    """
    Rode isto UMA VEZ antes de confiar na base. Para um ativo do BMFBOVESPA,
    a distribuição de horas do índice tem que bater com o pregão (09h/13h/17h
    em barra de 4h). Se aparecer 05h, 06h ou 21h, TZ_ORIGEM está errado.
    """
    df = importar_tradingview(ticker)
    if df is None or df.empty:
        print("sem dados para validar")
        return
    print(f"\n=== validação de timezone: {ticker} ===")
    print(f"tz do índice: {df.index.tz}")
    print("horas presentes no índice:")
    print(df.index.hour.value_counts().sort_index())
    print(df.tail(6))


# ====================== TICKERS ======================

tickers = [
    "ABEV3", "ALOS3", "ALPA4", "AMBP3", "ASAI3", "AUAU3",
    "AURA33", "AURE3", "AXIA3", "AZZA3", "B3SA3", "BBAS3",
    "BBDC3", "BBDC4", "BBSE3", "BEEF3", "BHIA3", "BOVA11",
    "BOVV11", "BPAC11", "BRAP4", "BRAV3", "BRKM5", "BRSR6",
    "CEAB3", "CMIG4", "CMIN3", "COGN3", "CPFE3", "CPLE3",
    "CSAN3", "CSMG3", "CSNA3", "CURY3", "CVCB3", "CXSE3",
    "CYRE3", "DIRR3", "ECOR3", "EGIE3", "EMBJ3", "ENEV3",
    "ENGI11", "EQTL3", "EZTC3", "FESA4", "FLRY3", "GGBR4",
    "GMAT3", "GOAU4", "GRND3", "HAPV3", "HASH11", "HYPE3",
    "IBOV11", "IGTI11", "IRBR3", "ISAE4", "ITSA4", "ITUB3",
    "ITUB4", "JBSS32", "JHSF3", "KLBN11", "LREN3", "MBRF3",
    "MGLU3", "MOTV3", "MOVI3", "MRVE3", "MULT3", "NATU3",
    "NVDC34", "ORVR3", "PCAR3", "PETR3", "PETR4", "POMO4",
    "POSI3", "PRIO3", "PSSA3", "QUAL3", "RADL3", "RAIL3",
    "RAIZ4", "RAPT4", "RDOR3", "RECV3", "RENT3", "ROXO34",
    "SANB11", "SAPR11", "SBFG3", "SBSP3", "SIMH3", "SLCE3",
    "SMAL11", "SMFT3", "SMTO3", "SOJA3", "SUZB3", "TAEE11",
    "TIMS3", "TOTS3", "UGPA3", "UNIP6", "USIM5", "VALE3",
    "VAMO3", "VBBR3", "VIVA3", "VIVT3", "WEGE3", "WIZC3",
    "XPBR31", "YDUQ3",
]
tickers += ['DI11!', 'DXY', 'BRENT', 'DOL1!', 'SPX', 'IBOV', 'IDIV', 'IEE',
            'US10Y', 'GOLD', 'VIX', 'FEF1!', 'CCM1!']
tickers += ['WDO1!', 'WIN1!']
tickers += ['BTCUSD', 'ARKK', 'SPY', 'TFLO']
tickers += ["BOAC34"]

tickers = list(dict.fromkeys(tickers))  # remove duplicados (ENGI11/BRSR6 apareciam 2x)


# ====================== EXECUÇÃO ======================

def main():
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), PASTA_SAIDA)
    os.makedirs(pasta, exist_ok=True)

    falhas = []
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker}")
        df = importar_tradingview(ticker)
        if df is None or df.empty:
            falhas.append(ticker)
            time.sleep(PAUSA_ENTRE_REQS)
            continue

        if FORMATO == "parquet":
            caminho = os.path.join(pasta, f"{ticker}.parquet")
            df.to_parquet(caminho)
        else:
            # openpyxl não aceita datetime tz-aware
            caminho = os.path.join(pasta, f"{ticker}.xlsx")
            df.tz_localize(None).to_excel(caminho)

        print(f"  salvo: {len(df)} barras | {df.index[0]} -> {df.index[-1]}")
        time.sleep(PAUSA_ENTRE_REQS)

    if falhas:
        print(f"\nFalharam ({len(falhas)}): {falhas}")


if __name__ == "__main__":
    # validar_timezone("IBOV")   # rode isto primeiro, uma vez
    main()
