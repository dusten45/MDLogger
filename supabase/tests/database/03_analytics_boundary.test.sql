-- R4: 분석 데이터 경계 테스트.
-- 분석 테이블에 직접 식별자와 note가 들어가지 않아야 하고,
-- 클라이언트는 분석 스키마에 접근할 수 없어야 한다.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(12);

-- 스키마 수준 보증: 분석 테이블에는 note/email/직접 식별자 컬럼이 없다.
select hasnt_column(
    'analytics', 'duel_observations', 'note',
    'duel_observations에는 note 컬럼이 없다'
);
select hasnt_column(
    'analytics', 'duel_observations', 'email',
    'duel_observations에는 email 컬럼이 없다'
);
select hasnt_column(
    'analytics', 'duel_observations', 'user_id',
    'duel_observations에는 직접 auth user ID 컬럼이 없다'
);

insert into auth.users (id, email)
values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local');

-- 등록 계정 게임 저장 → projection 트리거가 observation을 만든다.
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

insert into public.games
    (id, user_id, played_at, result, turn_order, note, timezone_offset_minutes)
values ('11111111-1111-4111-8111-111111111111',
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        '2026-08-07T10:00:00', 'win', 'first', '개인 메모', 540);

-- 클라이언트는 분석 스키마를 읽거나 쓸 수 없다.
select throws_ok(
    $$ select count(*) from analytics.duel_observations $$,
    '42501',
    'permission denied for schema analytics',
    'authenticated는 duel_observations를 읽을 수 없다'
);
select throws_ok(
    $$ insert into analytics.duel_observations
           (source_game_id, played_at_local, result, turn_order,
            payload_version, source_kind)
       values (gen_random_uuid(), '2026-08-07T10:00:00', 'win', 'first',
               1, 'registered') $$,
    '42501',
    'permission denied for schema analytics',
    'authenticated는 duel_observations에 직접 INSERT할 수 없다'
);
select throws_ok(
    $$ select public.ingest_guest_batch(gen_random_uuid(), gen_random_uuid(),
                                        null, 1, '[]'::jsonb) $$,
    '42501',
    'permission denied for function ingest_guest_batch',
    'authenticated는 guest ingest 함수를 실행할 수 없다'
);

set local role anon;
select throws_ok(
    $$ select count(*) from analytics.duel_observations $$,
    '42501',
    'permission denied for schema analytics',
    'anon은 duel_observations를 읽을 수 없다'
);
select throws_ok(
    $$ select public.ingest_guest_batch(gen_random_uuid(), gen_random_uuid(),
                                        null, 1, '[]'::jsonb) $$,
    '42501',
    'permission denied for function ingest_guest_batch',
    'anon은 guest ingest 함수를 실행할 수 없다'
);

-- 서버 관점 검증(트리거 projection 내용).
reset role;

select results_eq(
    $$ select result, turn_order, source_kind, timezone_offset_minutes
       from analytics.duel_observations
       where source_game_id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values ('win', 'first', 'registered', 540) $$,
    '등록 게임 저장이 허용 필드만 observation으로 projection된다'
);

select isnt(
    (select contributor_key from analytics.duel_observations
     where source_game_id = '11111111-1111-4111-8111-111111111111'),
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'contributor_key는 auth user ID 원문이 아니다'
);

-- 개인 기록 삭제(tombstone)는 observation 철회로 반영된다.
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
update public.games set deleted_at = now()
where id = '11111111-1111-4111-8111-111111111111';
reset role;

select ok(
    (select withdrawn_at is not null and withdrawal_source = 'registered'
     from analytics.duel_observations
     where source_game_id = '11111111-1111-4111-8111-111111111111'),
    'tombstone이 분석 observation 철회로 반영된다'
);

select results_eq(
    $$ select count(*)::int from analytics.duel_observations
       where source_game_id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values (1) $$,
    '철회된 observation은 물리 삭제되지 않는다'
);

select * from finish();
rollback;
