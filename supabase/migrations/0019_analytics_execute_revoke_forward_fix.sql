-- 0019_analytics_execute_revoke_forward_fix.sql
-- P2-9 forward-fix — analytics 함수의 EXECUTE를 anon/authenticated에서 명시 회수한다.
--
-- 0005/0007/0008/0011의 analytics 함수 회수는 `revoke ... from public`만 수행해,
-- Supabase 기본값(ALTER DEFAULT PRIVILEGES ... TO anon, authenticated,
-- service_role)으로 부여된 명시적 EXECUTE 권한을 제거하지 못했다. 0011(B2)이 세운
-- "anon/authenticated 명시 회수" 규칙에 맞춰 각 analytics 함수를 명시적으로 회수한다.
-- (분석 observation은 service_role 전용 Edge/public wrapper 경로로만 쓰여야 한다.)
revoke all on function analytics.pseudonym_for(text) from anon, authenticated;
revoke all on function analytics.project_registered_game() from anon, authenticated;
revoke all on function analytics.project_registered_game_timezone()
    from anon, authenticated;
revoke all on function analytics.ingest_guest_batch(uuid, uuid, text, integer, jsonb)
    from anon, authenticated;
