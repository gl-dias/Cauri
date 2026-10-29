-- Saldo inicial: posição que já existia antes do histórico importado (USDT depositado de
-- fora, ações compradas antes do primeiro export). É uma compra marcada: a quantidade e o
-- custo médio são os que o usuário informou. Para a rentabilidade, o engine conta a entrada
-- pelo valor de mercado do dia, para um custo antigo não virar "lucro" no dia em que entra.
alter table ledger.movements
  add column opening_balance boolean not null default false,
  add constraint movements_opening_balance check (
    not opening_balance or (type = 'compra' and asset_id is not null)
  );

create or replace view marts.movements with (security_invoker = true) as
select
  m.id,
  m.trade_date,
  m.type,
  m.income_kind,
  m.asset_class,
  m.asset_id,
  m.instrument_id,
  coalesce(a.ticker, i.label) as asset_label,
  coalesce(a.name, i.issuer_name) as asset_name,
  m.quantity,
  m.unit_price,
  m.fees,
  m.amount,
  m.factor,
  i.kind as fi_kind,
  i.rate_pct as fi_rate_pct,
  i.maturity_date as fi_maturity_date,
  m.broker_id,
  b.name as broker_name,
  m.origin,
  m.origin_label,
  m.notes,
  m.version,
  m.created_at,
  m.updated_at,
  m.voided_at,
  m.void_reason,
  m.orig_currency,
  m.orig_value,
  m.fx_rate,
  m.fx_date,
  m.fx_source,
  m.fee_asset,
  m.fee_quantity,
  m.opening_balance
from ledger.movements m
left join market.assets a on a.id = m.asset_id
left join ledger.fi_instruments i on i.id = m.instrument_id
left join market.brokers b on b.id = m.broker_id;

-- Sugestões de saldo inicial calculadas na pré-visualização (moeda, data, quantidade, custo
-- sugerido e o depósito que explica o saldo, quando há).
alter table imports.batches add column suggestions jsonb not null default '[]';

-- Depósito ou saque lido do arquivo (moeda, quantidade, dia): não mexe na posição, mas
-- explica um saldo que falta.
alter table imports.rows add column transfer jsonb;
