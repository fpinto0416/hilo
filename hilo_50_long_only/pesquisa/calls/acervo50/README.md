# Análise de call sobre o acervo — 50 ativos (§12.8)

Código que produziu o resultado definitivo do `ACHADOS.md` §12.8.
Substitui os scripts da pasta acima, que rodavam sobre `vol_implicita.db`
com apenas 6 ativos.

**Fonte:** `github.com/fpinto0416/acervo-opcoes-b3` (clone em
`/app/acervo_opcoes_b3`). Precisa dele preenchido.

## Ordem de execução

```bash
python3 cobertura.py    # mapeia ISIN dos 81 ativos, escolhe os 50 com
                        # call em >=50% dos pregões -> mapa.json
python3 extrair.py      # varre o acervo uma vez -> calls.parquet, spot.parquet
python3 rodar.py        # simula as pernas -> pernas.parquet
python3 resultado.py    # teste pareado + carteira (spread uniforme)
python3 spreads.py      # mede o spread real por ativo -> spreads.csv
python3 final50.py      # resultado com o spread medido de cada ativo
python3 completo.py     # baseline: long-only completo, sem restrição de opção
```

Os `.parquet` intermediários **não são versionados** (~33 MB, regeneráveis).

## Decisões que já custaram erro — não desfazer

- **Preço da opção é `ultimo`, não `medio`.** O sinal do HiLo só é
  conhecido no fechamento; comprar pelo VWAP do dia é look-ahead e em dia
  de alta barateia a call de graça. Valia **2,7 p.p. a.a.**
- **O sinal precisa ser defasado** (`inv.shift(1)`) contra o retorno.
  Sem isso o baseline em ação dava 54% a.a. com Sharpe 3,66.
- **ATM por `|ln(K/spot)|` com tolerância**, nunca "strike mais próximo":
  entre os que negociaram, o mais próximo pode estar longe do dinheiro.
- **Delta sai de Black-Scholes com a IV extraída do próprio preço** — o
  acervo não traz delta pronto, ao contrário do `vol_implicita.db`.
- **A ação paga 30 bps por episódio, não por perna** — ela é comprada uma
  vez e atravessa as rolagens.
- **O baseline que decide é o long-only COMPLETO** (`completo.py`), não a
  ação restrita aos episódios com call. É contra ele que a call perde.
