import json, pandas as pd, numpy as np, warnings
warnings.filterwarnings("ignore")
from motor2 import simular
C=pd.read_parquet("calls.parquet"); S=pd.read_parquet("spot.parquet")
bons=json.load(open("mapa.json"))["bons"]
out=[]
for i,t in enumerate(bons,1):
    try: p=simular(t,C,S)
    except Exception as e: print(f"  {t}: ERRO {e}"); continue
    if p is None: print(f"  {t}: sem pernas"); continue
    out.append(p)
    if i%10==0: print(f"  ...{i}/{len(bons)}", flush=True)
P=pd.concat(out,ignore_index=True)
P.to_parquet("pernas.parquet",index=False)
print(f"\npernas: {len(P):,} | ativos: {P.ticker.nunique()} | episodios: {P.groupby(['ticker','ep']).ngroups}")
print(f"delta na entrada: p05 {P.delta.quantile(.05):.3f} mediana {P.delta.median():.3f} p95 {P.delta.quantile(.95):.3f}")
print(f"moneyness |ln(K/S)| na entrada: mediana {P.money_ent.abs().median():.4f}")
print(f"duracao mediana da perna: {(P.d_sai-P.d_ent).dt.days.median():.0f} dias corridos")
print(f"delta NaN (IV nao extraida): {P.delta.isna().mean()*100:.1f}%")
