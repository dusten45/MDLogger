-- 0001_profiles.sql
-- 등록 계정의 개인용 profile 테이블.
-- RLS는 생성 즉시 활성화하고(기본 전면 거부), 정책은 0003에서 추가한다.

create extension if not exists pgcrypto with schema extensions;

create table public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    display_name text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table public.profiles is
    '등록 계정의 개인용 프로필. 소유자 본인만 접근한다.';

alter table public.profiles enable row level security;

-- 클라이언트 물리 삭제 금지: 계정 삭제는 서버 함수(0006)에서만 수행한다.
revoke all on table public.profiles from anon, authenticated;
grant select, insert, update on table public.profiles to authenticated;

-- 공용 updated_at 유지 트리거.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

revoke all on function public.set_updated_at() from public;

create trigger profiles_set_updated_at
    before update on public.profiles
    for each row
    execute function public.set_updated_at();
