-- 0026_score_input_mode.sql
-- 계획 2 후속: 점수 입력 방식(score_input_mode)을 취향 설정 allowlist에 추가.
--
-- 기존 0025_user_settings.sql의 upsert_user_settings RPC allowlist에
-- score_input_mode 키를 추가한다. 기기 특성(DEVICE_KEYS)과 미지 키는 여전히 거부한다.

create or replace function public.upsert_user_settings(preferences jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    allowed_keys constant text[] := array[
        'theme_mode', 'accent_color', 'memo_enabled', 'default_mode',
        'score_input_mode'
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
