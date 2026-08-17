-- 0025_user_settings.sql
-- 계획 2: 취향 설정 동기화 (P10, spec §4.2).
--
-- 설정 기본값은 기기 로컬이며, 별도 "설정 동기화"(수동 업로드/다운로드)는
-- 취향 설정(PREFERENCE_KEYS)만 대상으로 한다. 기기 특성 설정(DEVICE_KEYS)은
-- 어떤 경로로도 저장하지 않는다(서버 하드 차단).
--
-- - user_settings: 사용자당 1행, preferences(jsonb)만 저장.
-- - RLS: 사용자는 자기 행만 SELECT/INSERT/UPDATE. 삭제는 계정 삭제 시
--   auth.users on delete cascade로 함께 제거된다.
-- - upsert_user_settings RPC: preferences 키가 allowlist에만 속하는지 검증하고
--   DEVICE_KEYS/미지 키를 거부한다. auth.uid()를 user_id로 사용.

create table public.user_settings (
    user_id uuid primary key references auth.users(id) on delete cascade,
    preferences jsonb not null,
    updated_at timestamptz not null default now()
);

comment on table public.user_settings is
    '취향 설정 동기화(계획 2, P10). 기기 특성 설정은 저장하지 않는다.';

alter table public.user_settings enable row level security;

revoke all on table public.user_settings from anon, authenticated;
grant select, insert, update on table public.user_settings to authenticated;

create policy user_settings_select_own
    on public.user_settings
    for select
    to authenticated
    using (user_id = auth.uid());

create policy user_settings_insert_own
    on public.user_settings
    for insert
    to authenticated
    with check (user_id = auth.uid());

create policy user_settings_update_own
    on public.user_settings
    for update
    to authenticated
    using (user_id = auth.uid());

-- 취향 설정 upsert RPC (spec §4.2).
-- preferences의 키가 PREFERENCE_KEYS allowlist에만 속하는지 검증한다.
-- DEVICE_KEYS(font_scale/low_spec_mode/reduce_motion)와 미지 키는 거부한다.
create or replace function public.upsert_user_settings(preferences jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    allowed_keys constant text[] := array[
        'theme_mode', 'accent_color', 'memo_enabled', 'default_mode'
    ];
    disallowed text;
    uid uuid;
begin
    if preferences is null or jsonb_typeof(preferences) <> 'object' then
        raise exception 'preferences must be a JSON object'
            using errcode = '22023';
    end if;

    select key into disallowed
    from jsonb_object_keys(preferences) as t(key)
    where key <> all (allowed_keys)
    limit 1;
    if disallowed is not null then
        raise exception 'disallowed preference key: %', disallowed
            using errcode = '22023';
    end if;

    uid := auth.uid();
    if uid is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;

    insert into public.user_settings (user_id, preferences, updated_at)
    values (uid, preferences, now())
    on conflict (user_id) do update set
        preferences = excluded.preferences,
        updated_at = now();

    return preferences;
end;
$$;

revoke all on function public.upsert_user_settings(jsonb) from public, anon;
grant execute on function public.upsert_user_settings(jsonb) to authenticated;
