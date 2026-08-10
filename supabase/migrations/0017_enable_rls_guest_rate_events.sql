-- 0017_enable_rls_guest_rate_events.sql
-- P0-3 forward-fix — public.guest_rate_events에 RLS를 활성화한다(H5 재수정).
--
-- 0014에서 guest_rate_events를 만들 때 RLS를 켜지 않아 `revoke all ... from
-- anon, authenticated`에만 의존했다. 이는 0011(H-1)이 세운 "public 테이블 기본
-- 거부" 불변식(F4·§8.1)을 H5에서 다시 깨뜨리고 Supabase
-- `rls_disabled_in_public` 린트 대상이 된다.
--
-- 여기서 RLS만 켜고 별도 정책을 두지 않는다. `guest_rate_ok`/`guest_rate_check`
-- 같은 security definer 함수는 테이블 소유자로 실행되므로 그대로 동작하고,
-- 클라이언트(anon/authenticated)는 0014의 revoke와 정책 부재로 계속 접근 불가다.

alter table public.guest_rate_events enable row level security;
