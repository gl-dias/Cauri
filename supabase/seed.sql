-- Só para o ambiente local (supabase db reset). Nunca roda em produção.
-- Senhas dos roles de serviço no banco local; em produção elas são definidas à mão.
alter role cauri_api with password 'cauri_api_local';
alter role cauri_ingest with password 'cauri_ingest_local';
