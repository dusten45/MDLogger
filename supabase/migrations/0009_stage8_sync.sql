-- 0009_stage8_sync.sql
-- 단계 8: 누락 없는 사용자별 change-version cursor, 낙관적 동시성 게임
-- mutation, 장치 등록/heartbeat/ack 계약.
--
-- 등록 게임과 장치의 쓰기는 이 migration부터 검증된 RPC로만 허용한다.
-- guest ingest와 analytics projection 계약은 변경하지 않는다.

-- PostgreSQL sequence는 발급 순서와 transaction commit 순서가 다를 수 있다.
-- 사용자별 단일 clock 행을 transaction 안에서 갱신해 같은 사용자의 version
-- 발급과 commit 가시성 순서를 직렬화한다.
create table public.game_change_cursors (
    user_id uuid primary key references auth.users (id) on delete cascade,
    current_version bigint not null check (current_version >= 0)
);

revoke all on table public.game_change_cursors from public, anon, authenticated;

insert into public.game_change_cursors (user_id, current_version)
select user_id, max(change_version)
from public.games
group by user_id;

create unique index idx_games_user_change_version_unique
    on public.games (user_id, change_version);

create or replace function public.next_game_change_version(target_user uuid)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
    next_version bigint;
begin
    if target_user is null then
        raise exception 'target_user is required' using errcode = '22023';
    end if;

    insert into public.game_change_cursors as cursor_row (user_id, current_version)
    values (target_user, 1)
    on conflict (user_id) do update
    set current_version = cursor_row.current_version + 1
    returning current_version into next_version;

    return next_version;
end;
$$;

revoke all on function public.next_game_change_version(uuid) from public;

-- 기존 서버 관리 필드 보호를 유지하면서 payload v1만 허용하고 transactional
-- clock을 사용한다. 기존 sequence는 forward-fix를 위해 남기되 더는 사용하지 않는다.
create or replace function public.enforce_game_server_fields()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
begin
    if new.payload_version is distinct from 1 then
        raise exception 'unsupported payload_version' using errcode = '22023';
    end if;

    if tg_op = 'INSERT' then
        if request_user is not null then
            new.user_id := request_user;
        end if;
        new.created_at := now();
    else
        new.id := old.id;
        new.user_id := old.user_id;
        new.created_at := old.created_at;
        if new.deleted_at is not null and old.deleted_at is null then
            new.deleted_at := now();
        end if;
    end if;

    new.updated_at := now();
    new.change_version := public.next_game_change_version(new.user_id);
    return new;
end;
$$;

revoke all on function public.enforce_game_server_fields() from public;

