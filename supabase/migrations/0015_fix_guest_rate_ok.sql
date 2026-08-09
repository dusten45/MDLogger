-- 0015_fix_guest_rate_ok.sql
-- 하드닝 H5 forward-fix — `0014_guest_abuse.sql`의 `guest_rate_ok` 파라미터/
-- 컬럼 이름 충돌(실제 버그) 수정.
--
-- 원인: `guest_rate_ok(bucket_key text, ...)`의 파라미터 이름 `bucket_key`가 내부에서
-- 쿼리하는 `public.guest_rate_events.bucket_key` 컬럼과 같은 이름이라, 본문
-- `where bucket_key = guest_rate_ok.bucket_key`에서 "column reference bucket_key is
-- ambiguous" 오류가 발생해 함수가 생성되지 못했다. 그 결과 guest ingest의 rate limit
-- (결정 D-4: 1분 창 최대 10회)이 실제로 동작하지 않고, 정상 요청조차 500
-- (`rate_check_failed`)을 반환한다(final_bugs 원인 1).
--
-- PostgreSQL은 `CREATE OR REPLACE`로 기존 함수의 *입력 파라미터 이름*을 바꾸지
-- 못한다(SQLSTATE 42P13). forward-fix 정책(README)에 따라 기존 0014의 정의는
-- 그대로 두되, 여기서는 `DROP FUNCTION` 후 파라미터 이름을 컬럼과 충돌하지 않는
-- `p_bucket_key`로 재정의한다. 시그니처는 (text, integer, integer)로 변하지 않아
-- 호출자(`guest_rate_check`, guest-ingest Edge)와 0014의 의도는 그대로 유지되며,
-- 재생성하므로 권한도 다시 부여한다.

drop function if exists public.guest_rate_ok(text, integer, integer);

create or replace function public.guest_rate_ok(
    p_bucket_key text,
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

    -- 파라미터(`p_bucket_key`)와 테이블 컬럼(`guest_rate_events.bucket_key`)을 모두
    -- 한정해 모호함을 제거한다.
    select count(*) into current_count
    from public.guest_rate_events
    where guest_rate_events.bucket_key = guest_rate_ok.p_bucket_key
      and requested_at > now() - make_interval(mins => window_minutes);

    if current_count >= max_requests then
        select min(requested_at) into oldest_requested
        from public.guest_rate_events
        where guest_rate_events.bucket_key = guest_rate_ok.p_bucket_key
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
    values (guest_rate_ok.p_bucket_key);
    return jsonb_build_object('allowed', true);
end;
$$;

-- 0014와 동일하게 권한을 재부여한다(service_role 전용, 나머지 차단).
revoke all on function public.guest_rate_ok(text, integer, integer)
    from public, anon, authenticated;
grant execute on function public.guest_rate_ok(text, integer, integer)
    to service_role;
