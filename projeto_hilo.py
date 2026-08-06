
import os
import pandas as pd
import numpy as np
import requests
import yfinance as yf
import time
from tvDatafeed import TvDatafeed, Interval
import datetime

TV_USERNAME = os.getenv("TV_USERNAME")
TV_PASSWORD = os.getenv("TV_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
#hoje = pd.to_datetime("2026-07-17").date()
hoje = pd.to_datetime("today").date()
hoje_string = hoje.strftime("%d-%m-%Y")

tv = TvDatafeed(TV_USERNAME, TV_PASSWORD)

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
    "VBBR3": 48
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
df_final['data']=hoje
df_send=df_final[['data','ticker','ordem','price','hilo']]

df_string = df_send.to_string(index=False)

# Salva o histórico de ordens em Excel, servindo de base para o cálculo futuro
# de payoff e taxa de acerto das previsões.
HISTORICO_PATH = "historico_ordens.xlsx"
if not df_send.empty:
    if os.path.exists(HISTORICO_PATH):
        df_historico = pd.read_excel(HISTORICO_PATH)
        df_historico = pd.concat([df_historico, df_send], ignore_index=True)
    else:
        df_historico = df_send.copy()
    df_historico.to_excel(HISTORICO_PATH, index=False)


# inserir data para nao esquecer vencimento de opcoes

def dias_uteis_ate_proximo_vencimento():
    hoje = datetime.date.today()
    
    def calcular_terceira_sexta(ano, mes):
        primeiro_dia = datetime.date(ano, mes, 1)
        offset_sexta = (4 - primeiro_dia.weekday() + 7) % 7
        primeira_sexta = primeiro_dia + datetime.timedelta(days=offset_sexta)
        return primeira_sexta + datetime.timedelta(weeks=2)

    # Identifica o vencimento correto (deste mês ou do próximo)
    vencimento_alvo = calcular_terceira_sexta(hoje.year, hoje.month)
    if hoje > vencimento_alvo:
        if hoje.month == 12:
            vencimento_alvo = calcular_terceira_sexta(hoje.year + 1, 1)
        else:
            vencimento_alvo = calcular_terceira_sexta(hoje.year, hoje.month + 1)
            
    # Lista oficial de feriados nacionais e da B3 (Exemplo focado em 2026)
    # Adicione ou remova datas conforme o ano corrente
    feriados = [
        '2026-01-01',  # Confraternização Universal
        '2026-02-16',  # Carnaval
        '2026-02-17',  # Carnaval
        '2026-04-03',  # Sexta-feira Santa
        '2026-04-21',  # Tiradentes
        '2026-05-01',  # Dia do Trabalho
        '2026-06-04',  # Corpus Christi
        '2026-07-09',  # Data Magna de SP (Feriado B3)
        '2026-09-07',  # Independência do Brasil
        '2026-10-12',  # Nossa Sra. Aparecida
        '2026-11-02',  # Finados
        '2026-11-15',  # Proclamação da República
        '2026-11-20',  # Dia da Consciência Negra
        '2026-12-25',  # Natal
    ]
    
    # Converte os feriados para o formato aceito pelo NumPy
    feriados_np = np.array(feriados, dtype='datetime64[D]')
    
    # Converte as datas limites para o formato NumPy
    data_inicio = np.datetime64(hoje)
    data_fim = np.datetime64(vencimento_alvo)
    
    # Calcula os dias úteis (exclui finais de semana e feriados listados)
    # Nota: O np.busday_count por padrão não inclui a data final no cálculo.
    dias_uteis = np.busday_count(data_inicio, data_fim, holidays=feriados_np)
    
    return vencimento_alvo, dias_uteis

# Execução do script
data_vencimento, dias_uteis_faltam = dias_uteis_ate_proximo_vencimento()

venc_opc1=f"Próximo vencimento de opções: {data_vencimento.strftime('%d/%m/%Y')}"
venc_opc2=f"Faltam exatamente: {dias_uteis_faltam} dias úteis"

# mensagem para o Telegram


MESSAGE = df_string

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
data_hoje = {"chat_id": TELEGRAM_CHAT_ID, "text": hoje_string}
saudacao = {"chat_id": TELEGRAM_CHAT_ID, "text": "HiLo - Sinais de Compra e Venda"}
data = {"chat_id": TELEGRAM_CHAT_ID, "text": MESSAGE}
venc_opc1_msn = {"chat_id": TELEGRAM_CHAT_ID, "text": venc_opc1}
venc_opc2_msn = {"chat_id": TELEGRAM_CHAT_ID, "text": venc_opc2}

response1 = requests.post(url, data=saudacao, timeout=30)
response0 = requests.post(url, data=data_hoje, timeout=30)
response = requests.post(url, data=data, timeout=30)
response2 = requests.post(url, data=venc_opc1_msn, timeout=30)
response2 = requests.post(url, data=venc_opc2_msn, timeout=30)

print(response.json())  # Para verificar a resposta
print(df_string)


