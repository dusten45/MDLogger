-- 0003_rls.sql
-- 등록 사용자의 소유자 전용 RLS 정책.
-- 클라이언트 필터는 보안 경계가 아니며(로드맵 8.1) 모든 행 접근은
-- auth.uid() 소유권으로만 허용한다. anon에는 어떤 권한도 부여하지 않는다.

-- profiles: 본인 행만 조회/생성/수정.
create policy profiles_select_own
    on public.profiles
    for select
    to authenticated
    using (id = (select auth.uid()));

create policy profiles_insert_own
    on public.profiles
    for insert
    to authenticated
    with check (id = (select auth.uid()));

create policy profiles_update_own
    on public.profiles
    for update
    to authenticated
    using (id = (select auth.uid()))
    with check (id = (select auth.uid()));

-- games: 본인 소유 행만 조회/생성/수정. UUID를 알아도 타인 행에 접근할 수 없다.
create policy games_select_own
    on public.games
    for select
    to authenticated
    using (user_id = (select auth.uid()));

create policy games_insert_own
    on public.games
    for insert
    to authenticated
    with check (user_id = (select auth.uid()));

create policy games_update_own
    on public.games
    for update
    to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

-- devices: 본인 장치 행만 조회/생성/수정.
create policy devices_select_own
    on public.devices
    for select
    to authenticated
    using (user_id = (select auth.uid()));

create policy devices_insert_own
    on public.devices
    for insert
    to authenticated
    with check (user_id = (select auth.uid()));

create policy devices_update_own
    on public.devices
    for update
    to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));
