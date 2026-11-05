import pandas as pd, numpy as np, os, warnings, json
warnings.filterwarnings("ignore")
pd.set_option("display.width",260)
G=pd.read_csv("spreads.csv").set_index("ticker")
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25
CUSTO_ACAO=30/10000
P0=pd.read_parquet("pernas3f.parquet")
P0=P0[P0.delta.notna()&(P0.delta>0.05)&(P0.delta<0.98)].copy()
P0["dias"]=(P0.d_sai-P0.d_ent).dt.days.clip(lower=1)
P0["w"]=P0.p_ent/(P0.delta*P0.s_ent); P0=P0[(P0.w>0)&(P0.w<=1)]
P0["r_call"]=P0.p_sai/P0.p_ent-1; P0["r_acao"]=P0.s_sai/P0.s_ent-1

def cart(P,spf,cdi_aa):
    cd=(1+cdi_aa/100)**(1/252)-1
    Wt={t:1.0 for t in P.ticker.unique()}; Wat=dict(Wt)
    dant={t:INI for t in Wt}; epant={t:None for t in Wt}
    for _,L in P.sort_values("d_sai").iterrows():
        t=L.ticker; sp=spf(t)
        f=(1+cd)**int(max((L.d_ent-dant[t]).days,0)*252/365); Wt[t]*=f; Wat[t]*=f
        liq=L.motivo.startswith("liquidacao")
        rc=((1+L.r_call)*(1.0 if liq else (1-sp))/(1+sp))-1
        n_du=max(int(L.dias*252/365),1)
        Wt[t]*=1+L.w*rc+(1-L.w)*((1+cd)**n_du-1)
        c=(CUSTO_ACAO if L.ep!=epant[t] else 0)+(CUSTO_ACAO if L.motivo.startswith(("saida","liquidacao")) else 0)
        Wat[t]*=1+L.r_acao-c
        dant[t]=L.d_sai; epant[t]=L.ep
    for t in Wt:
        f=(1+cd)**int(max((FIM-dant[t]).days,0)*252/365); Wt[t]*=f; Wat[t]*=f
    return (np.mean(list(Wt.values()))**(1/ANOS)-1)*100,(np.mean(list(Wat.values()))**(1/ANOS)-1)*100

for grupo,nome in [(None,"50 ativos"),(["PETR4","VALE3","BOVA11"],"3 liquidos")]:
    P=P0 if grupo is None else P0[P0.ticker.isin(grupo)]
    print(f"\n{'='*70}\n{nome} -- SENSIBILIDADE AO CDI\n{'='*70}")
    print(f"{'CDI':>5} | {'call mid':>9} {'call p25':>9} {'call med':>9} | {'acao':>7} | {'dif p25':>8} {'dif med':>8}")
    for cdi in [0,5,10,14]:
        cm,a=cart(P,lambda t:0.0,cdi)
        cp,_=cart(P,lambda t:G.loc[t,"p25"]/100,cdi)
        ce,_=cart(P,lambda t:G.loc[t,"mediana"]/100,cdi)
        print(f"{cdi:>4}% | {cm:>8.2f}% {cp:>8.2f}% {ce:>8.2f}% | {a:>6.2f}% | {cp-a:>+7.2f} {ce-a:>+7.2f}")
    # decomposicao: quanto do retorno da call e so CDI
    cm0,a0=cart(P,lambda t:0.0,0); cm10,a10=cart(P,lambda t:0.0,10)
    cp0,_=cart(P,lambda t:G.loc[t,"p25"]/100,0); cp10,_=cart(P,lambda t:G.loc[t,"p25"]/100,10)
    print(f"\ncontribuicao do CDI (10% vs 0%):")
    print(f"  call a mid : {cm10-cm0:+.2f} pp de {cm10:.2f}%  -> {(cm10-cm0)/cm10*100:.0f}% do retorno")
    print(f"  call no p25: {cp10-cp0:+.2f} pp de {cp10:.2f}%  -> {(cp10-cp0)/cp10*100:.0f}% do retorno" if cp10>0 else f"  call no p25: {cp10-cp0:+.2f} pp")
    print(f"  acao       : {a10-a0:+.2f} pp de {a10:.2f}%  -> {(a10-a0)/a10*100:.0f}% do retorno")
    print(f"  fracao mediana do capital em CDI durante a perna: call {(1-P.w.median())*100:.0f}%  acao 0%")
