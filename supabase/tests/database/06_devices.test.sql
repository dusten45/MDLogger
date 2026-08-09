-- R8: device register/touch, version 기록, monotonic acknowledged version.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(19);

insert into auth.users (id, email) values
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local'),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'user-b@test.local');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select is(
    public.register_or_touch_device(
        1, 1, '77777777-7777-4777-8777-777777777777', 'PC A', '0.2.0'
    ) ->> 'client_version',
    '0.2.0',
    '새 장치를 등록한다'
);

select results_eq(
    $$ select count(*)::int from public.devices $$,
    $$ values (1) $$,
    '장치가 한 행 생성된다'
);

create temporary table device_snapshot as
select id, created_at, last_seen_at
from public.devices
where installation_id = '77777777-7777-4777-8777-777777777777';

select throws_ok(
    $$ insert into public.devices (id, user_id, installation_id, client_version)
       values (gen_random_uuid(),
               'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
               gen_random_uuid(), '위조') $$,
    '42501',
    'permission denied for table devices',
    'authenticated의 직접 device INSERT는 차단된다'
);

select is(
    public.register_or_touch_device(
        1, 1, '77777777-7777-4777-8777-777777777777', 'PC A 갱신', '0.2.1'
    ) ->> 'display_name',
    'PC A 갱신',
    '같은 installation을 touch한다'
);

select results_eq(
    $$ select count(*)::int from public.devices $$,
    $$ values (1) $$,
    'touch가 중복 장치를 만들지 않는다'
);

select results_eq(
    $$ select d.id = s.id and d.created_at = s.created_at
       from public.devices d cross join device_snapshot s
       where d.installation_id = '77777777-7777-4777-8777-777777777777' $$,
    $$ values (true) $$,
    'touch가 장치 ID와 created_at을 보존한다'
);

select results_eq(
    $$ select display_name, client_version, sync_schema_version, payload_version
       from public.devices
       where installation_id = '77777777-7777-4777-8777-777777777777' $$,
    $$ values ('PC A 갱신', '0.2.1', 1, 1) $$,
    'touch가 표시 이름과 client/schema/payload version을 기록한다'
);

select ok(
    (select d.last_seen_at >= s.last_seen_at
     from public.devices d cross join device_snapshot s
     where d.installation_id = '77777777-7777-4777-8777-777777777777'),
    'touch가 server last_seen_at을 갱신한다'
);

select public.apply_game_changes(
    1, 1,
    '[{"op":"create","id":"11111111-1111-4111-8111-111111111111",
       "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                  "turn_order":"first"}}]'::jsonb
);

select is(
    (public.acknowledge_device_version(
        1, 1, '77777777-7777-4777-8777-777777777777',
        (select change_version from public.games
         where id = '11111111-1111-4111-8111-111111111111')
    ) ->> 'last_acknowledged_version')::bigint,
    (select change_version from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    'pull 완료 version을 acknowledge한다'
);

select lives_ok(
    $$ select public.acknowledge_device_version(
           1, 1, '77777777-7777-4777-8777-777777777777',
           (select last_acknowledged_version from public.devices
            where installation_id = '77777777-7777-4777-8777-777777777777')
       ) $$,
    '같은 acknowledged version 재전송은 idempotent하다'
);

select throws_ok(
    $$ select public.acknowledge_device_version(
           1, 1, '77777777-7777-4777-8777-777777777777', 0
       ) $$,
    '22023',
    'acknowledged_version cannot decrease',
    'acknowledged version 감소는 거부된다'
);

select throws_ok(
    $$ select public.acknowledge_device_version(
           1, 1, '77777777-7777-4777-8777-777777777777', 999999
       ) $$,
    '22023',
    'acknowledged_version exceeds server version',
    '서버 cursor보다 큰 acknowledged version은 거부된다'
);

select throws_ok(
    $$ select public.acknowledge_device_version(
           1, 1, '88888888-8888-4888-8888-888888888888', 0
       ) $$,
    '22023',
    'device is not registered',
    '등록되지 않은 장치는 acknowledge할 수 없다'
);

select throws_ok(
    $$ select public.register_or_touch_device(
           0, 1, '88888888-8888-4888-8888-888888888888', 'old', '0.1.0'
       ) $$,
    '22023',
    'unsupported sync_schema_version',
    '구버전 sync schema 장치 쓰기는 거부된다'
);

select throws_ok(
    $$ select public.register_or_touch_device(
           1, 2, '88888888-8888-4888-8888-888888888888', 'future', '9.0.0'
       ) $$,
    '22023',
    'unsupported payload_version',
    '미래 payload version 장치 쓰기는 거부된다'
);

select throws_ok(
    $$ update public.devices set last_acknowledged_version = 999999 $$,
    '42501',
    'permission denied for table devices',
    'authenticated의 직접 device UPDATE는 차단된다'
);

set local request.jwt.claims to
    '{"sub":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","role":"authenticated"}';

select results_eq(
    $$ select count(*)::int from public.devices $$,
    $$ values (0) $$,
    '다른 사용자는 A의 장치를 볼 수 없다'
);

select throws_ok(
    $$ select public.acknowledge_device_version(
           1, 1, '77777777-7777-4777-8777-777777777777', 0
       ) $$,
    '22023',
    'device is not registered',
    '다른 사용자는 A의 장치를 acknowledge할 수 없다'
);

set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select throws_ok(
    $$ select current_version from public.game_change_cursors $$,
    '42501',
    'permission denied for table game_change_cursors',
    '장치 클라이언트는 server clock을 직접 위조하거나 읽을 수 없다'
);

select * from finish();
rollback;
