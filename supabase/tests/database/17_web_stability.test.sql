begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;
select no_plan();

insert into auth.users(id, email) values
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'web-a@test.local'),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'web-b@test.local');

set local role authenticated;
set local request.jwt.claims to '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select set_config('test.create', '[{"op":"create","id":"11111111-1111-4111-8111-111111111111",
    "request_id":"99999999-9999-4999-8999-999999999999","payload":{"played_at":"2026-08-07T10:00:00",
    "result":"win","turn_order":"first","note":"중복 저장하지 않을 메모",
    "standing_kind":"event_points","play_context_id":"dc_cup_2026_08","event_points_after":10000}}]', true);
select is(public.apply_game_changes(1, 2, current_setting('test.create')::jsonb)->'results'->0->>'status',
    'applied', '새 요청은 적용한다');
select is(public.apply_game_changes(1, 2, current_setting('test.create')::jsonb)->'results'->0->>'replayed',
    'true', '응답 유실 후 같은 요청은 영수증을 재생한다');
select is((select count(*)::int from public.games), 1, '재시도는 행을 추가하지 않는다');
select is((select change_version from public.games limit 1), 1::bigint, '재시도는 버전을 증가시키지 않는다');
select throws_ok($$ select public.apply_game_changes(1, 2,
    jsonb_set(current_setting('test.create')::jsonb, '{0,payload,result}', '"lose"')) $$,
    '22023', 'request_id reused with different payload', '같은 키의 다른 내용은 거절한다');
select is(public.apply_game_changes(1, 2, jsonb_build_array(
    (current_setting('test.create')::jsonb->0) - 'request_id')) -> 'results'->0->>'status',
    'conflict', '요청 ID가 없는 기존 클라이언트의 중복 생성 계약은 유지한다');
select is(public.apply_game_changes(1, 2, '[{"op":"update","id":"11111111-1111-4111-8111-111111111111",
    "expected_change_version":1,"payload":{"result":"lose"}}]')->'results'->0->>'status',
    'applied', '수정은 행 없는 성공 영수증을 반환한다');
select ok(not ((public.apply_game_changes(1, 2, current_setting('test.create')::jsonb)->'results'->0) ? 'remote'),
    '생성 재시도는 오래된 행을 캐시에 덮어쓰도록 반환하지 않는다');
select is((select result from public.games limit 1), 'lose', '생성 재시도는 이후 수정을 덮어쓰지 않는다');
select is(public.apply_game_changes(1, 2, jsonb_build_array(jsonb_build_object(
    'op', 'delete', 'id', '11111111-1111-4111-8111-111111111111',
    'expected_change_version', (select change_version from public.games where id = '11111111-1111-4111-8111-111111111111')
)))->'results'->0->>'status', 'applied', '삭제한다');
select is(public.apply_game_changes(1, 2, current_setting('test.create')::jsonb)->'results'->0->>'replayed',
    'true', '삭제 이후에도 원래 성공만 확인한다');
select ok((select deleted_at is not null from public.games limit 1), '재시도로 tombstone을 복원하지 않는다');
select is(public.apply_game_changes(1, 2, jsonb_build_array(jsonb_build_object(
    'op', 'restore', 'id', '11111111-1111-4111-8111-111111111111',
    'expected_change_version', (select change_version from public.games where id = '11111111-1111-4111-8111-111111111111')
))) -> 'results'->0->>'status', 'applied', '기존 복원 계약을 유지한다');
select is(public.apply_game_changes(1, 2, jsonb_build_array(jsonb_build_object(
    'op', 'update', 'id', '11111111-1111-4111-8111-111111111111',
    'expected_change_version', (select change_version from public.games where id = '11111111-1111-4111-8111-111111111111'),
    'payload', jsonb_build_object('turns', 2)),
    '{"op":"delete","id":"22222222-2222-4222-8222-222222222222","expected_change_version":null}'::jsonb))
    ->'results'->1->>'status', 'applied', '혼합 배치의 null CAS 삭제에 이전 버전이 누출되지 않는다');
select throws_ok($$ select * from public.game_create_receipts $$, '42501', null, '영수증 직접 읽기는 허용하지 않는다');
select throws_ok($$ select public.apply_game_changes_legacy(1, 2, '[]') $$,
    '42501', null, '내부 단일 항목 함수를 직접 실행하지 못한다');
select throws_ok($$ select public.apply_game_changes(1, 2, jsonb_build_array(
    (current_setting('test.create')::jsonb->0) || jsonb_build_object(
        'id', '55555555-5555-4555-8555-555555555555',
        'request_id', '88888888-8888-4888-8888-888888888888'),
    '{"op":"create","id":"66666666-6666-4666-8666-666666666666","payload":{}}'::jsonb)) $$,
    '22023', null, '배치 뒤쪽 검증 실패는 앞쪽 생성까지 롤백한다');
select is((select count(*)::int from public.games where id = '55555555-5555-4555-8555-555555555555'),
    0, '실패한 배치의 생성 행이 남지 않는다');
reset role;
select ok((select result::text not like '%중복 저장하지 않을 메모%' from public.game_create_receipts limit 1),
    '영수증에 원문 메모를 저장하지 않는다');
