import pandas as pd, numpy as np, json
C=pd.read_parquet("calls.parquet"); S=pd.read_parquet("spot.parquet")
C=C.merge(S,on=["data","isin"],how="left")
C=C[C.spot.notna()&(C.spot>0)]
C["money"]=np.log(C.strike/C.spot)
d=C[(C.money.abs()<0.06)&C.dc.between(10,60)&(C.bid>0)&(C.ask>=C.bid)]
mid=(d.bid+d.ask)/2
d=d.assign(sp=(d.ask-d.bid)/mid/2*100)
d=d[d.sp.between(0,100)]
g=d.groupby("ticker")["sp"].agg(n="size",p25=lambda x:x.quantile(.25),mediana="median")
g=g[g.n>=200].sort_values("mediana")
g.to_csv("spreads.csv")
print(f"spread medido em {len(g)} dos 50 ativos (>=200 observacoes)\n")
print(g.round(1).to_string())
print(f"\nmediana entre ativos: p25 {g.p25.median():.1f}%  mediana {g.mediana.median():.1f}%")
print(f"ativos com spread mediano <= 5%: {(g.mediana<=5).sum()}")
print(f"ativos com p25 <= 5%: {(g.p25<=5).sum()}")
