-- 0022_game_modes.sql
-- 1단계: 서버 game_modes 기준정보 (B2, spec §4.8).
--
-- 모드의 원본은 서버이며, 로컬 play_modes는 그 클라이언트 캐시다.
-- - anon/authenticated는 SELECT만 허용(공개 기준정보).
-- - 쓰기는 관리자 전용 RPC(manage_game_modes) + 관리자 역할만.
-- - apply_game_changes가 모든 기록의 play_context_id가 이 표에 존재·활성인지
--   검증하는 헬퍼(game_mode_context_valid)를 함께 만든다. 실제 호출은 0023에서.

create table public.game_modes (
    id text primary key,
    standing_kind text not null
        check (standing_kind in ('rank', 'rating', 'event_points')),
    display_name text not null,
    play_context_id text,
    sort_order integer not null default 0,
    is_active boolean not null default true,
    season_label text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table public.game_modes is
    '모드/시즌 기준정보. 원본이며 클라이언트 play_modes는 이 캐시다(B2).';

alter table public.game_modes enable row level security;

revoke all on table public.game_modes from anon, authenticated;
grant select on table public.game_modes to anon, authenticated;
-- 관리 도구(service-role key)의 목록 조회용 SELECT.
grant select on table public.game_modes to service_role;

create policy game_modes_select_public
    on public.game_modes
    for select
    to anon, authenticated
    using (true);

-- 관리자 전용 RPC: game_modes CRUD (spec §4.8, 3-b=②).
-- 관리자 자격은 Supabase service_role(service-role key)이다. 이 key는 서버
-- 환경 변수 전용이며 클라이언트/사용자 빌드에 포함되지 않는다(옵션 a).
create or replace function public.manage_game_modes(
    operation text,
    mode_id text,
    standing_kind text default null,
    display_name text default null,
    play_context_id text default null,
    sort_order integer default null,
    is_active boolean default null,
    season_label text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    result jsonb;
begin
    if auth.role() <> 'service_role' then
        raise exception 'admin role required' using errcode = '42501';
    end if;
    if operation = 'upsert' then
        insert into public.game_modes (
            id, standing_kind, display_name, play_context_id,
            sort_order, is_active, season_label, updated_at
        )
        values (
            mode_id, standing_kind, display_name, play_context_id,
            coalesce(sort_order, 0), coalesce(is_active, true), season_label, now()
        )
        on conflict (id) do update set
            standing_kind = excluded.standing_kind,
            display_name = excluded.display_name,
            play_context_id = excluded.play_context_id,
            sort_order = excluded.sort_order,
            is_active = excluded.is_active,
            season_label = excluded.season_label,
            updated_at = now()
        returning to_jsonb(game_modes) into result;
    elsif operation = 'delete' then
        delete from public.game_modes as gm
        where gm.id = mode_id
        returning to_jsonb(gm) into result;
        if result is null then
            raise exception 'mode not found' using errcode = '22000';
        end if;
    else
        raise exception 'unsupported operation' using errcode = '22023';
    end if;
    return result;
end;
$$;

revoke all on function public.manage_game_modes(
    text, text, text, text, text, integer, boolean, text
) from public, anon, authenticated;
grant execute on function public.manage_game_modes(
    text, text, text, text, text, integer, boolean, text
) to service_role;

-- apply_game_changes 문맥 검증 헬퍼: play_context_id가 존재·활성·kind 일치인지 (spec §4.7).
create or replace function public.game_mode_context_valid(
    p_play_context_id text,
    p_standing_kind text
)
returns boolean
language sql
security definer
set search_path = ''
as $$
    select exists (
        select 1 from public.game_modes
        where play_context_id = p_play_context_id
          and standing_kind = p_standing_kind
          and is_active
    );
$$;

revoke all on function public.game_mode_context_valid(text, text) from public, anon;
grant execute on function public.game_mode_context_valid(text, text) to authenticated;

-- 시드: 최초 baseline (클라이언트 최초 오프라인 캐시와 동일, spec §3.1).
insert into public.game_modes (
    id, standing_kind, display_name, play_context_id, sort_order, is_active, season_label
)
values
    ('rank-2026-08', 'rank', '랭크', 'rank_2026_08', 0, true, '26.08'),
    ('rating-2026-08', 'rating', '레이팅', 'rating_2026_08', 1, true, '26.08'),
    ('dc-cup-2026-08', 'event_points', '26.08 DC컵', 'dc_cup_2026_08', 2, true, '26.08'),
    ('wcq-2026', 'event_points', '2026 WCQ', 'wcq_2026', 3, true, '2026')
on conflict (id) do nothing;
