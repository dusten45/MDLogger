-- 웹 읽기는 RLS를 우회하지 않는다. 모든 결과 묶음은 단일 읽기 snapshot에서 계산한다.
create index idx_games_history on public.games(user_id, played_at desc, id desc)
    where deleted_at is null;
create index idx_games_mode_history
    on public.games(user_id, play_context_id, standing_kind, played_at desc, id desc)
    where deleted_at is null;

create function public.get_record_state(p_local_date text)
returns jsonb language plpgsql stable security invoker set search_path = ''
as $$
begin
    if auth.uid() is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if p_local_date is null or p_local_date !~ '^\d{4}-\d{2}-\d{2}$' then
        raise exception 'invalid local date' using errcode = '22023';
    end if;
    return (
        with owned as materialized (
            select * from public.games where user_id = auth.uid()
        ), live as (
            select * from owned where deleted_at is null
        ), latest as (
            select distinct on (play_context_id, standing_kind) * from live
            where (standing_kind = 'event_points' and event_points_after is not null)
               or (standing_kind = 'rating' and rating_after is not null)
               or (standing_kind = 'rank' and rank_tier_after is not null and rank_division_after is not null)
            order by play_context_id, standing_kind, played_at desc, id desc
        )
        select jsonb_build_object(
            'snapshot_version', (select coalesce(max(change_version), 0) from owned),
            'today', (select jsonb_build_object(
                'wins', count(*) filter (where result = 'win'),
                'losses', count(*) filter (where result = 'lose')
            ) from live where left(played_at, 10) = p_local_date),
            'last_game', (select to_jsonb(g) - 'user_id' from live g order by played_at desc, id desc limit 1),
            'last_my_deck', (select my_deck from live where coalesce(my_deck, '') <> '' order by played_at desc, id desc limit 1),
            'latest_by_mode', (select coalesce(jsonb_agg(to_jsonb(g) - 'user_id'), '[]'::jsonb) from latest g)
        )
    );
end;
$$;

create function public.get_game_statistics(p_context text default null)
returns jsonb language plpgsql stable security invoker set search_path = ''
as $$
begin
    if auth.uid() is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    return (
        with owned as materialized (
            select * from public.games where user_id = auth.uid()
        ), live as materialized (
            select * from owned where deleted_at is null
                and (p_context is null or play_context_id = p_context)
        ), counts as (
            select count(*) as total, count(*) filter (where result = 'win') as wins,
                count(*) filter (where turn_order = 'first') as first_games,
                count(*) filter (where turn_order = 'first' and result = 'win') as first_wins,
                count(*) filter (where turn_order = 'second') as second_games,
                count(*) filter (where turn_order = 'second' and result = 'win') as second_wins,
                coalesce(avg(turns), 0) as avg_turns from live
        ), matchups as (
            select coalesce(opp_deck, '') as deck, count(*) as games,
                count(*) filter (where result = 'win') as wins,
                count(*) filter (where result = 'lose') as losses,
                100.0 * count(*) filter (where result = 'win') / count(*) as winrate
            from live group by coalesce(opp_deck, '')
        )
        select jsonb_build_object(
            'snapshot_version', (select coalesce(max(change_version), 0) from owned),
            'summary', (select to_jsonb(c) || jsonb_build_object(
                'losses', total - wins, 'winrate', coalesce(100.0 * wins / nullif(total, 0), 0),
                'first_winrate', coalesce(100.0 * first_wins / nullif(first_games, 0), 0),
                'second_winrate', coalesce(100.0 * second_wins / nullif(second_games, 0), 0)
            ) from counts c),
            'matchups', (select coalesce(jsonb_agg(to_jsonb(m) order by games desc, deck), '[]'::jsonb) from matchups m),
            -- 상세 기록/메모 대신 차트에 필요한 값만 반환한다. 전체 통계를 잘라내지 않는다.
            'series', (select coalesce(jsonb_agg(jsonb_build_object(
                'played_at', played_at, 'standing_kind', standing_kind,
                'value', case when standing_kind = 'event_points' then event_points_after else rating_after end,
                'tier', rank_tier_after, 'division', rank_division_after
            ) order by played_at, id), '[]'::jsonb) from live where p_context is not null
                and ((standing_kind = 'event_points' and event_points_after is not null)
                    or (standing_kind = 'rating' and rating_after is not null)
                    or (standing_kind = 'rank' and rank_tier_after is not null)))
        )
    );
end;
$$;

create function public.list_game_history(
    p_context text default null, p_before_played_at text default null,
    p_before_id uuid default null, p_limit integer default 100,
    p_snapshot_version bigint default null
)
returns jsonb language plpgsql stable security invoker set search_path = ''
as $$
begin
    if auth.uid() is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if p_limit is null or p_limit not between 1 and 200
        or (p_before_played_at is null) <> (p_before_id is null)
        or (p_before_played_at is not null and p_before_played_at !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$') then
        raise exception 'invalid history cursor or limit' using errcode = '22023';
    end if;
    return (
        with version as (
            select coalesce(max(change_version), 0) as value from public.games where user_id = auth.uid()
        ), candidates as materialized (
            select * from public.games
            where user_id = auth.uid() and deleted_at is null
                and (p_context is null or play_context_id = p_context)
                and (p_before_id is null or (played_at, id) < (p_before_played_at, p_before_id))
            order by played_at desc, id desc limit p_limit + 1
        ), page as (
            select * from candidates order by played_at desc, id desc limit p_limit
        )
        select case when p_snapshot_version is not null and p_snapshot_version <> version.value then
            jsonb_build_object('stale', true, 'snapshot_version', version.value,
                'games', '[]'::jsonb, 'has_more', false, 'next_cursor', null)
        else jsonb_build_object(
            'stale', false, 'snapshot_version', version.value,
            'games', (select coalesce(jsonb_agg(to_jsonb(g) - 'user_id' order by played_at desc, id desc), '[]'::jsonb) from page g),
            'has_more', (select count(*) > p_limit from candidates),
            'next_cursor', (select jsonb_build_object('played_at', played_at, 'id', id)
                from page order by played_at, id limit 1)
        ) end from version
    );
end;
$$;

revoke all on function public.get_record_state(text) from public, anon;
revoke all on function public.get_game_statistics(text) from public, anon;
revoke all on function public.list_game_history(text, text, uuid, integer, bigint) from public, anon;
grant execute on function public.get_record_state(text) to authenticated;
grant execute on function public.get_game_statistics(text) to authenticated;
grant execute on function public.list_game_history(text, text, uuid, integer, bigint) to authenticated;
notify pgrst, 'reload schema';
