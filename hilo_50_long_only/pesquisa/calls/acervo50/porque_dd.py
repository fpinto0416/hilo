import pandas as pd, numpy as np
P=pd.read_parquet("pernas3f.parquet"); G=pd.read_csv("spreads.csv").set_index("ticker")
CDI_D=(1.10)**(1/252)-1; CUSTO_ACAO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25
P=P[P.delta.notna()&(P.delta>0.05)&(P.delta<0.98)].copy()
P["dias"]=(P.d_sai-P.d_ent).dt.days.clip(lower=1)
P["w"]=P.p_ent/(P.delta*P.s_ent); P=P[(P.w>0)&(P.w<=1)]
P["r_call"]=P.p_sai/P.p_ent-1; P["r_acao"]=P.s_sai/P.s_ent-1

liq=P.motivo.str.startswith("liquidacao")
def sleeve_call(sp):
    rc=((1+P.r_call)*np.where(liq,1.0,(1-sp))/(1+sp))-1
    n=(P.dias*252/365).clip(lower=1).astype(int)
    return P.w*rc+(1-P.w)*((1+CDI_D)**n-1)
prim=~P.duplicated(["ticker","ep"]); ult=P.motivo.str.startswith(("saida","liquidacao"))
sa=P.r_acao-CUSTO_ACAO*(prim.astype(float)+ult.astype(float))
sc0=sleeve_call(0.0)
scp=sleeve_call(P.ticker.map(G["p25"])/100)

print("=== ASSIMETRIA: frequencia x tamanho ===")
for rot,s in [("call mid",sc0),("call p25",scp),("acao",sa)]:
    neg=(s<0).mean()*100
    print(f"{rot:9s}  pernas negativas {neg:5.1f}%   perda media {s[s<0].mean()*100:+6.2f}%   ganho medio {s[s>0].mean()*100:+6.2f}%   media {s.mean()*100:+5.2f}%")

print("\n=== A OPCAO PERDE MAIS VEZES, MENOS POR VEZ ===")
print("a call so ganha quando o ativo sobe o suficiente pra pagar o theta.")
r=P.r_acao
for lo,hi,rot in [(-9,-0.05,"ativo caiu >5%"),(-0.05,0.0,"ativo caiu 0-5%"),(0.0,0.05,"ativo subiu 0-5%"),(0.05,9,"ativo subiu >5%")]:
    m=(r>lo)&(r<=hi)
    print(f"{rot:18s} n={m.sum():5d}  call {sc0[m].mean()*100:+6.2f}%   acao {sa[m].mean()*100:+6.2f}%")

print("\n=== O QUE ACONTECE SE IGUALAR A EXPOSICAO ===")
print("ativo dimensionado com o MESMO delta da call (w*delta do spot) e resto no CDI:")
expo=P.w*P.delta
n=(P.dias*252/365).clip(lower=1).astype(int); cdi_leg=(1+CDI_D)**n-1
sa_eq=expo*(P.r_acao-CUSTO_ACAO*(prim.astype(float)+ult.astype(float)))+(1-expo)*cdi_leg
print(f"exposicao mediana ao ativo: {expo.median()*100:.1f}%  (w {P.w.median()*100:.1f}% x delta {P.delta.median():.2f})")
for rot,s in [("call mid",sc0),("acao 4% expo",sa_eq)]:
    print(f"{rot:13s} media/perna {s.mean()*100:+5.2f}%  pior {s.min()*100:+6.1f}%  desvio {s.std()*100:5.2f}%")

def curva(s):
    W={t:1.0 for t in P.ticker.unique()}; dant={t:INI for t in W}; out=[]
    for (i,L),v in zip(P.sort_values("d_sai").iterrows(), s.reindex(P.sort_values("d_sai").index)):
        t=L.ticker
        W[t]*=(1+CDI_D)**int(max((L.d_ent-dant[t]).days,0)*252/365)
        W[t]*=1+v; dant[t]=L.d_sai
        out.append((L.d_sai,np.mean(list(W.values()))))
    return pd.DataFrame(out,columns=["data","w"]).groupby("data").w.last()
def dd(x): x=np.asarray(x); return (x/np.maximum.accumulate(x)-1).min()*100
print("\ncarteira:")
for rot,s in [("call mid",sc0),("call p25",scp),("acao 100%",sa),("acao 4% expo",sa_eq)]:
    c=curva(s); print(f"  {rot:13s} {(c.iloc[-1]**(1/ANOS)-1)*100:+6.2f}% a.a.   DD {dd(c):+7.2f}%")
