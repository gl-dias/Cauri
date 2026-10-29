"""Gera as fixtures de teste e o template de importação, sempre com dados inventados.

Nada aqui vem de arquivo real: os layouts seguem os exports públicos, e nomes, CPFs e
posições são fictícios (o CPF de exemplo é inválido de propósito). Rodar de novo
sobrescreve os arquivos::

    uv run python packages/importers/tests/fixtures/build_fixtures.py
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from openpyxl import Workbook

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
TEMPLATE_DIR = ROOT / "reference" / "import-template"
PUBLIC_DIR = ROOT / "web" / "public" / "templates"  # botão "Baixar template" da tela Importar

GENERIC_HEADER = [
    "data", "tipo", "ativo", "classe", "quantidade", "preco", "fator", "taxas", "valor",
    "corretora", "pct_cdi", "vencimento", "emissor", "tipo_provento", "obs",
]  # fmt: skip

# Exemplo do template: uma linha de cada tipo, carteira inventada.
GENERIC_EXAMPLE = [
    ["10/03/2025", "compra", "PETR4", "acao", "100", "36,80", "", "4,90", "", "XP Investimentos", "", "", "", "", ""],
    ["12/03/2025", "compra", "HGLG11", "fii", "20", "158,40", "", "0", "", "BTG Pactual", "", "", "", "", ""],
    ["14/04/2025", "provento", "HGLG11", "fii", "", "", "", "", "22,00", "BTG Pactual", "", "", "", "rendimento", ""],
    ["02/05/2025", "compra", "Tesouro Selic 2029", "tesouro", "0,35", "15.120,44", "", "", "", "XP Investimentos", "", "", "", "", ""],
    ["05/05/2025", "aporte", "CDB Banco Exemplo 110% CDI", "renda_fixa", "", "", "", "", "5.000,00", "Nubank", "110", "05/05/2028", "Banco Exemplo", "", ""],
    ["20/05/2025", "compra", "BTC", "cripto", "0,0025", "560.000,00", "", "", "", "Binance", "", "", "", "", ""],
    ["02/06/2025", "venda", "PETR4", "acao", "40", "38,10", "", "4,90", "", "XP Investimentos", "", "", "", "", "venda parcial"],
    ["16/06/2025", "desdobramento", "PETR4", "acao", "", "", "2", "", "", "XP Investimentos", "", "", "", "", "1 vira 2"],
]  # fmt: skip


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


def write_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    first = True
    for title, rows in sheets.items():
        sheet = workbook.active if first else workbook.create_sheet()
        assert sheet is not None
        sheet.title = title
        for row in rows:
            sheet.append(row)
        first = False
    workbook.save(path)


def _numbers(row: list[str]) -> list[object]:
    """Versão xlsx: números e datas como células de verdade, não texto."""
    from decimal import Decimal

    out: list[object] = []
    for i, value in enumerate(row):
        column = GENERIC_HEADER[i]
        if value and column in {"data", "vencimento"}:
            d, m, y = value.split("/")
            out.append(date(int(y), int(m), int(d)))
        elif value and column in {"quantidade", "preco", "fator", "taxas", "valor", "pct_cdi"}:
            out.append(float(Decimal(value.replace(".", "").replace(",", "."))))
        else:
            out.append(value or None)
    return out


def build() -> None:
    # Template público (vai para o repo e para o botão "Baixar template").
    for folder in (TEMPLATE_DIR, PUBLIC_DIR):
        write_csv(folder / "cauri-importacao.csv", GENERIC_HEADER, GENERIC_EXAMPLE)
        write_xlsx(
            folder / "cauri-importacao.xlsx",
            {"Movimentações": [GENERIC_HEADER, *(_numbers(r) for r in GENERIC_EXAMPLE)]},
        )

    # Fixtures do template genérico, com problemas de propósito.
    write_csv(
        HERE / "generico.csv",
        GENERIC_HEADER,
        [
            *GENERIC_EXAMPLE[:3],
            ["31/02/2025", "compra", "PETR4", "acao", "1", "10", "", "", "", "XP Investimentos", "", "", "", "", ""],
            ["10/03/2025", "troca", "PETR4", "acao", "1", "10", "", "", "", "XP Investimentos", "", "", "", "", ""],
            ["11/03/2025", "compra", "PETR4", "acao", "1", "10", "", "", "", "Corretora Que Nao Existe", "", "", "", "", ""],
            ["12/03/2025", "compra", "PETR4", "acao", "1", "10", "", "", "", "XP Investimentos", "", "", "", "", "contato 123.456.789-00"],
        ],
    )  # fmt: skip
    write_xlsx(
        HERE / "generico.xlsx",
        {
            # Folha de rosto com dado pessoal antes da tabela: o leitor nunca deve carregar.
            "Resumo": [["Investidor", "Fulano de Tal"], ["CPF", "123.456.789-00"]],
            "Movimentações": [
                ["Relatório de movimentações"],
                ["Nome", "Fulano de Tal", "CPF", "123.456.789-00"],
                [],
                [*GENERIC_HEADER, "cpf"],
                *([*_numbers(r), "123.456.789-00"] for r in GENERIC_EXAMPLE),
            ],
        },
    )

    # B3, Área do Investidor. Ativos e corretoras de teste (os mesmos do conftest), para os
    # testes com banco rodarem também no CI. Acima da tabela, um bloco de identificação
    # inventado: o leitor acha o cabeçalho e nunca carrega essas células.
    identification = [["Investidor", "Fulano de Tal"], ["CPF", "123.456.789-00"], []]
    write_xlsx(
        HERE / "b3-negociacao.xlsx",
        {
            "Negociação": [
                *identification,
                [
                    "Data do Negócio",
                    "Tipo de Movimentação",
                    "Mercado",
                    "Prazo/Vencimento",
                    "Instituição",
                    "Código de Negociação",
                    "Quantidade",
                    "Preço",
                    "Valor",
                ],
                [
                    "05/01/2026",
                    "Compra",
                    "Mercado à Vista",
                    "-",
                    "CORRETORA TESTE A",
                    "TSTA3",
                    100,
                    20.0,
                    2000.0,
                ],
                [
                    "05/01/2026",
                    "Compra",
                    "Mercado Fracionário",
                    "-",
                    "CORRETORA TESTE A",
                    "TSTA3F",
                    7,
                    20.1,
                    140.7,
                ],
                [
                    "06/01/2026",
                    "Compra",
                    "Mercado à Vista",
                    "-",
                    "CORRETORA TESTE B",
                    "TSTA3",
                    50,
                    21.0,
                    1050.0,
                ],
                [
                    "07/01/2026",
                    "Compra",
                    "Mercado à Vista",
                    "-",
                    "CORRETORA TESTE A",
                    "TSTF11",
                    10,
                    100.0,
                    1000.0,
                ],
                [
                    "08/01/2026",
                    "Venda",
                    "Mercado à Vista",
                    "-",
                    "CORRETORA TESTE A",
                    "TSTA3",
                    30,
                    22.0,
                    660.0,
                ],
                [
                    "09/01/2026",
                    "Compra",
                    "Opção de Compra",
                    "16/01/2026",
                    "CORRETORA TESTE A",
                    "TSTAA220",
                    100,
                    0.5,
                    50.0,
                ],
                [
                    "12/01/2026",
                    "Compra",
                    "Mercado à Vista",
                    "-",
                    "CORRETORA TESTE B",
                    "TSTB4",
                    10,
                    15.0,
                    150.0,
                ],
                [
                    "12/01/2026",
                    "Compra",
                    "Mercado à Vista",
                    "-",
                    "CORRETORA TESTE B",
                    "TSTB4",
                    10,
                    15.0,
                    150.0,
                ],
            ]
        },
    )
    write_xlsx(
        HERE / "b3-movimentacao.xlsx",
        {
            "Movimentação": [
                *identification,
                [
                    "Entrada/Saída",
                    "Data",
                    "Movimentação",
                    "Produto",
                    "Instituição",
                    "Quantidade",
                    "Preço unitário",
                    "Valor da Operação",
                ],
                [
                    "Credito",
                    "07/01/2026",
                    "Transferência - Liquidação",
                    "TSTA3 - EMPRESA TSTA S.A.",
                    "CORRETORA TESTE A",
                    100,
                    20.0,
                    2000.0,
                ],
                [
                    "Credito",
                    "15/01/2026",
                    "Rendimento",
                    "TSTF11 - FUNDO TESTE FII",
                    "CORRETORA TESTE A",
                    10,
                    0.85,
                    8.5,
                ],
                [
                    "Credito",
                    "20/01/2026",
                    "Dividendo",
                    "TSTA3 - EMPRESA TSTA S.A.",
                    "CORRETORA TESTE A",
                    77,
                    0.1,
                    7.7,
                ],
                [
                    "Credito",
                    "20/01/2026",
                    "Juros Sobre Capital Próprio",
                    "TSTA3 - EMPRESA TSTA S.A.",
                    "CORRETORA TESTE B",
                    50,
                    0.068,
                    3.4,
                ],
                [
                    "Credito",
                    "02/02/2026",
                    "Desdobro",
                    "TSTA3 - EMPRESA TSTA S.A.",
                    "CORRETORA TESTE A",
                    77,
                    "-",
                    "-",
                ],
                [
                    "Credito",
                    "02/02/2026",
                    "Desdobro",
                    "TSTA3 - EMPRESA TSTA S.A.",
                    "CORRETORA TESTE B",
                    50,
                    "-",
                    "-",
                ],
                [
                    "Credito",
                    "03/02/2026",
                    "Compra / Venda",
                    "Tesouro Selic 2099",
                    "CORRETORA TESTE A",
                    0.5,
                    15000.0,
                    7500.0,
                ],
                [
                    "Credito",
                    "10/02/2026",
                    "Bonificação em Ativos",
                    "TSTF11 - FUNDO TESTE FII",
                    "CORRETORA TESTE A",
                    1,
                    95.0,
                    "-",
                ],
                [
                    "Debito",
                    "15/02/2026",
                    "Cobrança de Taxa Semestral",
                    "Tesouro Selic 2099",
                    "CORRETORA TESTE A",
                    "-",
                    "-",
                    3.1,
                ],
                [
                    "Credito",
                    "16/02/2026",
                    "Atualização",
                    "TSTF11 - FUNDO TESTE FII",
                    "CORRETORA TESTE A",
                    11,
                    "-",
                    "-",
                ],
                [
                    "Credito",
                    "17/02/2026",
                    "Transferência",
                    "TSTA3 - EMPRESA TSTA S.A.",
                    "CORRETORA TESTE B",
                    10,
                    "-",
                    "-",
                ],
                [
                    "Credito",
                    "18/02/2026",
                    "Leilão de Fração",
                    "TSTF11 - FUNDO TESTE FII",
                    "CORRETORA TESTE A",
                    "-",
                    "-",
                    12.3,
                ],
                [
                    "Credito",
                    "19/02/2026",
                    "Cisão",
                    "TSTA3 - EMPRESA TSTA S.A.",
                    "CORRETORA TESTE A",
                    5,
                    "-",
                    "-",
                ],
            ]
        },
    )


if __name__ == "__main__":
    build()
