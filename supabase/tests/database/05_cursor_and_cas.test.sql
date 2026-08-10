-- R8: change_version cursor, optimistic concurrency, 수정/삭제 충돌 테스트.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(37);

insert into auth.users (id, email)
values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select is(
    public.apply_game_changes(
        1, 1,
        '[{"op":"create","id":"11111111-1111-4111-8111-111111111111",
           "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                      "turn_order":"first"}},
          {"op":"create","id":"22222222-2222-4222-8222-222222222222",
           "payload":{"played_at":"2026-08-07T10:00:00","result":"lose",
                      "turn_order":"second"}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    'batch의 첫 create가 적용된다'
);

select is(
    public.apply_game_changes(
        1, 1,
        '[{"op":"create","id":"33333333-3333-4333-8333-333333333333",
           "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                      "turn_order":"first"}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    '후속 create가 적용된다'
);

select results_eq(
    $$ select count(distinct updated_at)::int from public.games $$,
    $$ values (1) $$,
    '같은 transaction timestamp를 가진 변경도 허용된다'
);

select ok(
    (select count(distinct change_version) = 3
            and min(change_version) > 0
     from public.games),
    '같은 사용자의 각 변경은 고유한 version을 받는다'
);

select results_eq(
    $$ select id from public.games
       where change_version > (
           select change_version from public.games
           where id = '11111111-1111-4111-8111-111111111111'
       )
       order by change_version asc $$,
    $$ values
       ('22222222-2222-4222-8222-222222222222'::uuid),
       ('33333333-3333-4333-8333-333333333333'::uuid) $$,
    'cursor보다 큰 변경이 version 순서로 빠짐없이 조회된다'
);

select results_eq(
    $$ select count(*)::int from pg_indexes
       where schemaname = 'public' and tablename = 'games'
         and indexname = 'idx_games_user_change_version_unique'
         and indexdef like 'CREATE UNIQUE INDEX%' $$,
    $$ values (1) $$,
    '사용자별 change_version unique index가 존재한다'
);

select is(
    public.apply_game_changes(
        1, 1,
        jsonb_build_array(jsonb_build_object(
            'op', 'update',
            'id', '11111111-1111-4111-8111-111111111111',
            'expected_change_version',
                (select change_version from public.games
                 where id = '11111111-1111-4111-8111-111111111111'),
            'payload', jsonb_build_object('result', 'lose', 'turns', 7)
        ))
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    '일치하는 expected version의 수정이 적용된다'
);

select results_eq(
    $$ select result, turns from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values ('lose', 7) $$,
    '수정 payload가 저장된다'
);

select is(
    public.apply_game_changes(
        1, 1,
        '[{"op":"update","id":"11111111-1111-4111-8111-111111111111",
           "expected_change_version":1,
           "payload":{"result":"win","turns":99}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'conflict',
    '동시 수정의 stale expected version은 conflict다'
);

select is(
    public.apply_game_changes(
        1, 1,
        '[{"op":"update","id":"11111111-1111-4111-8111-111111111111",
           "expected_change_version":1,
           "payload":{"result":"win","turns":99}}]'::jsonb
    ) -> 'results' -> 0 -> 'remote' ->> 'result',
    'lose',
    '수정 conflict가 현재 remote payload를 반환한다'
);

select results_eq(
    $$ select result, turns from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values ('lose', 7) $$,
    'stale 수정이 현재 데이터를 덮어쓰지 않는다'
);

select is(
    public.apply_game_changes(
        1, 1,
        '[{"op":"delete","id":"11111111-1111-4111-8111-111111111111",
           "expected_change_version":1}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'conflict',
    '수정 후 stale delete는 conflict다'
);

select ok(
    (select deleted_at is null from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    'stale delete가 수정된 행을 삭제하지 않는다'
);

select is(
    public.apply_game_changes(
        1, 1,
        jsonb_build_array(jsonb_build_object(
            'op', 'delete',
            'id', '11111111-1111-4111-8111-111111111111',
            'expected_change_version',
                (select change_version from public.games
                 where id = '11111111-1111-4111-8111-111111111111')
        ))
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    '현재 version의 delete가 적용된다'
);

select results_eq(
    $$ select count(*)::int from public.games
       where change_version > 3 and deleted_at is not null $$,
    $$ values (1) $$,
    'tombstone도 cursor pull 대상에 포함된다'
);

select is(
    public.apply_game_changes(
        1, 1,
        '[{"op":"update","id":"11111111-1111-4111-8111-111111111111",
           "expected_change_version":4,
           "payload":{"result":"win"}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'conflict',
    '삭제 후 stale 수정은 conflict다'
);

select ok(
    (public.apply_game_changes(
        1, 1,
        '[{"op":"update","id":"11111111-1111-4111-8111-111111111111",
           "expected_change_version":4,
           "payload":{"result":"win"}}]'::jsonb
     ) -> 'results' -> 0 -> 'remote' ->> 'deleted_at') is not null,
    '수정/삭제 conflict가 remote tombstone을 반환한다'
);

select is(
    public.apply_game_changes(
        1, 1,
        jsonb_build_array(jsonb_build_object(
            'op', 'update',
            'id', '11111111-1111-4111-8111-111111111111',
            'expected_change_version',
                (select change_version from public.games
                 where id = '11111111-1111-4111-8111-111111111111'),
            'payload', jsonb_build_object('result', 'win')
        ))
    ) -> 'results' -> 0 ->> 'status',
    'conflict',
    '정확한 tombstone version이어도 일반 update는 복원하지 않는다'
);

select is(
    public.apply_game_changes(
        1, 1,
        jsonb_build_array(jsonb_build_object(
            'op', 'restore',
            'id', '11111111-1111-4111-8111-111111111111',
            'expected_change_version',
                (select change_version from public.games
                 where id = '11111111-1111-4111-8111-111111111111'),
            'payload', jsonb_build_object('result', 'win')
        ))
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    '명시적 restore가 tombstone을 복원한다'
);

select ok(
    (select deleted_at is null and result = 'win' from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    'restore 결과가 private game에 반영된다'
);

reset role;
select results_eq(
    $$ select current_version >= (select max(change_version) from public.games
                                   where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
       from public.game_change_cursors
       where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' $$,
    $$ values (true) $$,
    'transactional clock은 저장된 최대 game version보다 뒤처지지 않는다'
);
create temporary table duplicate_cursor_snapshot as
select current_version
from public.game_change_cursors
where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select is(
    public.apply_game_changes(
        1, 1,
        '[{"op":"create","id":"11111111-1111-4111-8111-111111111111",
           "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                      "turn_order":"first"}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'conflict',
    '중복 create는 기존 행을 덮어쓰지 않고 conflict를 반환한다'
);

reset role;
select results_eq(
    $$ select c.current_version = s.current_version
       from public.game_change_cursors c cross join duplicate_cursor_snapshot s
       where c.user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' $$,
    $$ values (true) $$,
    '중복 create 재전송은 change cursor를 증가시키지 않는다'
);
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select throws_ok(
    $$ select public.apply_game_changes(
           0, 1,
           '[{"op":"create","id":"44444444-4444-4444-8444-444444444444",
              "payload":{"played_at":"2026-08-07T10:00:00",
                         "result":"win","turn_order":"first"}}]'::jsonb
       ) $$,
    '22023',
    'unsupported sync_schema_version',
    '구버전 sync schema 쓰기는 차단된다'
);

select throws_ok(
    $$ select public.apply_game_changes(
           2, 1,
           '[{"op":"create","id":"44444444-4444-4444-8444-444444444444",
              "payload":{"played_at":"2026-08-07T10:00:00",
                         "result":"win","turn_order":"first"}}]'::jsonb
       ) $$,
    '22023',
    'unsupported sync_schema_version',
    '미래 sync schema 쓰기는 차단된다'
);

select throws_ok(
    $$ select public.apply_game_changes(
           1, 0,
           '[{"op":"create","id":"44444444-4444-4444-8444-444444444444",
              "payload":{"played_at":"2026-08-07T10:00:00",
                         "result":"win","turn_order":"first"}}]'::jsonb
       ) $$,
    '22023',
    'unsupported payload_version',
    '구버전 payload 쓰기는 차단된다'
);

select throws_ok(
    $$ select public.apply_game_changes(
           1, 1,
           '[{"op":"create","id":"44444444-4444-4444-8444-444444444444",
              "user_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
              "payload":{"played_at":"2026-08-07T10:00:00",
                         "result":"win","turn_order":"first"}}]'::jsonb
       ) $$,
    '22023',
    'disallowed change field: user_id',
    '허용되지 않은 change envelope 필드는 거부된다'
);

