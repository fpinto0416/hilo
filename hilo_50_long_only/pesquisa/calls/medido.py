import numpy as np, pandas as pd
exec(open("final2.py").read().split('for sp in [0.0')[0])
SP_MED = {"PETR4":6.65,"BBDC4":15.04,"BBAS3":17.75,"ITUB4":22.78,"VALE3":8.28,"BOVA11":8.11}
SP_P25 = {"PETR4":2.83,"BBDC4":7.87,"BBAS3":9.32,"ITUB4":12.00,"VALE3":3.79,"BOVA11":3.53}
out=[]
for t,g in P.groupby("ativo"):
    c0,a,an = curva(g,0.0)
    cm,_,_  = curva(g,SP_MED[t]/100)
    cp,_,_  = curva(g,SP_P25[t]/100)
    out.append(dict(ativo=t,n=len(g),anos=round(an,1),acao_aa=a,
                    call_mid=c0, call_p25=cp, call_mediana=cm,
                    sp_p25=SP_P25[t], sp_med=SP_MED[t]))
o=pd.DataFrame(out)
o["dif_mid"]=o.call_mid-o.acao_aa; o["dif_p25"]=o.call_p25-o.acao_aa; o["dif_med"]=o.call_mediana-o.acao_aa
print("Call ATM rolada vs acao, com o SPREAD MEDIDO de cada ativo (% do mid por lado)")
print(o[["ativo","n","anos","acao_aa","call_mid","dif_mid","sp_p25","call_p25","dif_p25","sp_med","call_mediana","dif_med"]].round(2).to_string(index=False))
print()
print(f"mediana dif a mid-a-mid : {o.dif_mid.median():+.2f} pp a.a.  (ganha em {(o.dif_mid>0).sum()}/6)")
print(f"mediana dif no spread p25: {o.dif_p25.median():+.2f} pp a.a.  (ganha em {(o.dif_p25>0).sum()}/6)")
print(f"mediana dif no spread mediano: {o.dif_med.median():+.2f} pp a.a.  (ganha em {(o.dif_med>0).sum()}/6)")
