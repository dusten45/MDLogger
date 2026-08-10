-- H3 하드닝: release policy 테이블 권한·위조 방지 검증(0012).
--  - anon/authenticated는 읽기 전용(SELECT)으로만 조회할 수 있다.
--  - 클라이언트는 INSERT/UPDATE/DELETE 정책이 없어 수정할 수 없다.
--  - 로컬 개발 시드 정책이 존재한다(production 값은 소유자 운영 값).
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(6);

select results_eq(
    $$ select count(*)::int from pg_class c
       join pg_namespace n on n.oid = c.relnamespace
       where n.nspname = 'public' and c.relname = 'release_policies'
         and c.relrowsecurity $$,
    $$ values (1) $$,
    'release_policies에 RLS가 활성화되어 있다'
);

-- 클라이언트 수정 불가: SELECT 정책만 존재(INSERT/UPDATE/DELETE 정책 없음).
select policies_are(
    'public', 'release_policies', ARRAY['release_policies_select_public'],
    'release_policies에는 SELECT 정책만 존재한다'
);

set local role anon;
select results_eq(
    $$ select latest_version, minimum_supported_version
       from public.release_policies where platform = 'windows' $$,
    $$ values ('0.1.6', '0.1.6') $$,
    'anon은 정책(최소=최신=0.1.6)을 읽을 수 있다'
);
reset role;

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select results_eq(
    $$ select latest_version, minimum_supported_version
       from public.release_policies where platform = 'windows' $$,
    $$ values ('0.1.6', '0.1.6') $$,
    'authenticated도 정책(최소=최신=0.1.6)을 읽을 수 있다'
);
reset role;

-- authenticated는 정책 표를 수정할 수 없다. 테이블 UPDATE 권한을 주지 않았으므로
-- RLS 0행이 아니라 권한 거부(42501)로 차단된다. 이는 "클라이언트 수정 금지" 의도를
-- 유지한다(final_bugs 원인 2 옵션 A). 하드 오류는 파일 실행을 멈추므로 throws_ok로 잡는다.
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select throws_ok(
    $$ update public.release_policies
       set latest_version = '9.9.9'
       where platform = 'windows' $$,
    '42501', NULL,
    'authenticated는 release_policies를 수정할 수 없다(권한 회수)'
);
reset role;

select ok(
    (select allow_export from public.release_policies where platform = 'windows'),
    '데이터 탈출 경로 보장: allow_export는 true 기본값이다'
);

select * from finish();
rollback;
