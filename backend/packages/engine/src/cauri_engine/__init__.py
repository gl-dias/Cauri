"""Engine: posição, preço médio, renda fixa, rentabilidade e snapshots diários.

``cauri_engine.calc`` é o núcleo puro (testável sem banco). A camada que lê o ledger
e grava os snapshots entra com o job diário.
"""
