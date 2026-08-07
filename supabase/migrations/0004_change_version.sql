-- 0004_change_version.sql
-- 서버 변경 버전과 서버 관리 필드 강제.
-- `user_id`, `created_at`, `updated_at`, `change_version`은 클라이언트가
-- 임의 설정하거나 바꿀 수 없다(로드맵 7.3). pull cursor는 이 버전을 사용한다.

create sequence public.games_change_version_seq;

-- 트리거 함수는 security definer로 실행되어 클라이언트에 sequence 권한을
-- 부여하지 않는다.
create or replace function public.enforce_game_server_fields()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
begin
    if tg_op = 'INSERT' then
        -- 인증된 클라이언트 요청이면 위조된 user_id를 요청자 본인으로 강제한다.
        if request_user is not null then
            new.user_id := request_user;
        end if;
        new.created_at := now();
    else
        -- 소유자, 기본 키, 생성 시각은 변경할 수 없다.
        new.id := old.id;
        new.user_id := old.user_id;
        new.created_at := old.created_at;
        -- tombstone은 되돌릴 수 있지만(충돌 해결) 클라이언트가 임의로
        -- 과거 시각을 위조하지 못하도록 새 tombstone 시각은 서버가 부여한다.
        if new.deleted_at is not null and old.deleted_at is null then
            new.deleted_at := now();
        end if;
    end if;

    new.updated_at := now();
    new.change_version := nextval('public.games_change_version_seq');
    return new;
end;
$$;

revoke all on function public.enforce_game_server_fields() from public;

create trigger games_enforce_server_fields
    before insert or update on public.games
    for each row
    execute function public.enforce_game_server_fields();

-- devices에도 같은 소유권 강제를 적용한다.
create or replace function public.enforce_device_server_fields()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
begin
    if tg_op = 'INSERT' then
        if request_user is not null then
            new.user_id := request_user;
        end if;
        new.created_at := now();
    else
        new.id := old.id;
        new.user_id := old.user_id;
        new.created_at := old.created_at;
    end if;
    new.last_seen_at := now();
    return new;
end;
$$;

revoke all on function public.enforce_device_server_fields() from public;

create trigger devices_enforce_server_fields
    before insert or update on public.devices
    for each row
    execute function public.enforce_device_server_fields();
