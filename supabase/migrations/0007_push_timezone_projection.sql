-- 0007_push_timezone_projection.sql
-- 단계 7 push부터 신규 기록의 기록 시점 UTC offset을 private games와
-- 등록 계정 분석 projection에 보존한다. 기존 행은 추측하지 않고 NULL로 둔다.

alter table public.games
    add column timezone_offset_minutes integer
    check (timezone_offset_minutes is null
           or timezone_offset_minutes between -1440 and 1440);

create or replace function analytics.project_registered_game_timezone()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.deleted_at is null then
        update analytics.duel_observations
        set timezone_offset_minutes = new.timezone_offset_minutes
        where source_game_id = new.id;
    end if;
    return null;
end;
$$;

revoke all on function analytics.project_registered_game_timezone() from public;

-- PostgreSQL의 같은 event trigger는 이름순 실행된다. 기존
-- games_project_observation 뒤에 실행되어 방금 upsert된 observation을 보완한다.
create trigger games_project_timezone
    after insert or update on public.games
    for each row
    execute function analytics.project_registered_game_timezone();
