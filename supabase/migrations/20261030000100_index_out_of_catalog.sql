-- O COTAHIST traz o próprio Ibovespa no BDI de ações (IBOV11, ISIN BRIBOVINDM18, tipo IND).
-- Ele entrou no cadastro como se fosse ação, e o assistente aceitava "comprei 1 IBOV11".
-- A carga já ignora índices; aqui eles saem do cadastro. Se alguém tiver movimentação num
-- índice, ele só fica inativo, para não quebrar o histórico.

do $$
declare
  v_unused uuid[];
begin
  update market.assets set active = false where substr(provider_ids ->> 'isin', 7, 3) = 'IND';

  select coalesce(array_agg(a.id), '{}') into v_unused
    from market.assets a
   where substr(a.provider_ids ->> 'isin', 7, 3) = 'IND'
     and not exists (select 1 from ledger.movements m where m.asset_id = a.id)
     and not exists (select 1 from engine.position_snapshots s where s.asset_id = a.id);

  delete from market.prices_daily where asset_id = any(v_unused);
  delete from market.asset_aliases where asset_id = any(v_unused);
  delete from market.assets where id = any(v_unused);
end $$;
