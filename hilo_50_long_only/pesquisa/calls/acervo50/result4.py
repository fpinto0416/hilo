import pandas as pd, numpy as np, os
from scipy import stats
pd.set_option("display.width",260)
P=pd.read_parquet("trava.parquet"); G=pd.read_csv("spreads.csv").set_index("ticker")
CDI_D=(1.10)**(1/252)-1; CUSTO_ACAO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25
# filtro de evento societario, igual ao aplicado na call seca
DB="/app/projeto_MIA26/database"; cache={}
def aj(t):
    if t not in cache:
        p=f"{DB}/{t}.xlsx"
        cache[t]=pd.read_excel(p,index_col=0,parse_dates=True).sort_index()["Close"] if os.path.exists(p) else None
    return cache[t]
d=[]
for _,x in P.iterrows():
    s=aj(x.ticker)
    try: a=float(s.asof(x.d_ent)); b=float(s.asof(x.d_sai)); d.append(abs((x.s_sai/x.s_ent-1)-(b/a-1)))
    except Exception: d.append(np.nan)
P["dif"]=d; n0=len(P); P=P[~(P.dif.notna()&(P.dif>0.15))].copy()
print(f"descartadas por evento societario: {n0-len(P)}")
P["dias"]=(P.d_sai-P.d_ent).dt.days.clip(lower=1)
P["r_acao"]=P.s_sai/P.s_ent-1
P=P[(P.delta_liq>0.05)&(P.p_liq_ent>0)]
def custo(sp):
    """premio liquido pago na entrada e recebido na saida, ja com spread
    nas DUAS pernas. Liquidacao no vencimento nao paga spread."""
    ent=P.p_l_ent*(1+sp)-P.p_s_ent*(1-sp)
    liq=P.motivo.str.startswith("liquidacao")
    sai=np.where(liq, P.p_liq_sai, P.p_l_sai*(1-sp)-P.p_s_sai*(1+sp))
    return ent, sai
def cart(D,spf,mask=None):
    Wc=[];Wa=[]
    for t,g in D.groupby("ticker"):
        sp=spf(t); g=g.sort_values("d_ent"); vc=va=1.0; d_ant=INI; ep_ant=None
        for _,L in g.iterrows():
            f=(1+CDI_D)**int(max((L.d_ent-d_ant).days,0)*252/365); vc*=f; va*=f
            liq=L.motivo.startswith("liquidacao")
            ent=L.p_l_ent*(1+sp)-L.p_s_ent*(1-sp)
            sai=L.p_liq_sai if liq else (L.p_l_sai*(1-sp)-L.p_s_sai*(1+sp))
            if ent<=0: d_ant=L.d_sai; ep_ant=L.ep; continue
            w=min(ent/(L.delta_liq*L.s_ent),1.0)
            n_du=max(int(L.dias*252/365),1)
            vc*=1+w*(sai/ent-1)+(1-w)*((1+CDI_D)**n_du-1)
            c=(CUSTO_ACAO if L.ep!=ep_ant else 0)+(CUSTO_ACAO if L.motivo.startswith(("saida","liquidacao")) else 0)
            va*=1+L.r_acao-c; d_ant=L.d_sai; ep_ant=L.ep
        f=(1+CDI_D)**int(max((FIM-d_ant).days,0)*252/365); vc*=f; va*=f
        Wc.append(vc);Wa.append(va)
    return (np.mean(Wc)**(1/ANOS)-1)*100,(np.mean(Wa)**(1/ANOS)-1)*100
ent,sai=custo(0.0); P["r_trava"]=sai/ent-1
print(f"\npernas: {len(P):,} | w mediano {(ent/(P.delta_liq*P.s_ent)).median()*100:.1f}% (call seca 8,2%)")
print(f"retorno por perna: mediana {P.r_trava.median()*100:+.1f}%  media {P.r_trava.mean()*100:+.1f}%")
print(f"maximo por perna: {P.r_trava.max()*100:+.0f}%  (call seca chegava a +3.297%)")
print("\nretorno medio por tipo de saida:")
print(P.groupby("motivo").r_trava.agg(n="size",mediana=lambda x:x.median()*100,media=lambda x:x.mean()*100).round(1).to_string())
print("\n=== CARTEIRA equal-weight, 50 ativos, 2015-2026 ===")
res=[]
for rot,spf in [("mid-a-mid (0%)",lambda t:0.0),("p25 medido",lambda t:G.loc[t,"p25"]/100),
                ("mediana medida",lambda t:G.loc[t,"mediana"]/100)]:
    c,a=cart(P,spf); res.append(dict(Execucao=rot,Trava_aa=c,Acao_aa=a,Dif_pp=c-a))
print(pd.DataFrame(res).round(2).to_string(index=False))
print("\nbaseline acao long-only COMPLETA = 14,39% a.a.")
print("\nexigindo liquidez minima nas duas pernas:")
for m in [1,5,10,20]:
    D=P[P.neg_ent>=m]
    if len(D)<200: continue
    cm,a=cart(D,lambda t:0.0); cp,_=cart(D,lambda t:G.loc[t,"p25"]/100)
    print(f"  min {m:>2} negocios: {len(D):>5} pernas | mid {cm:>6.2f}% | p25 {cp:>6.2f}% | acao {a:>5.2f}%")
