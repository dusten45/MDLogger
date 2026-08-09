-- 0014_guest_abuse.sql
-- 하드닝 H5/H6 — guest ingest 남용 방어(로드맵 §12.3 방어 1·4)와 Edge Function
-- 필드 allowlist를 위한 서버 측 초석.
--
-- - `public.guest_rate_events`: installation pseudonym·IP 단위 슬라이딩 창
--   요청 카운터. anon/authenticated 접근 없음(service_role 전용).
-- - `public.guest_rate_ok`: 단일 키의 슬라이딩 창 rate limit.
-- - `public.guest_rate_check`: installation + IP 이중 검사 wrapper.
-- 임계값(결정 D-4 확정): installation·IP 각각 1분 창 최대 10회. 게스트 배치
-- 업로드(관찰 1~200건)는 1건당 1요청이므로 정상 사용은 방해하지 않는다. 초과 시
-- 429 + retry_after_seconds.

create table public.guest_rate_events (
    id bigint generated always as identity primary key,
    bucket_key text not null,
    requested_at timestamptz not null default now()
);

create index idx_guest_rate_events_key_time
    on public.guest_rate_events (bucket_key, requested_at);

-- 진단용으로만 남고 클라이언트 접근은 없다. 게스트는 Edge Function
-- (service_role)이 호출하는 검사 함수만 거친다.
revoke all on table public.guest_rate_events from anon, authenticated;

create or replace function public.guest_rate_ok(
    bucket_key text,
    window_minutes integer,
    max_requests integer
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    current_count integer;
    oldest_requested timestamptz;
begin
    if window_minutes is null or window_minutes < 1 then
        raise exception 'window_minutes must be positive' using errcode = '22023';
    end if;
    if max_requests is null or max_requests < 1 then
        raise exception 'max_requests must be positive' using errcode = '22023';
    end if;

    select count(*) into current_count
    from public.guest_rate_events
    where bucket_key = guest_rate_ok.bucket_key
      and requested_at > now() - make_interval(mins => window_minutes);

    if current_count >= max_requests then
        select min(requested_at) into oldest_requested
        from public.guest_rate_events
        where bucket_key = guest_rate_ok.bucket_key
          and requested_at > now() - make_interval(mins => window_minutes);
        return jsonb_build_object(
            'allowed', false,
            'retry_after_seconds', greatest(
                1,
                ceil(
                    extract(epoch from (
                        coalesce(oldest_requested, now())
                        + make_interval(mins => window_minutes) - now()
                    ))
                )::integer
            )
        );
    end if;

    insert into public.guest_rate_events (bucket_key)
    values (guest_rate_ok.bucket_key);
    return jsonb_build_object('allowed', true);
end;
$$;

revoke all on function public.guest_rate_ok(text, integer, integer)
    from public, anon, authenticated;
grant execute on function public.guest_rate_ok(text, integer, integer)
    to service_role;

-- installation pseudonym + IP 이중 검사. 둘 중 하나라도 창 허용치를 넘으면 차단.
create or replace function public.guest_rate_check(
    installation_id uuid,
    ip text,
    window_minutes integer default 1,
    max_per_window integer default 10
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    inst_key text := analytics.pseudonym_for(installation_id::text);
    ip_key text := coalesce(nullif(btrim(guest_rate_check.ip), ''), 'unknown');
    inst_result jsonb;
    ip_result jsonb;
begin
    inst_result := public.guest_rate_ok(inst_key, window_minutes, max_per_window);
    if not (inst_result ->> 'allowed')::boolean then
        return jsonb_build_object(
            'allowed', false, 'reason', 'installation',
            'retry_after_seconds',
            (inst_result ->> 'retry_after_seconds')::integer
        );
    end if;

    ip_result := public.guest_rate_ok(ip_key, window_minutes, max_per_window);
    if not (ip_result ->> 'allowed')::boolean then
        return jsonb_build_object(
            'allowed', false, 'reason', 'ip',
            'retry_after_seconds',
            (ip_result ->> 'retry_after_seconds')::integer
        );
    end if;

    return jsonb_build_object('allowed', true);
end;
$$;

revoke all on function public.guest_rate_check(uuid, text, integer, integer)
    from public, anon, authenticated;
grant execute on function public.guest_rate_check(uuid, text, integer, integer)
    to service_role;

-- 긴급 차단 해제·리셋 수단(소유자 운영).
comment on table public.guest_rate_events is
    'guest ingest rate limit 카운터. 자유롭게 삭제해도 진단에만 영향. 운영은 주기적으로 오래된 행을 정리한다.';
