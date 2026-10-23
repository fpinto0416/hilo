import sys, glob, pathlib, pandas as pd, numpy as np, collections
ACERVO=pathlib.Path("/app/acervo_opcoes_b3")
TICKERS="""BOVA11 BBAS3 PETR4 ITUB4 SMAL11 CSNA3 BBDC4 VALE3 CSAN3 ITSA4 TAEE11 SUZB3
TIMS3 VAMO3 MGLU3 POMO4 JHSF3 ABEV3 EZTC3 SBSP3 BRAV3 WEGE3 CSMG3 BBSE3 EQTL3 COGN3
EMBJ3 RENT3 DIRR3 MRVE3 RAIZ4 SIMH3 AXIA3 CXSE3 EGIE3 AURA33 BPAC11 VBBR3 RAIL3 ALOS3
ECOR3 KLBN11 IRBR3 VIVT3 AZZA3 PSSA3 ITUB3 USIM5 CMIN3 IGTI11 ENEV3 FLRY3 CEAB3 GMAT3
XPBR31 TOTS3 BRAP4 HAPV3 MOVI3 SLCE3 BBDC3 CVCB3 QUAL3 SMFT3 BEEF3 MBRF3 VIVA3 CYRE3
RDOR3 ORVR3 BRSR6 HYPE3 RECV3 MULT3 WIZC3 RAPT4 ROXO34 GRND3 CPLE3 ENGI11 YDUQ3""".split()
# ISIN de cada ticker, a partir do spot (amostra ampla de datas)
isin_por_ticker={}
arqs=sorted(glob.glob(str(ACERVO/"data/spot/*/*.parquet")))
for p in arqs[::60]:
    d=pd.read_parquet(p, columns=["ticker","isin"])
    for t,i in d[d.ticker.isin(TICKERS)].itertuples(index=False):
        isin_por_ticker.setdefault(t,collections.Counter())[i]+=1
isin_por_ticker={t:c.most_common(1)[0][0] for t,c in isin_por_ticker.items()}
print(f"tickers com spot no acervo: {len(isin_por_ticker)} de {len(TICKERS)}")
faltam=[t for t in TICKERS if t not in isin_por_ticker]
if faltam: print("sem spot:", " ".join(faltam))
alvo=set(isin_por_ticker.values())
# quantos pregoes cada isin tem call negociada
dias=collections.Counter()
opc=sorted(glob.glob(str(ACERVO/"data/opcoes/*/*.parquet")))
for p in opc[::10]:
    d=pd.read_parquet(p, columns=["tipo","isin"])
    for i in d[(d.tipo=="C") & d["isin"].isin(alvo)]["isin"].unique(): dias[i]+=1
n=len(opc[::10])
inv={v:k for k,v in isin_por_ticker.items()}
linhas=[(inv[i], dias.get(i,0)/n*100) for i in alvo]
linhas.sort(key=lambda x:-x[1])
bons=[t for t,p in linhas if p>=50]
print(f"\ncom call negociada em >=50% dos pregoes amostrados: {len(bons)}")
print(" ".join(bons))
ruins=[(t,p) for t,p in linhas if p<50]
print(f"\nabaixo de 50%: {len(ruins)}")
print(" ".join(f"{t}({p:.0f}%)" for t,p in ruins))
import json; json.dump({"isin":isin_por_ticker,"bons":bons}, open("mapa.json","w"))