select is((select count(*)::int from public.game_create_receipts), 1, '실패한 배치의 영수증도 남지 않는다');
update public.game_modes set is_active = false where play_context_id = 'dc_cup_2026_08';
set local role authenticated;
select is(public.apply_game_changes(1, 2, current_setting('test.create')::jsonb)->'results'->0->>'replayed',
    'true', '모드 비활성화 후에도 이미 성공한 생성은 확인할 수 있다');
reset role;
update public.game_modes set is_active = true where play_context_id = 'dc_cup_2026_08';

-- 같은 요청 키도 사용자별로 격리한다.
set local role authenticated;
set local request.jwt.claims to '{"sub":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","role":"authenticated"}';
select is(public.apply_game_changes(1, 2, jsonb_set(current_setting('test.create')::jsonb,
    '{0,id}', '"33333333-3333-4333-8333-333333333333"'))->'results'->0->>'status',
    'applied', '다른 사용자의 동일 요청 키는 별개 요청이다');
select is((public.get_game_statistics()->'summary'->>'total')::int, 1, '다른 사용자의 기록은 집계에 포함되지 않는다');
select is(jsonb_array_length(public.list_game_history()->'games'), 1, '기록 페이지도 사용자별로 격리한다');
select is(public.get_record_state('2026-08-07')->'last_game'->>'id',
    '33333333-3333-4333-8333-333333333333', '입력 기준 상태도 사용자별로 격리한다');
reset role;

-- 최근 1000건 밖의 점수와 같은 시각의 UUID 경계를 검증한다.
set local request.jwt.claims to '{}';
insert into public.games(id, user_id, played_at, result, turn_order, turns, standing_kind, play_context_id,
    rank_tier_after, rank_division_after, payload_version)
select ('40000000-0000-4000-8000-' || lpad(n::text, 12, '0'))::uuid,
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', '2026-08-08T10:00:00', 'win', 'first', 2,
    'rank', 'rank_2026_08', 'master', 1, 2 from generate_series(1, 1001) n;

set local role authenticated;
set local request.jwt.claims to '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select is((public.get_game_statistics()->'summary'->>'total')::int, 1002, '전체 통계는 1000건에서 잘리지 않는다');
select is((public.get_game_statistics()->'summary'->>'wins')::int, 1001, '전체 승수를 집계한다');
select is((public.get_game_statistics()->'summary'->>'avg_turns')::numeric, 2::numeric, '턴 평균은 기존 의미를 유지한다');
select is((public.get_game_statistics('dc_cup_2026_08')->'summary'->>'total')::int, 1, '모드 필터를 집계 전에 적용한다');
select is(jsonb_array_length(public.get_game_statistics('rank_2026_08')->'series'), 1001, '차트 값도 전역 1000건에서 잘리지 않는다');
select is((select (g->>'event_points_after')::int from jsonb_array_elements(
    public.get_record_state('2026-08-08')->'latest_by_mode') g where g->>'standing_kind' = 'event_points'),
    10000, '오래된 모드의 기준 점수도 찾아낸다');
select is((public.get_record_state('2026-08-08')->'today'->>'wins')::int, 1001, '오늘 전적도 전체를 집계한다');
select is(public.list_game_history(p_limit => 2)->'games'->0->>'id',
    '40000000-0000-4000-8000-000000001001', '동일 시각은 UUID 내림차순으로 정렬한다');
select is(public.list_game_history(p_before_played_at => '2026-08-08T10:00:00',
    p_before_id => '40000000-0000-4000-8000-000000001000', p_limit => 2)->'games'->0->>'id',
    '40000000-0000-4000-8000-000000000999', '다음 페이지는 동률 커서 다음에서 시작한다');
select is(jsonb_array_length(public.list_game_history(p_context => 'dc_cup_2026_08')->'games'),
    1, '기록 필터는 전역 최신 페이지와 독립적이다');
select is(public.list_game_history(p_snapshot_version => 0)->>'stale', 'true', '변경된 snapshot의 다음 페이지를 섞지 않는다');
select throws_ok($$ select public.list_game_history(p_limit => 1000) $$, '22023', null, '페이지 크기를 제한한다');
select is(public.apply_game_changes(1, 2, '[{"op":"delete","id":"11111111-1111-4111-8111-111111111111"}]')
    ->'results'->0->>'status', 'applied', '삭제된 경기 제외를 검증한다');
select is((public.get_game_statistics('dc_cup_2026_08')->'summary'->>'total')::int, 0, '삭제된 경기는 통계에서 제외한다');
select is(jsonb_array_length(public.list_game_history(p_context => 'dc_cup_2026_08')->'games'), 0, '삭제된 경기는 목록에서 제외한다');
select is((select count(*)::int from jsonb_array_elements(public.get_record_state('2026-08-08')->'latest_by_mode') g
    where g->>'standing_kind' = 'event_points'), 0, '삭제된 경기는 모드 기준에서도 제외한다');
reset role;
set local role anon;
select throws_ok($$ select public.get_record_state('2026-08-08') $$, '42501', null, '익명 상태 조회를 차단한다');
select throws_ok($$ select public.get_game_statistics() $$, '42501', null, '익명 통계를 차단한다');
select throws_ok($$ select public.list_game_history() $$, '42501', null, '익명 목록 조회를 차단한다');
reset role;
delete from auth.users where id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
select is((select count(*)::int from public.game_create_receipts), 1, '계정 삭제는 본인 영수증만 제거한다');
select * from finish();
rollback;
