# -*- coding: utf-8 -*-
"""
Listas e filtros iniciais do Triadex (B3/US).
Podemos expandir/parametrizar isso depois lendo de JSON/YAML ou do próprio backend.
"""

WATCHLISTS = {
    # Núcleo B3 (representativo para a primeira tela)
    "br_bluechips": {
        "label": "B3 • Blue Chips",
        "symbols": [
            "PETR4.SA", "VALE3.SA", "ITUB4.SA", "B3SA3.SA", "ABEV3.SA",
            "BBAS3.SA", "BBDC4.SA", "WEGE3.SA", "ELET3.SA", "ELET6.SA",
            "PRIO3.SA", "GGBR4.SA", "SUZB3.SA", "JBSS3.SA"
        ],
        "note": "Conjunto enxuto de alta liquidez para exemplo inicial."
    },

    # Setores simplificados (exemplo inicial)
    "br_bancos": {
        "label": "B3 • Bancos",
        "symbols": ["ITUB4.SA", "BBDC4.SA", "BBAS3.SA", "SANB11.SA", "BPAC11.SA"],
        "note": "Setor financeiro (bancos & serviços)."
    },
    "br_energia": {
        "label": "B3 • Energia/Elétricas",
        "symbols": ["ELET3.SA", "ELET6.SA", "TAEE11.SA", "ENBR3.SA", "EQTL3.SA", "CMIG4.SA"],
        "note": "Geradoras, transmissoras e distribuidoras."
    },
    "br_commodities": {
        "label": "B3 • Commodities",
        "symbols": ["VALE3.SA", "PETR4.SA", "PETR3.SA", "GGBR4.SA", "SUZB3.SA", "PRIO3.SA"],
        "note": "Mineração, petróleo & siderurgia."
    },

    # EUA
    "us_mega": {
        "label": "US • Mega Caps",
        "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META"],
        "note": "Gigantes de tecnologia (USD)."
    }
}
