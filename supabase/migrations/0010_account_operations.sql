-- 0010_account_operations.sql
-- 단계 11: 계정 관리와 운영 기능(로드맵 13, 단계 11).
--
-- 제공하는 계약:
-- - export_account_data: 인증 사용자 본인의 개인 데이터(profile, games, devices)
--   를 돌려준다. 분석용 duel_observations는 반환하지 않는다(로드맵 12.4).
-- - revoke_device / revoke_all_devices: 특정 장치 해제와 모든 장치 로그아웃.
-- - prune_guest_ingest_diagnostics: 오래된 guest ingest *진단* 메타데이터
--   (ingestion_batches, rejected_observations) 정리. 분석 observation
--   (duel_observations)에는 절대 접근하지 않는다(로드맵 12.4, 검토 게이트 R11-3).
--
-- 보존 정책(검토 게이트 R11-2, 로드맵 9.3): 개인용 games의 deleted_at
-- tombstone과 분석용 duel_observations의 withdrawn_at 마커는 무기한 보존한다.
-- 아래 정리 함수는 이러한 행을 건드리지 않는다.
--
-- 계정 삭제의 개인 데이터 삭제 인터페이스(delete_account_data)는 이미 0006에
-- 있다. auth 사용자·세션 폐기는 service_role 계정 삭제 Edge Function
-- (functions/account-delete)이 Auth Admin API로 수행한다(단계 11).

-- ---------------------------------------------------------------------------
-- 계정 데이터 내보내기(로드맵 12.4: 사용자가 내보낼 수 있는 데이터 범위).
-- 인증된 사용자 본인의 개인 데이터만 반환한다. 분석 데이터는 제외한다.
-- ---------------------------------------------------------------------------
create or replace function public.export_account_data()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
    profile_payload jsonb;
    game_payload jsonb;
    device_payload jsonb;
begin
    if request_user is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;

    select to_jsonb(p) - 'id'
    into profile_payload
    from public.profiles as p
    where p.id = request_user;

    select coalesce(jsonb_agg(to_jsonb(g) - 'user_id'), '[]'::jsonb)
    into game_payload
    from public.games as g
    where g.user_id = request_user;

    select coalesce(jsonb_agg(to_jsonb(d) - 'user_id'), '[]'::jsonb)
    into device_payload
    from public.devices as d
    where d.user_id = request_user;

    return jsonb_build_object(
        'user_id', request_user,
        'exported_at', now(),
        'profile', profile_payload,
        'games', game_payload,
        'devices', device_payload
    );
end;
$$;

revoke all on function public.export_account_data() from public, anon;
grant execute on function public.export_account_data() to authenticated;

-- ---------------------------------------------------------------------------
-- 장치 관리(로드맵 단계 11: 모든 장치 로그아웃과 특정 장치 해제).
-- 클라이언트는 auth.uid() 문맥으로 본인 장치만 조회/해제할 수 있다(R11-1).
-- ---------------------------------------------------------------------------
create or replace function public.list_user_devices()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
begin
    if request_user is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;

    return coalesce(
        (
            select jsonb_agg(to_jsonb(d) - 'user_id' order by d.last_seen_at desc)
            from public.devices as d
            where d.user_id = request_user
        ),
        '[]'::jsonb
    );
end;
$$;

revoke all on function public.list_user_devices() from public, anon;
grant execute on function public.list_user_devices() to authenticated;

create or replace function public.revoke_device(installation_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
    removed jsonb;
begin
    if request_user is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if installation_id is null then
        raise exception 'installation_id is required' using errcode = '22023';
    end if;

    delete from public.devices as device_row
    where device_row.user_id = request_user
      and device_row.installation_id = revoke_device.installation_id
    returning to_jsonb(device_row) - 'user_id' into removed;

    if removed is null then
        raise exception 'device is not registered' using errcode = '22023';
    end if;

    return removed;
end;
$$;

revoke all on function public.revoke_device(uuid) from public, anon;
grant execute on function public.revoke_device(uuid) to authenticated;

create or replace function public.revoke_all_devices()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
    revoked integer;
begin
    if request_user is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;

    delete from public.devices where user_id = request_user;
    get diagnostics revoked = row_count;

    return jsonb_build_object('revoked_devices', revoked);
end;
$$;

revoke all on function public.revoke_all_devices() from public, anon;
grant execute on function public.revoke_all_devices() to authenticated;

-- ---------------------------------------------------------------------------
-- guest ingest 진단 메타데이터 정리 정책(로드맵 12.4, 검토 게이트 R11-3).
--
-- ingestion_batches와 rejected_observations는 남용 탐지·진단 전용으로, 분석
-- observation(duel_observations)과 분리되어 있다. 이 정책은 *진단* 행만
-- 제거하며 duel_observations에는 절대 접근하지 않아 분석 데이터에 영향을
-- 주지 않는다. 개인 games tombstone과 분석 withdrawn_at 마커도 보존한다.
--
-- 기본 보존 기간은 90일이며 소유자가 운영 값을 조정할 수 있다(결정 17.2).
-- ---------------------------------------------------------------------------
create or replace function public.prune_guest_ingest_diagnostics(
    older_than_days integer default 90
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    cutoff timestamptz;
    pruned_batches bigint;
    pruned_rejected bigint;
begin
    if older_than_days is null or older_than_days < 0 then
        raise exception 'older_than_days must be non-negative'
            using errcode = '22023';
    end if;

    cutoff := now() - make_interval(days => older_than_days);

    delete from analytics.ingestion_batches
    where received_at < cutoff;
    get diagnostics pruned_batches = row_count;

    delete from analytics.rejected_observations
    where received_at < cutoff;
    get diagnostics pruned_rejected = row_count;

    return jsonb_build_object(
        'cutoff', cutoff,
        'pruned_batches', pruned_batches,
        'pruned_rejected', pruned_rejected
    );
end;
$$;

-- 기본 보존 기간을 명시하는 운영 값(결정 17.2). 소유자가 조정 가능하다.
comment on function public.prune_guest_ingest_diagnostics(integer) is
    'guest ingest 진단 메타데이터(ingestion_batches, rejected_observations)만 '
    '정리한다. duel_observations, games tombstone, withdrawn_at 마커는 절대 '
    '삭제하지 않는다. 기본 보존 기간 90일.';

-- 클라이언트는 직접 호출할 수 없다. 스케줄러/관리자(service_role) 전용이다.
revoke all on function public.prune_guest_ingest_diagnostics(integer)
    from public, anon, authenticated;
grant execute on function public.prune_guest_ingest_diagnostics(integer)
    to service_role;
