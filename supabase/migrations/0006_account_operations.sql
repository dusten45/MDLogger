-- 0006_account_operations.sql
-- 계정 삭제용 서버 함수 인터페이스(로드맵 8.4, 결정 4).
--
-- 계정 삭제 시:
-- - 개인용 profiles, games(note 포함), devices 행은 삭제한다.
-- - 계정과 분리된 분석용 duel_observations는 보존한다. 계정 삭제는
--   듀얼 기록 철회가 아니므로 withdrawn_at을 설정하지 않는다(로드맵 9.3).
-- - auth.users 행 삭제와 모든 세션/refresh token 폐기는 service_role
--   자격의 계정 삭제 Edge Function이 Auth Admin API로 수행한다(단계 11).
--   이 함수는 그 Edge Function이 호출하는 데이터 삭제 인터페이스다.

create or replace function public.delete_account_data(target_user uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    deleted_games integer;
    deleted_devices integer;
    deleted_profiles integer;
begin
    if target_user is null then
        raise exception 'target_user is required' using errcode = '22023';
    end if;

    delete from public.games where user_id = target_user;
    get diagnostics deleted_games = row_count;

    delete from public.devices where user_id = target_user;
    get diagnostics deleted_devices = row_count;

    delete from public.profiles where id = target_user;
    get diagnostics deleted_profiles = row_count;

    return jsonb_build_object(
        'user_id', target_user,
        'deleted_games', deleted_games,
        'deleted_devices', deleted_devices,
        'deleted_profiles', deleted_profiles
    );
end;
$$;

comment on function public.delete_account_data(uuid) is
    '개인용 계정 데이터만 삭제한다. auth 사용자 삭제와 세션 폐기는 '
    'service_role Edge Function이 Auth Admin API로 수행한다.';

-- 클라이언트는 직접 실행할 수 없다. 계정 삭제 Edge Function(service_role)
-- 전용이다. 데스크톱 클라이언트에 관리자 자격 증명을 포함하지 않는다.
revoke all on function public.delete_account_data(uuid)
    from public, anon, authenticated;
grant execute on function public.delete_account_data(uuid) to service_role;
