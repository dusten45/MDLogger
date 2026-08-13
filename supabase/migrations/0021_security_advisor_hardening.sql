-- 0021_security_advisor_hardening.sql
-- 보안 어드바이저(docs/security-report.md §8) 경고 정리용 forward-fix.
--
-- 대상:
--  1. `public.rls_auto_enable()`이 event trigger 함수임에도 기본 PUBLIC EXECUTE
--     grant로 anon/authenticated가 RPC로 실행 가능해 보이는 경고(WARN) 제거.
--  2. RLS는 활성인데 정책이 없는 6개 테이블에 "의도가 명시된" 최소 권한 정책을
--     추가해 `rls_enabled_no_policy`(INFO)를 해소하고 서버 전용 접근 모델을 문서화.
--
-- 보안 판정(코드 보안 모델 유지):
--  - `rls_auto_enable()`은 `ensure_rls` event trigger다. event trigger는 DDL
--    발생 시 권한 검사 없이 자동 발화하므로 EXECUTE 명시 회수가 기능을 깨지 않는다.
--  - 아래 6개 테이블(`analytics.*` 4개, `public.game_change_cursors`,
--    `public.guest_rate_events`)은 전부 SECURITY DEFINER 함수(소유자 실행)와
--    service_role만 접근한다. service_role은 `BYPASSRLS`라 RLS를 우회하므로,
--    service_role 전용 정책을 추가해도 실제 접근 권한은 변하지 않는다.
--  - anon/authenticated는 여전히 아무 정책의 수혜자가 아니므로 기본 거부(42501)가
--    유지된다. 기존 `tests/database/08_hardening` H-1 단언을 깨지 않는다.
-- ============================================================================

-- 1) event trigger 함수의 직접 RPC 실행 표면 제거
-- `rls_auto_enable()`/`ensure_rls` event trigger는 Supabase hosted 플랫폼이
-- 만드는 bootstrap 함수다. 로컬 `supabase db reset`에는 존재하지 않을 수 있으므로
-- 존재할 때만 revoke한다(guarded). host에만 있고 로컬에 없으면 그대로 스킵된다.
do $$
begin
    if to_regprocedure('public.rls_auto_enable()') is not null then
        revoke execute on function public.rls_auto_enable()
            from public, anon, authenticated;
    end if;
end
$$;

-- ============================================================================
-- 2) RLS-활성-무정책 테이블에 서버 전용 정책 명시
--    (client deny-by-default 보존, linter `rls_enabled_no_policy` 해소)
-- ============================================================================

-- analytics.contributor_salt: pseudonymization salt(서버 전용).
create policy contributor_salt_service_role
    on analytics.contributor_salt
    for all
    to service_role
    using (true)
    with check (true);

-- analytics.duel_observations: 분석 observation(서버 전용).
create policy duel_observations_service_role
    on analytics.duel_observations
    for all
    to service_role
    using (true)
    with check (true);

-- analytics.ingestion_batches: 게스트 ingest 진단 메타데이터(서버 전용).
create policy ingestion_batches_service_role
    on analytics.ingestion_batches
    for all
    to service_role
    using (true)
    with check (true);

-- analytics.rejected_observations: 게스트 ingest 거부 진단(서버 전용).
create policy rejected_observations_service_role
    on analytics.rejected_observations
    for all
    to service_role
    using (true)
    with check (true);

-- public.game_change_cursors: 사용자별 change-version clock(동기화 함수 전용).
create policy game_change_cursors_service_role
    on public.game_change_cursors
    for all
    to service_role
    using (true)
    with check (true);

-- public.guest_rate_events: guest ingest rate limit 카운터(service_role 전용).
create policy guest_rate_events_service_role
    on public.guest_rate_events
    for all
    to service_role
    using (true)
    with check (true);
