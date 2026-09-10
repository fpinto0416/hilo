import pandas as pd, numpy as np, json
from scipy import stats
pd.set_option("display.width",260)
P=pd.read_parquet("pernas.parquet")
CDI_D=(1.10)**(1/252)-1; CUSTO_ACAO=30/10000
P=P[P.delta.notna() & (P.delta>0.2) & (P.delta<0.9)].copy()
P["dias"]=(P.d_sai-P.d_ent).dt.days
P["w"]=P.p_ent/(P.delta*P.s_ent)          # fracao do capital no premio
P=P[(P.w>0)&(P.w<=1)]
P["r_call"]=P.p_sai/P.p_ent-1
P["r_acao"]=P.s_sai/P.s_ent-1
print(f"pernas usadas: {len(P):,} | ativos: {P.ticker.nunique()} | w mediano: {P.w.median()*100:.1f}%\n")

def sleeves(sp):
    n_du=(P.dias*252/365).clip(lower=1).astype(int)
    rc=((1+P.r_call)*(1-sp)/(1+sp))-1
    sc=P.w*rc+(1-P.w)*((1+CDI_D)**n_du-1)
    # acao paga 30bps so na entrada e na saida do EPISODIO, nao por perna
    prim=~P.duplicated(["ticker","ep"]); ult=P.motivo=="saida"
    sa=P.r_acao - CUSTO_ACAO*(prim.astype(float)+ult.astype(float))
    return sc,sa

print("=== TESTE PAREADO POR PERNA (mesmas datas, mesmo sinal) ===")
for rot,sp in [("mid-a-mid (0%)",0.0),("2%",0.02),("5%",0.05),("10%",0.10),("20%",0.20)]:
    sc,sa=sleeves(sp); d=(sc-sa).values
    t_,p_=stats.ttest_1samp(d,0)
    print(f"  {rot:>16}: media {d.mean()*100:+.3f} pp/perna  t={t_:+5.2f}  p={p_:.4f}  "
          f"call ganha em {(d>0).mean()*100:.1f}%")

print("\n=== CARTEIRA equal-weight dos 50 ativos, 2015-2026 ===")
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09")
ANOS=(FIM-INI).days/365.25
def riqueza(sp):
    Wc=[];Wa=[]
    for t,g in P.groupby("ticker"):
        g=g.sort_values("d_ent"); vc=va=1.0; d_ant=INI; ep_ant=None
        for _,L in g.iterrows():
            gap=max((L.d_ent-d_ant).days,0); f=(1+CDI_D)**int(gap*252/365)
            vc*=f; va*=f
            n_du=max(int(L.dias*252/365),1)
            rc=((1+L.r_call)*(1-sp)/(1+sp))-1
            vc*=1+L.w*rc+(1-L.w)*((1+CDI_D)**n_du-1)
            c=(CUSTO_ACAO if L.ep!=ep_ant else 0)+(CUSTO_ACAO if L.motivo=="saida" else 0)
            va*=1+L.r_acao-c
            d_ant=L.d_sai; ep_ant=L.ep
        f=(1+CDI_D)**int(max((FIM-d_ant).days,0)*252/365)
        Wc.append(vc*f); Wa.append(va*f)
    return (np.mean(Wc)**(1/ANOS)-1)*100, (np.mean(Wa)**(1/ANOS)-1)*100
linhas=[]
for rot,sp in [("mid-a-mid",0.0),("2%",0.02),("5%",0.05),("10%",0.10),("20%",0.20)]:
    c,a=riqueza(sp); linhas.append(dict(Execucao=rot,Call_aa=c,Acao_aa=a,Dif_pp=c-a))
print(pd.DataFrame(linhas).round(2).to_string(index=False))
P.to_parquet("pernas2.parquet",index=False)
