-- 0016_export_account_data_anon.sql
-- 단계 11 forward-fix — 결정(B) 반영: anon('미인증')이 `export_account_data`를 실행할
-- 수 있게 되돌려, 함수 본문이 auth.uid() == null을 감지해 의미 있는 SQLSTATE
-- 28000('authentication required')을 던지게 한다(final_bugs 원인 4).
--
-- 0010은 `revoke all ... from public, anon` 후 `grant execute ... to authenticated`로
-- anon의 실행을 막아, anon 호출이 *함수에 도달하지 못하고* DB 권한 게이트에서 42501이
-- 먼저 났다. 여기서는 anon에만 EXECUTE를 명시적으로 다시 부여해 최소한의 노출만 허용하되,
-- 함수는 security definer(소유자 권한)로 실행되므로 데이터는 여전히 auth.uid()로만
-- 조회되고 비인증에는 28000이 반환된다.

grant execute on function public.export_account_data() to anon;
