-- 2-B: user_settings RLS 격리 + upsert_user_settings allowlist 검증 (spec §8.3).
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(8);

insert into auth.users (id, email) values
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local'),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'user-b@test.local');

-- anon은 user_settings를 읽을 수 없다.
set local role anon;
select throws_ok(
    $$ select count(*) from public.user_settings $$,
    '42501', NULL,
    'anon은 user_settings를 읽을 수 없다'
);
reset role;

-- authenticated: 취향 설정 upsert 양성 경로.
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select is(
    (public.upsert_user_settings(
        '{"theme_mode":"dark","memo_enabled":false}'::jsonb
    ) ->> 'theme_mode'),
    'dark',
    '취향 설정을 upsert한다'
);

select is(
    (select preferences ->> 'memo_enabled' from public.user_settings
     where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
    'false',
    'upsert된 설정이 저장된다'
);

-- DEVICE_KEYS 포함 payload는 거부된다(서버 하드 차단).
select throws_ok(
    $$ select public.upsert_user_settings('{"font_scale":1.5}'::jsonb) $$,
    '22023', NULL,
    '기기 특성 설정(font_scale)은 거부된다'
);

select throws_ok(
    $$ select public.upsert_user_settings('{"low_spec_mode":true}'::jsonb) $$,
    '22023', NULL,
    '기기 특성 설정(low_spec_mode)은 거부된다'
);

-- allowlist 외 키도 거부된다.
select throws_ok(
    $$ select public.upsert_user_settings('{"unknown_key":1}'::jsonb) $$,
    '22023', NULL,
    'allowlist 외 키는 거부된다'
);

-- on conflict do update: 기존 행을 갱신한다.
select is(
    (public.upsert_user_settings('{"accent_color":"teal"}'::jsonb) ->> 'accent_color'),
    'teal',
    '기존 행을 갱신한다'
);

-- RLS 격리: 다른 사용자는 A의 행을 볼 수 없다.
set local request.jwt.claims to
    '{"sub":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","role":"authenticated"}';
select results_eq(
    $$ select count(*)::int from public.user_settings $$,
    $$ values (0) $$,
    '다른 사용자는 A의 설정을 볼 수 없다'
);

select * from finish();
rollback;
