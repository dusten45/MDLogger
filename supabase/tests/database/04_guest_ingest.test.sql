-- R4: Guest Ingest 경계 테스트.
-- 허용된 분석 필드 외 payload는 거부되고, batch와 observation은
-- idempotent해야 하며, 계정 삭제 인터페이스가 분석 행을 보존해야 한다.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(14);

-- Edge Function과 같은 자격(service_role)으로 실행한다.
set local role service_role;

select is(
    (public.ingest_guest_batch(
        '99999999-9999-4999-8999-999999999999',
        '77777777-7777-4777-8777-777777777777',
        '0.1.0',
        1,
        '[{"sync_id":"33333333-3333-4333-8333-333333333333",
           "played_at_local":"2026-08-07T12:00:00",
           "result":"win","turn_order":"second","turns":6,
           "end_reason":"regular"},
          {"sync_id":"44444444-4444-4444-8444-444444444444",
           "played_at_local":"2026-08-07T12:10:00",
           "result":"lose","turn_order":"first",
           "note":"이건 들어가면 안 됨"}]'::jsonb
    )) - 'batch_id',
    '{"accepted":1,"skipped":0,"rejected":1,"replayed":false}'::jsonb,
    'note가 포함된 observation은 거부되고 정상 observation만 수락된다'
);

reset role;

select results_eq(
    $$ select reason from analytics.rejected_observations
       where batch_id = '99999999-9999-4999-8999-999999999999' $$,
    $$ values ('disallowed_field:note') $$,
    '거부 이유가 기록된다'
);

select results_eq(
    $$ select count(*)::int from analytics.duel_observations
       where source_game_id = '44444444-4444-4444-8444-444444444444' $$,
    $$ values (0) $$,
    '거부된 observation은 저장되지 않는다'
);

select results_eq(
    $$ select source_kind, client_version, contributor_key is not null
       from analytics.duel_observations
       where source_game_id = '33333333-3333-4333-8333-333333333333' $$,
    $$ values ('guest', '0.1.0', true) $$,
    '수락된 게스트 observation은 guest source와 pseudonym을 가진다'
);

select isnt(
    (select contributor_key from analytics.duel_observations
     where source_game_id = '33333333-3333-4333-8333-333333333333'),
    '77777777-7777-4777-8777-777777777777',
    'installation ID 원문은 분석 행에 저장되지 않는다'
);

set local role service_role;

-- 같은 batch 재전송: 응답이 끊긴 뒤 재시도해도 중복이 생기지 않는다.
select is(
    (public.ingest_guest_batch(
        '99999999-9999-4999-8999-999999999999',
        '77777777-7777-4777-8777-777777777777',
        '0.1.0',
        1,
        '[{"sync_id":"33333333-3333-4333-8333-333333333333",
           "played_at_local":"2026-08-07T12:00:00",
           "result":"win","turn_order":"second"}]'::jsonb
    )) ->> 'replayed',
    'true',
    '같은 batch 재전송은 저장된 요약으로 응답한다'
);

-- 다른 batch에서 같은 sync_id: observation 수준 idempotency.
select is(
    (public.ingest_guest_batch(
        '88888888-8888-4888-8888-888888888888',
        '77777777-7777-4777-8777-777777777777',
        '0.1.0',
        1,
        '[{"sync_id":"33333333-3333-4333-8333-333333333333",
           "played_at_local":"2026-08-07T12:00:00",
           "result":"win","turn_order":"second"}]'::jsonb
    )) - 'batch_id',
    '{"accepted":0,"skipped":1,"rejected":0,"replayed":false}'::jsonb,
    '같은 sync_id observation은 중복 생성되지 않는다'
);

-- 다른 batch의 명시적 upsert는 동일 게스트 observation의 수정값을 반영한다.
select is(
    (public.ingest_guest_batch(
        '12121212-1212-4212-8212-121212121212',
        '77777777-7777-4777-8777-777777777777',
        '0.1.0',
        1,
        '[{"op":"upsert",
           "sync_id":"33333333-3333-4333-8333-333333333333",
           "played_at_local":"2026-08-07T12:00:00",
           "timezone_offset_minutes":540,
           "result":"lose","turn_order":"first","turns":8}]'::jsonb
    )) ->> 'accepted',
    '1',
    '게스트 upsert operation이 수락된다'
);

reset role;

select results_eq(
    $$ select result, turn_order, turns, timezone_offset_minutes
       from analytics.duel_observations
       where source_game_id = '33333333-3333-4333-8333-333333333333' $$,
    $$ values ('lose', 'first', 8, 540) $$,
    '게스트 upsert가 기존 observation의 분석 필드를 갱신한다'
);

set local role service_role;

-- 게스트 철회 operation.
select is(
    (public.ingest_guest_batch(
        '66666666-6666-4666-8666-666666666666',
        '77777777-7777-4777-8777-777777777777',
        '0.1.0',
        1,
        '[{"op":"withdraw",
           "sync_id":"33333333-3333-4333-8333-333333333333"}]'::jsonb
    )) ->> 'accepted',
    '1',
    '게스트 withdraw operation이 수락된다'
);

reset role;

select ok(
    (select withdrawn_at is not null and withdrawal_source = 'guest'
     from analytics.duel_observations
     where source_game_id = '33333333-3333-4333-8333-333333333333'),
    '철회된 게스트 observation에 withdrawn_at이 기록된다'
);

-- 잘못된 payload 계약: 빈 배열은 함수 수준에서 거부된다.
set local role service_role;
select throws_ok(
    $$ select public.ingest_guest_batch(gen_random_uuid(), gen_random_uuid(),
                                        null, 1, '[]'::jsonb) $$,
    '22023',
    'batch size must be between 1 and 200',
    '빈 batch는 거부된다'
);
reset role;

-- 계정 삭제 인터페이스: 개인 데이터는 삭제하고 분석 행은 보존한다(결정 4).
insert into auth.users (id, email)
values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
insert into public.profiles (id) values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');
select public.apply_game_changes(
    1, 1,
    '[{"op":"create","id":"55555555-5555-4555-8555-555555555555",
       "payload":{"played_at":"2026-08-07T13:00:00","result":"win",
                  "turn_order":"first","note":"지워질 개인 메모"}}]'::jsonb
);
set local role service_role;

select is(
    (public.delete_account_data('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'))
        - 'user_id',
    '{"deleted_games":1,"deleted_devices":0,"deleted_profiles":1}'::jsonb,
    '계정 삭제 함수가 개인용 데이터를 삭제한다'
);

reset role;

select ok(
    (select withdrawn_at is null
     from analytics.duel_observations
     where source_game_id = '55555555-5555-4555-8555-555555555555'),
    '계정 삭제는 분석 observation을 보존하고 철회 처리하지 않는다'
);

select * from finish();
rollback;
