-- H5/H6 하드닝: guest ingest rate limit·Edge 전용 권한 검증(0014).
--  - service_role만 guest_rate_ok/guest_rate_check를 실행할 수 있다.
--  - 슬라이딩 창이 초과되면 blocked(+retry_after_seconds)를 반환한다.
--  - anon/authenticated는 카운터 테이블과 함수에 접근할 수 없다.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(10);

set local role service_role;

select is(
    (public.guest_rate_ok('ok-key', 5, 3) ->> 'allowed'),
    'true',
    '창 허용치 안의 첫 요청은 허용된다'
);

-- 'boom' 키에 이미 2건이 있으면 max=2 초과로 차단된다.
-- 준비용 행은 직접 표에 INSERT하지 않고, 실제 기록 경로인 guest_rate_ok를 두 번
-- 호출해 쌓는다(표에 대한 불필요한 권한 없이 최소 권한 유지, final_bugs 원인 1 후속).
select is(
    (public.guest_rate_ok('boom', 5, 2) ->> 'allowed'),
    'true',
    'boom 첫 번째 호출은 허용된다(기록됨)'
);
select is(
    (public.guest_rate_ok('boom', 5, 2) ->> 'allowed'),
    'true',
    'boom 두 번째 호출도 허용된다(기록됨)'
);
select is(
    (public.guest_rate_ok('boom', 5, 2) ->> 'allowed'),
    'false',
    '창 허용치 초과 시 차단된다'
);
select ok(
    (public.guest_rate_ok('boom', 5, 2) ->> 'retry_after_seconds')::integer >= 1,
    '차단 시 재시도 대기 시간을 돌려준다'
);
-- 기본 임계값(결정 D-4 확정): 1분 창 최대 10회. 10회까지 허용되고 11회째 차단된다.
set local role service_role;
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select public.guest_rate_check(
    '12121212-1212-4212-8212-121212121212', '203.0.113.9');
select is(
    (public.guest_rate_check(
        '12121212-1212-4212-8212-121212121212', '203.0.113.9'
    ) ->> 'allowed'),
    'false',
    '기본 임계값(1분 창 10회)을 초과하면 차단된다'
);
reset role;

-- guest_rate_check: installation 단위로 max=1이면 두 번째 요청은 차단된다.
set local role service_role;
select is(
    (public.guest_rate_check(
        '77777777-7777-4777-8777-777777777777', '203.0.113.1', 1, 1
    ) ->> 'allowed'),
    'true',
    'installation/IP 이중 검사 첫 요청은 허용된다'
);
select is(
    (public.guest_rate_check(
        '77777777-7777-4777-8777-777777777777', '203.0.113.1', 1, 1
    ) ->> 'allowed'),
    'false',
    '같은 installation로 두 번째 요청은 차단된다'
);
reset role;

set local role anon;
select throws_ok(
    $$ select public.guest_rate_ok('k', 5, 3) $$,
    '42501', NULL,
    'anon은 rate limit 함수를 실행할 수 없다'
);
select throws_ok(
    $$ select * from public.guest_rate_events $$,
    '42501', NULL,
    'anon은 rate 카운터 테이블에 접근할 수 없다'
);
reset role;

select * from finish();
rollback;
