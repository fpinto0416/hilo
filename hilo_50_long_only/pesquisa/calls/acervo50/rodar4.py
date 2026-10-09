import json, pandas as pd, numpy as np, warnings
warnings.filterwarnings("ignore")
from motor4 import simular
from motor2 import sinal_hilo, episodios
C=pd.read_parquet("calls.parquet"); S=pd.read_parquet("spot.parquet")
bons=json.load(open("mapa.json"))["bons"]
out=[]
for i,t in enumerate(bons,1):
    try: p=simular(t,C,S)
    except Exception as e: print(f"  {t}: ERRO {e}"); continue
    if p is not None: out.append(p)
    if i%10==0: print(f"  ...{i}/{len(bons)}",flush=True)
P=pd.concat(out,ignore_index=True); P.to_parquet("trava.parquet",index=False)
cob=P.groupby(["ticker","ep"]).ngroups
print(f"\npernas: {len(P):,} | ativos {P.ticker.nunique()} | episodios cobertos {cob} de 2390 ({cob/2390*100:.0f}%)")
print(f"delta compra {P.d_l.median():.3f} | venda {P.d_s.median():.3f} | liquido {P.delta_liq.median():.3f}")
print(f"premio liquido/spot: mediana {(P.p_liq_ent/P.s_ent).median()*100:.2f}%  (call seca era ~4,6%)")
print(f"teto/premio: mediana {(P.teto/P.p_liq_ent).median():.1f}x")
print(P.motivo.value_counts(normalize=True).mul(100).round(1).to_string())