-- v1 등록 게임 mutation batch. 유효한 항목은 항목별 applied/conflict 결과를
-- 반환한다. 잘못된 batch/operation/필드는 요청 전체를 22023으로 거부한다.
create or replace function public.apply_game_changes(
    sync_schema_version integer,
    payload_version integer,
    changes jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    allowed_change_keys constant text[] := array[
        'op', 'id', 'expected_change_version', 'payload'
    ];
    allowed_payload_keys constant text[] := array[
        'played_at', 'result', 'turn_order', 'my_deck', 'opp_deck',
        'turns', 'end_reason', 'score_after', 'note', 'play_context_id',
        'standing_kind', 'rank_tier_before', 'rank_tier_after',
        'rank_division_before', 'rank_division_after',
        'rating_before', 'rating_after',
        'event_points_before', 'event_points_after',
        'timezone_offset_minutes'
    ];
    max_batch_size constant integer := 200;
    request_user uuid := (select auth.uid());
    change_item jsonb;
    requested_payload jsonb;
    operation text;
    game_id uuid;
    expected_version bigint;
    disallowed text;
    applied_game public.games%rowtype;
    current_payload jsonb;
    results jsonb := '[]'::jsonb;
begin
    if request_user is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if sync_schema_version is distinct from 1 then
        raise exception 'unsupported sync_schema_version' using errcode = '22023';
    end if;
    if payload_version is distinct from 1 then
        raise exception 'unsupported payload_version' using errcode = '22023';
    end if;
    if changes is null or jsonb_typeof(changes) <> 'array' then
        raise exception 'changes must be a JSON array' using errcode = '22023';
    end if;
    if jsonb_array_length(changes) < 1
        or jsonb_array_length(changes) > max_batch_size then
        raise exception 'batch size must be between 1 and %', max_batch_size
            using errcode = '22023';
    end if;

    for change_item in select * from jsonb_array_elements(changes)
    loop
        if jsonb_typeof(change_item) <> 'object' then
            raise exception 'change item must be an object' using errcode = '22023';
        end if;

        select key into disallowed
        from jsonb_object_keys(change_item) as item_key(key)
        where key <> all (allowed_change_keys)
        limit 1;
        if disallowed is not null then
            raise exception 'disallowed change field: %', disallowed
                using errcode = '22023';
        end if;

        operation := change_item ->> 'op';
        if operation not in ('create', 'update', 'delete', 'restore') then
            raise exception 'unsupported game operation' using errcode = '22023';
        end if;

        begin
            game_id := (change_item ->> 'id')::uuid;
        exception when invalid_text_representation then
            raise exception 'invalid game id' using errcode = '22023';
        end;
        if game_id is null then
            raise exception 'game id is required' using errcode = '22023';
        end if;

        requested_payload := coalesce(change_item -> 'payload', '{}'::jsonb);
        if jsonb_typeof(requested_payload) <> 'object' then
            raise exception 'payload must be an object' using errcode = '22023';
        end if;

        select key into disallowed
        from jsonb_object_keys(requested_payload) as payload_key(key)
        where key <> all (allowed_payload_keys)
        limit 1;
        if disallowed is not null then
            raise exception 'disallowed game payload field: %', disallowed
                using errcode = '22023';
        end if;

        if operation = 'create' then
            if change_item ? 'expected_change_version'
                and change_item -> 'expected_change_version' <> 'null'::jsonb then
                raise exception 'create must not include expected_change_version'
                    using errcode = '22023';
            end if;
            if not (requested_payload ? 'played_at')
                or not (requested_payload ? 'result')
                or not (requested_payload ? 'turn_order') then
                raise exception 'create requires played_at, result, and turn_order'
                    using errcode = '22023';
            end if;

            -- 같은 UUID의 응답 유실 재전송과 동시 create를 직렬화한다.
            -- 존재 확인 뒤에만 INSERT를 실행해 BEFORE INSERT trigger가 실제 변경 없이
            -- change cursor를 증가시키지 않게 한다.
            perform pg_advisory_xact_lock(hashtextextended(game_id::text, 0));
            applied_game := null;
            if not exists (
                select 1 from public.games as existing_game
                where existing_game.id = game_id
            ) then
                insert into public.games (
                id, user_id, played_at, result, turn_order,
                my_deck, opp_deck, turns, end_reason, score_after, note,
                play_context_id, standing_kind,
                rank_tier_before, rank_tier_after,
                rank_division_before, rank_division_after,
                rating_before, rating_after,
                event_points_before, event_points_after,
                timezone_offset_minutes, payload_version, source_kind
            )
            values (
                game_id, request_user,
                requested_payload ->> 'played_at',
                requested_payload ->> 'result',
                requested_payload ->> 'turn_order',
                requested_payload ->> 'my_deck',
                requested_payload ->> 'opp_deck',
                (requested_payload ->> 'turns')::integer,
                requested_payload ->> 'end_reason',
                (requested_payload ->> 'score_after')::integer,
                requested_payload ->> 'note',
                requested_payload ->> 'play_context_id',
                requested_payload ->> 'standing_kind',
                requested_payload ->> 'rank_tier_before',
                requested_payload ->> 'rank_tier_after',
                (requested_payload ->> 'rank_division_before')::integer,
                (requested_payload ->> 'rank_division_after')::integer,
                (requested_payload ->> 'rating_before')::integer,
                (requested_payload ->> 'rating_after')::integer,
                (requested_payload ->> 'event_points_before')::integer,
                (requested_payload ->> 'event_points_after')::integer,
                (requested_payload ->> 'timezone_offset_minutes')::integer,
                1, 'native'
            )
                on conflict (id) do nothing
                returning * into applied_game;
            end if;

            if applied_game.id is not null then
                results := results || jsonb_build_array(jsonb_build_object(
                    'id', game_id,
                    'status', 'applied',
                    'change_version', applied_game.change_version
                ));
                continue;
            end if;
        else
            begin
                expected_version := (change_item ->> 'expected_change_version')::bigint;
            exception when invalid_text_representation or numeric_value_out_of_range then
                raise exception 'invalid expected_change_version'
                    using errcode = '22023';
            end;
            if expected_version is null or expected_version < 1 then
                raise exception 'positive expected_change_version is required'
                    using errcode = '22023';
            end if;

            applied_game := null;
            if operation = 'delete' then
                if requested_payload <> '{}'::jsonb then
                    raise exception 'delete payload must be empty'
                        using errcode = '22023';
                end if;
                update public.games as game_row
                set deleted_at = now(), payload_version = 1
                where game_row.id = game_id
                  and game_row.user_id = request_user
                  and game_row.change_version = expected_version
                  and game_row.deleted_at is null
                returning game_row.* into applied_game;
            else
                update public.games as game_row
                set played_at = case
                        when requested_payload ? 'played_at'
                        then requested_payload ->> 'played_at'
                        else game_row.played_at end,
                    result = case
                        when requested_payload ? 'result'
                        then requested_payload ->> 'result'
                        else game_row.result end,
                    turn_order = case
                        when requested_payload ? 'turn_order'
                        then requested_payload ->> 'turn_order'
                        else game_row.turn_order end,
                    my_deck = case
                        when requested_payload ? 'my_deck'
                        then requested_payload ->> 'my_deck'
                        else game_row.my_deck end,
                    opp_deck = case
                        when requested_payload ? 'opp_deck'
                        then requested_payload ->> 'opp_deck'
                        else game_row.opp_deck end,
                    turns = case
                        when requested_payload ? 'turns'
                        then (requested_payload ->> 'turns')::integer
                        else game_row.turns end,
                    end_reason = case
                        when requested_payload ? 'end_reason'
                        then requested_payload ->> 'end_reason'
                        else game_row.end_reason end,
                    score_after = case
                        when requested_payload ? 'score_after'
                        then (requested_payload ->> 'score_after')::integer
                        else game_row.score_after end,
                    note = case
                        when requested_payload ? 'note'
                        then requested_payload ->> 'note'
                        else game_row.note end,
                    play_context_id = case
                        when requested_payload ? 'play_context_id'
                        then requested_payload ->> 'play_context_id'
                        else game_row.play_context_id end,
                    standing_kind = case
                        when requested_payload ? 'standing_kind'
                        then requested_payload ->> 'standing_kind'
                        else game_row.standing_kind end,
                    rank_tier_before = case
                        when requested_payload ? 'rank_tier_before'
                        then requested_payload ->> 'rank_tier_before'
                        else game_row.rank_tier_before end,
                    rank_tier_after = case
                        when requested_payload ? 'rank_tier_after'
                        then requested_payload ->> 'rank_tier_after'
                        else game_row.rank_tier_after end,
                    rank_division_before = case
                        when requested_payload ? 'rank_division_before'
                        then (requested_payload ->> 'rank_division_before')::integer
                        else game_row.rank_division_before end,
                    rank_division_after = case
                        when requested_payload ? 'rank_division_after'
                        then (requested_payload ->> 'rank_division_after')::integer
                        else game_row.rank_division_after end,
                    rating_before = case
                        when requested_payload ? 'rating_before'
                        then (requested_payload ->> 'rating_before')::integer
                        else game_row.rating_before end,
                    rating_after = case
                        when requested_payload ? 'rating_after'
                        then (requested_payload ->> 'rating_after')::integer
                        else game_row.rating_after end,
                    event_points_before = case
                        when requested_payload ? 'event_points_before'
                        then (requested_payload ->> 'event_points_before')::integer
                        else game_row.event_points_before end,
                    event_points_after = case
                        when requested_payload ? 'event_points_after'
                        then (requested_payload ->> 'event_points_after')::integer
                        else game_row.event_points_after end,
                    timezone_offset_minutes = case
                        when requested_payload ? 'timezone_offset_minutes'
                        then (requested_payload ->> 'timezone_offset_minutes')::integer
                        else game_row.timezone_offset_minutes end,
                    deleted_at = case
                        when operation = 'restore' then null
                        else game_row.deleted_at end,
                    payload_version = 1
                where game_row.id = game_id
                  and game_row.user_id = request_user
                  and game_row.change_version = expected_version
                  and ((operation = 'update' and game_row.deleted_at is null)
                       or (operation = 'restore' and game_row.deleted_at is not null))
                returning game_row.* into applied_game;
            end if;

            if applied_game.id is not null then
                results := results || jsonb_build_array(jsonb_build_object(
                    'id', game_id,
                    'status', 'applied',
                    'change_version', applied_game.change_version
                ));
                continue;
            end if;
        end if;

        select to_jsonb(game_row) - 'user_id'
        into current_payload
        from public.games as game_row
        where game_row.id = game_id
          and game_row.user_id = request_user;

        results := results || jsonb_build_array(jsonb_build_object(
            'id', game_id,
            'status', 'conflict',
            'expected_change_version', case
                when operation = 'create' then null
                else expected_version end,
            'current_change_version', case
                when current_payload is null then null
                else (current_payload ->> 'change_version')::bigint end,
            'remote', current_payload
        ));
    end loop;

    return jsonb_build_object('results', results);
exception
    when check_violation or invalid_text_representation
        or numeric_value_out_of_range or not_null_violation then
        raise exception 'invalid game payload' using errcode = '22023';
end;
$$;

revoke all on function public.apply_game_changes(integer, integer, jsonb)
    from public, anon;
grant execute on function public.apply_game_changes(integer, integer, jsonb)
    to authenticated;

-- 장치가 실제 사용한 sync/payload 계약을 진단할 수 있게 보존한다.
alter table public.devices
    add column sync_schema_version integer not null default 1
        check (sync_schema_version = 1),
    add column payload_version integer not null default 1
        check (payload_version = 1);

create or replace function public.enforce_device_server_fields()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
begin
    if new.sync_schema_version is distinct from 1 then
        raise exception 'unsupported sync_schema_version' using errcode = '22023';
    end if;
    if new.payload_version is distinct from 1 then
        raise exception 'unsupported payload_version' using errcode = '22023';
    end if;

    if tg_op = 'INSERT' then
        if request_user is not null then
            new.user_id := request_user;
        end if;
        new.created_at := now();
    else
        new.id := old.id;
        new.user_id := old.user_id;
        new.installation_id := old.installation_id;
        new.created_at := old.created_at;
    end if;
    new.last_seen_at := now();
    return new;
end;
$$;

revoke all on function public.enforce_device_server_fields() from public;

create or replace function public.register_or_touch_device(
    sync_schema_version integer,
    payload_version integer,
    installation_id uuid,
    display_name text,
    client_version text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
    device_payload jsonb;
begin
    if request_user is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if sync_schema_version is distinct from 1 then
        raise exception 'unsupported sync_schema_version' using errcode = '22023';
    end if;
    if payload_version is distinct from 1 then
        raise exception 'unsupported payload_version' using errcode = '22023';
    end if;
    if installation_id is null then
        raise exception 'installation_id is required' using errcode = '22023';
    end if;
    if client_version is null or btrim(client_version) = '' then
        raise exception 'client_version is required' using errcode = '22023';
    end if;

    insert into public.devices as device_row (
        id, user_id, installation_id, display_name, client_version,
        sync_schema_version, payload_version
    )
    values (
        extensions.gen_random_uuid(), request_user,
        register_or_touch_device.installation_id,
        register_or_touch_device.display_name,
        register_or_touch_device.client_version, 1, 1
    )
    on conflict on constraint devices_user_id_installation_id_key do update
    set display_name = excluded.display_name,
        client_version = excluded.client_version,
        sync_schema_version = excluded.sync_schema_version,
        payload_version = excluded.payload_version
    returning to_jsonb(device_row) - 'user_id' into device_payload;

    return device_payload;
end;
$$;

revoke all on function public.register_or_touch_device(
    integer, integer, uuid, text, text
) from public, anon;
grant execute on function public.register_or_touch_device(
    integer, integer, uuid, text, text
) to authenticated;

create or replace function public.acknowledge_device_version(
    sync_schema_version integer,
    payload_version integer,
    installation_id uuid,
    acknowledged_version bigint
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
    server_version bigint;
    current_ack bigint;
    device_payload jsonb;
begin
    if request_user is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if sync_schema_version is distinct from 1 then
        raise exception 'unsupported sync_schema_version' using errcode = '22023';
    end if;
    if payload_version is distinct from 1 then
        raise exception 'unsupported payload_version' using errcode = '22023';
    end if;
    if installation_id is null then
        raise exception 'installation_id is required' using errcode = '22023';
    end if;
    if acknowledged_version is null or acknowledged_version < 0 then
        raise exception 'acknowledged_version must be non-negative'
            using errcode = '22023';
    end if;

    select coalesce((
        select cursor_row.current_version
        from public.game_change_cursors as cursor_row
        where cursor_row.user_id = request_user
    ), 0) into server_version;

    if acknowledged_version > server_version then
        raise exception 'acknowledged_version exceeds server version'
            using errcode = '22023';
    end if;

    update public.devices as device_row
    set last_acknowledged_version = acknowledged_version
    where device_row.user_id = request_user
      and device_row.installation_id = acknowledge_device_version.installation_id
      and device_row.last_acknowledged_version <= acknowledged_version
    returning to_jsonb(device_row) - 'user_id' into device_payload;

    if device_payload is not null then
        return device_payload;
    end if;

    select device_row.last_acknowledged_version
    into current_ack
    from public.devices as device_row
    where device_row.user_id = request_user
      and device_row.installation_id = acknowledge_device_version.installation_id;

    if current_ack is null then
        raise exception 'device is not registered' using errcode = '22023';
    end if;

    raise exception 'acknowledged_version cannot decrease' using errcode = '22023';
end;
$$;

revoke all on function public.acknowledge_device_version(
    integer, integer, uuid, bigint
) from public, anon;
grant execute on function public.acknowledge_device_version(
    integer, integer, uuid, bigint
) to authenticated;

-- 모든 등록 쓰기를 검증된 RPC 경계로 강제한다. SELECT RLS는 그대로 유지한다.
revoke insert, update on table public.games from authenticated;
revoke insert, update on table public.devices from authenticated;