select throws_ok(
    $$ select public.apply_game_changes(
           1, 1,
           '[{"op":"create","id":"44444444-4444-4444-8444-444444444444",
              "payload":{"played_at":"2026-08-07T10:00:00",
                         "result":"win","turn_order":"first",
                         "change_version":999}}]'::jsonb
       ) $$,
    '22023',
    'disallowed game payload field: change_version',
    '서버 관리 game 필드는 payload allowlist에서 거부된다'
);

select throws_ok(
    $$ select current_version from public.game_change_cursors $$,
    '42501',
    'permission denied for table game_change_cursors',
    'authenticated는 change-version clock을 직접 읽을 수 없다'
);

-- P0-1: delete-if-exists(0018). expected_change_version 없이도 삭제를 표현한다.
select is(
    public.apply_game_changes(
        1, 1,
        '[{"op":"create","id":"b0000000-0000-4000-8000-000000000001",
           "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                      "turn_order":"first"}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    'delete-if-exists 준비용 create가 적용된다'
);

select is(
    public.apply_game_changes(
        1, 1,
        '[{"op":"delete","id":"b0000000-0000-4000-8000-000000000001"}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    'CAS 없는 delete-if-exists가 존재하는 기록을 soft delete한다'
);

select ok(
    (select deleted_at is not null from public.games
     where id = 'b0000000-0000-4000-8000-000000000001'),
    'delete-if-exists 결과가 서버에 반영된다'
);

select ok(
    (public.apply_game_changes(
        1, 1,
        '[{"op":"delete","id":"b0000000-0000-4000-8000-000000000001"}]'::jsonb
    ) -> 'results' -> 0 -> 'change_version') is null,
    '이미 삭제된 기록의 delete-if-exists는 멱등 성공(버전 null)이다'
);

select ok(
    (public.apply_game_changes(
        1, 1,
        '[{"op":"delete","id":"b0000000-0000-4000-8000-000000000002"}]'::jsonb
    ) -> 'results' -> 0 -> 'change_version') is null,
    '존재하지 않는 기록의 delete-if-exists는 멱등 성공(버전 null)이다'
);

select throws_ok(
    $$ select public.apply_game_changes(
           1, 1,
           '[{"op":"delete","id":"b0000000-0000-4000-8000-000000000002",
              "payload":{"note":"x"}}]'::jsonb
       ) $$,
    '22023',
    'delete payload must be empty',
    'delete-if-exists도 빈 payload만 허용한다'
);

-- P2-7: 위조된 과거 deleted_at은 서버가 now()로 덮어쓴다(0004/0009 tombstone 강제).
-- 클라이언트가 임의의 과거 시각을 tombstone으로 위조하지 못하도록, 새 tombstone은
-- 테이블 소유자 자격의 직접 UPDATE여도 서버 시각으로만 기록된다.
reset role;
update public.games
set deleted_at = '2020-01-01T00:00:00'
where id = '11111111-1111-4111-8111-111111111111';
select ok(
    (select deleted_at > '2020-01-01T00:00:00' from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    '위조된 과거 deleted_at은 서버가 now()로 덮어쓴다'
);
select ok(
    (select deleted_at is not null from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    '서버가 부여한 tombstone 시각이 기록된다'
);

select * from finish();
rollback;
