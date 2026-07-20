
import os
import pandas as pd
import numpy as np
import requests
import yfinance as yf
import time
from tvDatafeed import TvDatafeed, Interval

TV_USERNAME = os.getenv("TV_USERNAME")
TV_PASSWORD = os.getenv("TV_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

hoje = pd.to_datetime("today").date()
hoje_string = hoje.strftime("%d-%m-%Y")

tv = TvDatafeed(TV_USERNAME, TV_PASSWORD, chromedriver_path="chromedriver")

def importar_tradingview(ticker, hoje = pd.to_datetime("today").date()):
    tentativa = 0
    while tentativa < 5:  # Tenta duas vezes antes de desistir
        try:

            exchange = 'BMFBOVESPA'

            df = tv.get_hist(ticker, exchange, interval=Interval.in_daily, n_bars=100)
            df=df.drop(["symbol"], axis=1)
            df = df.sort_values("datetime")
            df.index.name = 'Date'
            df.index = df.index.date
            df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close','volume': 'Volume',})
            
            # tratar outliers
            ret =df["Close"].pct_change()
            med = ret.median()
            mad = np.median(np.abs(ret - med))
            z_robusto = 0.6745 * (ret - med) / mad
            outlier = np.abs(z_robusto) > 8
            df.loc[outlier, "Close"] = np.nan
            df["Close"] = df["Close"].interpolate(method="linear")
 
            break  # Sai do loop se a requisição for bem-sucedida
        except Exception as e:
            print(f"Erro ao processar {ticker}: {e}")
            tentativa += 1
            if tentativa < 5:
                print(f"Tentando novamente em 15 segundos...")
                time.sleep(15)
            else:
                print(f"Falha definitiva para {ticker}, passando para o próximo.")
    return df

df = pd.DataFrame()
df_final= pd.DataFrame(columns=['ticker', 'price', 'hilo', 'posicao', 'change'])
Ativo_hilo = {
    "ALOS3": 28,
    "ALPA4": 31,
    "BBAS3": 30,
    "BEEF3": 16,
    "BHIA3": 12,
    "BOVA11": 26,
    "BPAC11": 45,
    "BRKM5": 61,
    "CMIN3": 10,
    "CSNA3": 22,
    "CXSE3": 49,
    "ENEV3": 20,
    "EZTC3": 9,
    "GMAT3": 26,
    "HYPE3": 27,
    "JHSF3": 22,
    "MGLU3": 20,
    "MOVI3": 25,
    "MRVE3": 30,
    "PETR4": 23,
    "POMO4": 20,
    "PRIO3": 8,
    "PSSA3": 16,
    "RADL3": 63,
    "RDOR3": 35,
    "SMAL11": 31,
    "SUZB3": 11,
    "USIM5": 11,
    "VBBR3": 48,
    "WEGE3": 87
}
for ativo, valor in Ativo_hilo.items():
    ticker = ativo
    n_hilo=valor
    try:
        df = yf.download(ticker+'.SA', start='2000-01-01', end=hoje, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.date
        df = df[df['Volume'] != 0]

        df_tradingview = importar_tradingview(ticker, hoje)
        df_tradingview = df_tradingview.loc[df_tradingview.index > df.index[-1]]
        # Garante que as colunas fiquem na mesma ordem antes de concatenar
        df_tradingview = df_tradingview[df.columns]

        # Agora a concatenação será perfeita
        df = pd.concat([df, df_tradingview])
        df["hi"]=df["High"].rolling(n_hilo).mean().shift(1).round(2)
        df["lo"]=df["Low"].rolling(n_hilo).mean().shift(1).round(2)
        df['sinal'] = np.where( df['Close'] > df['hi'],1,np.where(df['Close'] < df['lo'], -1, 0))
        df['posicao'] = df['sinal'].replace(0, np.nan).ffill().fillna(0)
        df['change']=np.where(df['posicao']!=df['posicao'].shift(1),1,0)
        i = len(df_final)
        df_final.loc[i] = {'ticker': ticker,'price': df['Close'].iloc[-1],'hilo': n_hilo,'posicao': df['posicao'].iloc[-1],'change': df['change'].iloc[-1]}
    except Exception as e:
        print(f"Erro ao processar {ticker}: {e}")
    
df_final=df_final[df_final['change'] == 1]
df_final['ordem']=np.where(df_final['posicao']==1,'Compra','Venda')
df_send=df_final[['ticker','ordem','price','hilo']]

df_string = df_send.to_string(index=False)

MESSAGE = df_string

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
data_hoje = {"chat_id": TELEGRAM_CHAT_ID, "text": hoje_string}
saudacao = {"chat_id": TELEGRAM_CHAT_ID, "text": "HiLo - Sinais de Compra e Venda"}
data = {"chat_id": TELEGRAM_CHAT_ID, "text": MESSAGE}


response1 = requests.post(url, data=saudacao, timeout=30)
response0 = requests.post(url, data=data_hoje, timeout=30)
response = requests.post(url, data=data, timeout=30)
print(response.json())  # Para verificar a resposta
print(df_string)


