-- DHL Dashboard — run once in Supabase SQL Editor (https://supabase.com/dashboard/project/_/sql)

create table if not exists vss_tokens (
  id text primary key default 'active',
  token text not null,
  pid text not null default '',
  issued_at timestamptz not null,
  base_url text,
  profile text,
  updated_at timestamptz not null default now()
);

create table if not exists dashboard_snapshots (
  key text primary key,
  payload jsonb not null,
  row_count integer not null default 0,
  updated_at timestamptz not null default now()
);

create table if not exists operation_sessions (
  id text primary key,
  trigger text not null,
  username text,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  status text not null default 'running'
);

create table if not exists operation_logs (
  id bigserial primary key,
  session_id text,
  ts timestamptz not null default now(),
  category text not null,
  step text not null,
  status text not null,
  message text not null,
  detail jsonb
);

alter table operation_logs add column if not exists session_id text;

create index if not exists operation_logs_session_idx on operation_logs (session_id, id);
create index if not exists operation_logs_ts_idx on operation_logs (ts desc);

create table if not exists dashboard_meta (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);
