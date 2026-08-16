-- R11: 계정 운영 기능 — export_account_data, revoke device/all, prune diagnostics.
-- 검토 게이트: 로컬/분석 데이터 분리, 분석 observation에 영향 없음.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(21);

insert into auth.users (id, email) values
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local'),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'user-b@test.local');

-- 게스트 분석 데이터 baseline: 정리 정책이 분석 observation(duel_observations)
-- 에 영향을 주지 않는다는 검토 게이트 R11-3을 확인한다.
insert into analytics.duel_observations (
    source_game_id, played_at_local, result, turn_order, source_kind, payload_version
) values (
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc', '2026-08-07T10:00:00', 'win', 'first',
    'guest', 1
);

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

-- 프로필과 장치, 게임을 준비한다.
select lives_ok(
    $$ insert into public.profiles (id, display_name)
       values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'Alice') $$,
    '테스트 프로필을 만든다'
);

select public.register_or_touch_device(1, 2, '77777777-7777-4777-8777-777777777777', 'PC A', '0.2.0'
);

select public.apply_game_changes(1, 2,
    '[{"op":"create","id":"11111111-1111-4111-8111-111111111111",
       "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                  "turn_order":"first","standing_kind":"event_points","play_context_id":"dc_cup_2026_08","note":"비밀 메모"}}]'::jsonb
);

-- export_account_data: 개인 데이터만 반환하고 분석 데이터는 제외.
select is(
    (public.export_account_data() ->> 'profile') is not null,
    true,
    '내보내기에 profile이 포함된다'
);

select is(
    jsonb_array_length(public.export_account_data() -> 'games'),
    1,
    '내보내기에 개인 게임이 포함된다'
);

select is(
    (public.export_account_data() -> 'games' -> 0 ->> 'note'),
    '비밀 메모',
    '개인 게임의 note는 내보내기에 포함된다'
);

select is(
    jsonb_array_length(public.export_account_data() -> 'devices'),
    1,
    '내보내기에 장치 정보가 포함된다'
);

select is(
    (public.export_account_data() ? 'duel_observations'),
    false,
    '분석 데이터는 내보내기에 없다'
);

-- unauthenticated: export는 거부.
set local role anon;
set local request.jwt.claims to
    '{"sub":null,"role":"anon"}';
select throws_ok(
    $$ select public.export_account_data() $$,
    '28000',
    'authentication required',
    '비인증 export는 거부된다'
);

-- 장치 해제: 특정 장치와 모든 장치.
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select is(
    (public.list_user_devices() #>> '{0,display_name}'),
    'PC A',
    '본인 장치 목록을 조회한다'
);

select is(
    (public.revoke_device('77777777-7777-4777-8777-777777777777') ->> 'display_name'),
    'PC A',
    '특정 장치를 해제한다'
);

select results_eq(
    $$ select count(*)::int from public.devices $$,
    $$ values (0) $$,
    '해제 후 장치가 없다'
);

select lives_ok(
    $$ select public.register_or_touch_device(1, 2, '88888888-8888-4888-8888-888888888888', 'PC B', '0.2.0') $$,
    '두 번째 장치를 다시 등록한다'
);

select is(
    (public.revoke_all_devices() ->> 'revoked_devices')::int,
    1,
    '모든 장치를 해제한다'
);

select throws_ok(
    $$ select public.revoke_device('99999999-9999-4999-8999-999999999999') $$,
    '22023',
    'device is not registered',
    '등록되지 않은 장치 해제는 거부된다'
);

-- 다른 사용자로 전환해도 A의 데이터에 접근할 수 없다.
set local request.jwt.claims to
    '{"sub":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","role":"authenticated"}';

select is(
    jsonb_array_length(public.export_account_data() -> 'games'),
    0,
    '다른 사용자 export에는 A의 게임이 없다'
);

select results_eq(
    $$ select count(*)::int from public.devices $$,
    $$ values (0) $$,
    '다른 사용자는 A의 장치를 볼 수 없다'
);

-- prune_guest_ingest_diagnostics: guest ingest 진단 메타데이터만 정리한다.
-- 진단 행을 직접 넣은 뒤 분석 observation과 격리되어 있는지 확인한다.
set local role postgres;
insert into analytics.ingestion_batches (
    batch_id, source_kind, installation_key, received_at
) values (
    'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', 'guest',
    'pseudonym-x', now() - interval '120 days'
);
insert into analytics.ingestion_batches (
    batch_id, source_kind, installation_key, received_at
) values (
    '11111111-2222-4333-8444-555555555555', 'guest',
    'pseudonym-y', now() - interval '10 days'
);
insert into analytics.rejected_observations (
    batch_id, source_game_id, reason, received_at
) values (
    'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    'abcdabcd-abcd-4abc-8abc-abcdabcdabcd',
    'invalid_value', now() - interval '120 days'
);

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select throws_ok(
    $$ select public.prune_guest_ingest_diagnostics(90) $$,
    '42501',
    NULL,
    'authenticated는 진단 정리를 직접 실행할 수 없다'
);

-- 양성 경로는 실제 호출자(service_role) 자격으로 실행해 권한 충실도를 검증한다.
-- fixture 삽입과 SELECT 검증은 postgres(소유자)로, 실제 prune 함수 호출만
-- service_role로 수행한다. service_role의 커스텀(analytics) 스키마 직접 INSERT
-- 권한에 의존하지 않도록 분리한다.
set local role service_role;
select is(
    (public.prune_guest_ingest_diagnostics(90) ->> 'pruned_batches')::int,
    1,
    '90일보다 오래된 진단 batch만 정리된다'
);

set local role postgres;
select results_eq(
    $$ select count(*)::int from analytics.ingestion_batches $$,
    $$ values (1) $$,
    '최근 진단 batch는 보존된다'
);

-- 위 첫 prune(90) 호출에서 오래된 rejected 행도 함께 지워졌으므로, 새 오래된 거부
-- 기록을 넣어 rejected 정리를 다시 검증한다(이중 호출 순서로 인한 원인 2 후속 보정).
insert into analytics.rejected_observations (
    batch_id, source_game_id, reason, received_at
) values (
    'ffffffff-ffff-4fff-8fff-ffffffffffff',
    'ffffffff-ffff-4fff-8fff-ffffffffffff',
    'invalid_value', now() - interval '120 days'
);
set local role service_role;
select is(
    (public.prune_guest_ingest_diagnostics(90) ->> 'pruned_rejected')::int,
    1,
    '오래된 거부 기록도 정리된다'
);

set local role postgres;
select is(
    (select count(*)::int from analytics.duel_observations
     where source_game_id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'),
    1,
    '진단 정리가 분석 observation에 영향을 주지 않는다(검토 게이트 R11-3)'
);

select throws_ok(
    $$ select public.prune_guest_ingest_diagnostics(-1) $$,
    '22023',
    'older_than_days must be non-negative',
    '음수 보존 기간은 거부된다'
);

select * from finish();
rollback;
