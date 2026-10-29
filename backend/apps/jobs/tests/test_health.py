"""Regra do monitoramento: issue quando falta fechamento em 2 pregões seguidos."""

from datetime import date

from cauri_jobs.health import evaluate


def test_um_pregao_sem_fechamento_ainda_nao_alerta():
    # Último fechamento na quarta 28/10/2026; quinta 29 ainda sem: 1 pregão.
    result = evaluate(date(2026, 10, 28), True, until=date(2026, 10, 29), business_days=2)
    assert result.ok


def test_dois_pregoes_sem_fechamento_alerta_com_as_datas():
    result = evaluate(date(2026, 10, 27), True, until=date(2026, 10, 29), business_days=2)
    assert not result.ok
    assert "28/10/2026, 29/10/2026" in result.message


def test_fim_de_semana_nao_conta_como_pregao():
    # Sexta 23/10 fechou; segunda 26 ainda sem: só 1 pregão faltando.
    assert evaluate(date(2026, 10, 23), True, until=date(2026, 10, 26), business_days=2).ok


def test_banco_sem_fechamento_e_carteira_sem_acoes():
    assert not evaluate(None, True, until=date(2026, 10, 29), business_days=2).ok
    assert evaluate(None, False, until=date(2026, 10, 29), business_days=2).ok
