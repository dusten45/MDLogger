-- R4: 등록 사용자 격리 공격 테스트.
-- 사용자 A 토큰으로 사용자 B의 모든 CRUD가 실패해야 하고,
-- 비인증(anon) 클라이언트는 private 테이블에 접근할 수 없어야 한다.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(12);

insert into auth.users (id, email) values
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local'),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'user-b@test.local');

-- 사용자 A로 동작.
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select lives_ok(
    $$ insert into public.profiles (id, display_name)
       values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'A') $$,
    'A는 자신의 profile을 만들 수 있다'
);

select lives_ok(
    $$ insert into public.games (id, user_id, played_at, result, turn_order, note)
       values ('11111111-1111-4111-8111-111111111111',
               'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
               '2026-08-07T10:00:00', 'win', 'first', 'A의 비밀 메모') $$,
    'A는 자신의 게임을 만들 수 있다'
);

select results_eq(
    $$ select count(*)::int from public.games $$,
    $$ values (1) $$,
    'A는 자신의 게임을 조회한다'
);

-- 사용자 B로 전환.
set local request.jwt.claims to
    '{"sub":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","role":"authenticated"}';

select results_eq(
    $$ select count(*)::int from public.games $$,
    $$ values (0) $$,
    'B에게는 A의 게임이 보이지 않는다'
);

select results_eq(
    $$ select count(*)::int from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values (0) $$,
    'B는 game UUID를 알아도 A의 행을 읽을 수 없다'
);

-- B의 탈취 시도 UPDATE는 어떤 행에도 적용되지 않아야 한다.
update public.games set note = '탈취됨'
where id = '11111111-1111-4111-8111-111111111111';

select results_eq(
    $$ select count(*)::int from public.profiles $$,
    $$ values (0) $$,
    'B에게는 A의 profile이 보이지 않는다'
);

select throws_ok(
    $$ delete from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    '42501',
    'permission denied for table games',
    'B는 games를 물리 삭제할 수 없다'
);

-- 다시 A: 데이터가 그대로여야 하고, A 본인도 물리 삭제는 불가능하다.
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select results_eq(
    $$ select note from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values ('A의 비밀 메모') $$,
    'B의 UPDATE 시도 후에도 A의 데이터는 변경되지 않는다'
);

select throws_ok(
    $$ delete from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    '42501',
    'permission denied for table games',
    '클라이언트는 tombstone 대신 물리 DELETE를 사용할 수 없다'
);

-- 비인증 anon 클라이언트.
set local role anon;

select throws_ok(
    $$ select count(*) from public.games $$,
    '42501',
    'permission denied for table games',
    'anon은 games를 읽을 수 없다'
);

select throws_ok(
    $$ insert into public.games (id, user_id, played_at, result, turn_order)
       values (gen_random_uuid(),
               'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
               '2026-08-07T10:00:00', 'win', 'first') $$,
    '42501',
    'permission denied for table games',
    'anon은 games에 쓸 수 없다'
);

select throws_ok(
    $$ select count(*) from public.profiles $$,
    '42501',
    'permission denied for table profiles',
    'anon은 profiles를 읽을 수 없다'
);

select * from finish();
rollback;
