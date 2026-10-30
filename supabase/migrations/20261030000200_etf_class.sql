-- ETFs da B3 como classe própria (BOVA11, IVVB11, HASH11...). Vêm do COTAHIST (código BDI
-- 14) filtrados pela lista de fundos de índice da B3 (reference/etfs.yaml), que separa os
-- ETFs de FI-Infra e Fiagro. ETF tem desdobramento e grupamento como ação, então entra nos
-- eventos corporativos.
--
-- O valor novo do enum só pode ser usado depois do commit desta migration; aqui ele aparece
-- só no corpo da função, que não é avaliado agora.

alter type market.asset_class add value if not exists 'etf' after 'fii';

create or replace function ledger.movements_before_write() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_class market.asset_class;
  v_today date := (now() at time zone 'America/Sao_Paulo')::date;
begin
  if tg_op = 'UPDATE' then
    if new.id <> old.id or new.user_id <> old.user_id or new.origin <> old.origin
       or new.origin_ref is distinct from old.origin_ref
       or new.idempotency_key <> old.idempotency_key
       or new.created_at <> old.created_at
       or new.created_by is distinct from old.created_by then
      raise exception 'Campo imutável da movimentação foi alterado.' using errcode = 'CA002';
    end if;
    if old.voided_at is not null and new.voided_at is not null then
      raise exception 'Movimentação removida não pode ser editada.' using errcode = 'CA006';
    end if;
    new.version := old.version + 1;
    new.updated_at := now();
    new.updated_by := auth.uid();
    if new.voided_at is not null and old.voided_at is null then
      new.voided_by := coalesce(auth.uid(), new.voided_by);
    end if;
    if new.voided_at is null and old.voided_at is not null then
      new.voided_by := null;
    end if;
  else
    new.version := 1;
    new.created_at := now();
    new.updated_at := new.created_at;
    new.voided_at := null;
    new.voided_by := null;
    new.void_reason := null;
  end if;

  -- Classe vem do ativo (ou do instrumento de renda fixa), nunca do cliente.
  if new.instrument_id is not null then
    v_class := 'renda_fixa';
  else
    select a.class into v_class from market.assets a where a.id = new.asset_id;
  end if;
  new.asset_class := v_class;

  if v_class = 'renda_fixa' and new.type not in ('aporte', 'resgate', 'provento') then
    raise exception 'Renda fixa aceita só aporte, resgate e provento.' using errcode = 'CA004';
  end if;
  if v_class <> 'renda_fixa' and new.type in ('aporte', 'resgate') then
    raise exception 'Aporte e resgate são só para renda fixa.' using errcode = 'CA004';
  end if;
  if new.type in ('desdobramento', 'grupamento', 'bonificacao') and v_class not in ('acao', 'fii', 'etf') then
    raise exception 'Eventos corporativos são só para ações, FIIs e ETFs.' using errcode = 'CA004';
  end if;

  -- Só provento pode ter data futura (agenda de pagamentos já anunciados).
  if new.type <> 'provento' and new.trade_date > v_today then
    raise exception 'Data da movimentação no futuro.' using errcode = 'CA005';
  end if;

  return new;
end
$$;

