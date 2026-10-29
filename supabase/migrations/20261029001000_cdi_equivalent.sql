-- Linha "CDI" do gráfico de evolução: quanto valeria o mesmo dinheiro, com as mesmas
-- entradas e saídas, se tivesse rendido 100% do CDI. Calculada pelo engine (Decimal).

alter table engine.portfolio_snapshots add column cdi_equivalent numeric(20, 2);

create or replace view marts.portfolio_daily with (security_invoker = true) as
select
  s.user_id,
  s.snap_date,
  s.market_value,
  s.cost_basis,
  s.net_flows,
  s.income,
  s.quota_value,
  s.cdi_index,
  s.ipca_index,
  s.stale_count,
  s.cdi_equivalent
from engine.portfolio_snapshots s;
