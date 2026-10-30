"""Carga do cadastro da B3: no BDI de fundos, só entra o que a lista da B3 diz que é ETF."""

import zipfile

import pytest

from cauri_ingest_market import sync_b3_assets
from cauri_storage import service_transaction

pytestmark = pytest.mark.db

# Linhas reais do COTAHIST_A2026 com o ticker trocado (TST*, para não mexer no cadastro real).
ETF = (
    "012026033014TSTE11      010ISHARES BOVACI           R$  "
    "000000001799100000000181000000000017845"
    "000000001797300000000179000000000017900000000001792730967000000000003134093000000056329796285"
    "000000000000009999123100000010000000000000BRBOVACTF003118"
)
FI_INFRA = (
    "012026033014TSTI11      010KINEA INFRAFCI           R$  "
    "000000001234000000000123990000000012215"
    "000000001227400000000122190000000012219000000001225406876000000000000042482000000000521434421"
    "000000000000009999123100000010000000000000BRKDIFCTF003165"
)


def test_etf_entra_com_a_classe_propria_e_fi_infra_fica_de_fora(tmp_path, ingest_pool):
    path = tmp_path / "COTAHIST_A2026.ZIP"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("COTAHIST_A2026.TXT", "\r\n".join([ETF, FI_INFRA]).encode("latin-1"))
    with service_transaction(ingest_pool) as conn:
        report = sync_b3_assets(conn, path, etf_roots={"tste"})
        rows = conn.execute(
            "select ticker, class::text as class, issuer_code from market.assets"
            " where ticker in ('TSTE11', 'TSTI11')"
        ).fetchall()
    assert report.assets == 1
    assert [(r["ticker"], r["class"], r["issuer_code"]) for r in rows] == [
        ("TSTE11", "etf", "TSTE")
    ]
