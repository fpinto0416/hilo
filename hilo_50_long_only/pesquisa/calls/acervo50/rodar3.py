import json, pandas as pd, numpy as np, warnings
warnings.filterwarnings("ignore")
from motor3 import simular
from motor2 import sinal_hilo, episodios
C=pd.read_parquet("calls.parquet"); S=pd.read_parquet("spot.parquet")
bons=json.load(open("mapa.json"))["bons"]
out=[]
for i,t in enumerate(bons,1):
    try: p=simular(t,C,S)
    except Exception as e: print(f"  {t}: ERRO {e}"); continue
    if p is not None: out.append(p)
    if i%10==0: print(f"  ...{i}/{len(bons)}",flush=True)
P=pd.concat(out,ignore_index=True)
P.to_parquet("pernas3.parquet",index=False)
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09")
tot=sum(len(episodios(sinal_hilo(t,50,INI,FIM))) for t in bons if sinal_hilo(t,50,INI,FIM) is not None)
cob=P.groupby(["ticker","ep"]).ngroups
print(f"\npernas: {len(P):,} | ativos: {P.ticker.nunique()} | episodios cobertos: {cob} de {tot} ({cob/tot*100:.0f}%)")
print(f"delta entrada: p05 {P.delta.quantile(.05):.3f} mediana {P.delta.median():.3f} p95 {P.delta.quantile(.95):.3f}")
print(f"moneyness |ln(K/S)|: mediana {P.money_ent.abs().median():.4f} p95 {P.money_ent.abs().quantile(.95):.4f}")
print(f"dias p/ venc na entrada: mediana {P.dc_ent.median():.0f}")
print(f"negocios do contrato na entrada: mediana {P.neg_ent.median():.0f}")
print("\ncomo cada perna terminou:")
print((P.motivo.value_counts()/len(P)*100).round(1).to_string())
