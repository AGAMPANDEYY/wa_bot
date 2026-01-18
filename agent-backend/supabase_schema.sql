create table if not exists public.reminders (
  id bigserial primary key,
  user_id text not null,
  title text not null,
  description text default '',
  due_at_epoch bigint not null,
  status text default 'active',
  category text,
  created_at bigint default extract(epoch from now()),
  mem0_memory_id text,
  updated_at bigint default extract(epoch from now()),
  last_notified_at bigint,
  reschedule_count integer default 0,
  last_rescheduled_at bigint
);

create table if not exists public.preferences (
  user_id text not null,
  key text not null,
  value text not null,
  mem0_memory_id text,
  updated_at bigint default extract(epoch from now()),
  primary key (user_id, key)
);

create table if not exists public.audit_logs (
  id bigserial primary key,
  user_id text,
  action text not null,
  details text,
  timestamp bigint default extract(epoch from now())
);

create table if not exists public.conversation_messages (
  id bigserial primary key,
  user_id text not null,
  role text not null,
  content text not null,
  created_at bigint default extract(epoch from now())
);

create table if not exists public.behavior_stats (
  user_id text primary key,
  create_count integer default 0,
  update_count integer default 0,
  snooze_count integer default 0,
  snooze_minutes_total integer default 0,
  done_count integer default 0,
  complete_minutes_total integer default 0,
  last_event_at bigint default extract(epoch from now())
);

create table if not exists public.mem0_cache (
  user_id text primary key,
  payload text not null,
  updated_at bigint default extract(epoch from now())
);

create index if not exists idx_reminders_user on public.reminders (user_id);
create index if not exists idx_reminders_status on public.reminders (status);
create index if not exists idx_reminders_due on public.reminders (due_at_epoch);
create index if not exists idx_audit_timestamp on public.audit_logs (timestamp);
create index if not exists idx_convo_user on public.conversation_messages (user_id);
create index if not exists idx_convo_created on public.conversation_messages (created_at);
create index if not exists idx_mem0_cache_updated on public.mem0_cache (updated_at);
