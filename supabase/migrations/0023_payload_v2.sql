-- 0023_payload_v2.sql
-- 1단계 payload v2 (spec §4.1, §4.7, §3.3, §4.9).
--
-- - apply_game_changes: payload_version=2만 허용, score_after 제거,
--   play_context_id 문맥(서버 game_modes 존재·활성) 검증.
-- - games.score_after 컬럼 완전 삭제 (정책 B-a', 레거시 없음).
-- - 장치 RPC/트리거도 payload_version=2 허용.
-- - release_policies: v0.2.0, payload_version 2, sync_schema_version 1.

-- games.score_after 컬럼 완전 삭제 (레거시 없음, spec §3.3).
alter table public.games drop column if exists score_after;

-- 장치 RPC/트리거 payload_version 검증을 v2로 올린다.
-- 기존 테스트 장치 행을 v2로 승격한다(레거시 없음, spec §1.1). 실제 사용자가
-- 없으므로 기존 행은 모두 테스트 데이터다.
-- 구버전 트리거와 제약조건(payload_version=1)이 승격 UPDATE를 막으므로,
-- 트리거 비활성화 → 구 제약조건 제거 → 승격 → v2 제약조건 추가 순서로 진행한다.
alter table public.devices disable trigger devices_enforce_server_fields;
alter table public.devices drop constraint if exists devices_payload_version_check;
update public.devices set payload_version = 2 where payload_version <> 2;
alter table public.devices add constraint devices_payload_version_check
    check (payload_version = 2);

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
    if new.payload_version is distinct from 2 then
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

-- 트리거를 v2 함수로 다시 활성화한다.
alter table public.devices enable trigger devices_enforce_server_fields;

-- 등록 games 서버 관리 필드를 강제하고 payload v2만 허용한다. 기존 0009/0013의
-- 게임 트리거는 payload v1 단일 전제였으므로 v2 계약으로 대체한다(B-a', spec §4.7).
-- `games_enforce_server_fields` 트리거는 그대로 두고 함수만 재정의한다.
create or replace function public.enforce_game_server_fields()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_user uuid := (select auth.uid());
begin
    if new.payload_version is distinct from 2 then
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

revoke all on function public.enforce_game_server_fields()
    from public, anon, authenticated;

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
    if payload_version is distinct from 2 then
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
        gen_random_uuid(), request_user,
        register_or_touch_device.installation_id,
        register_or_touch_device.display_name,
        register_or_touch_device.client_version,
        sync_schema_version, payload_version
    )
    on conflict on constraint devices_user_id_installation_id_key do update set
        display_name = excluded.display_name,
        client_version = excluded.client_version,
        last_seen_at = now(),
        sync_schema_version = excluded.sync_schema_version,
        payload_version = excluded.payload_version
    returning to_jsonb(device_row) - 'user_id' into device_payload;
    return device_payload;
end;
$$;

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
    current_ack bigint;
    device_payload jsonb;
begin
    if request_user is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if sync_schema_version is distinct from 1 then
        raise exception 'unsupported sync_schema_version' using errcode = '22023';
    end if;
    if payload_version is distinct from 2 then
        raise exception 'unsupported payload_version' using errcode = '22023';
    end if;
    if installation_id is null then
        raise exception 'installation_id is required' using errcode = '22023';
    end if;
    if acknowledged_version is null or acknowledged_version < 0 then
        raise exception 'acknowledged_version must be non-negative'
            using errcode = '22023';
    end if;
    if acknowledged_version > coalesce((
        select cursor_row.current_version
        from public.game_change_cursors as cursor_row
        where cursor_row.user_id = request_user
    ), 0) then
        raise exception 'acknowledged_version exceeds server version'
            using errcode = '22023';
    end if;

    update public.devices as device_row
    set last_acknowledged_version = acknowledged_version,
        last_seen_at = now()
    where device_row.user_id = request_user
      and device_row.installation_id = acknowledge_device_version.installation_id
      and device_row.last_acknowledged_version <= acknowledged_version
    returning to_jsonb(device_row) - 'user_id' into device_payload;
    if device_payload is not null then
        return device_payload;
    end if;

    select device_row.last_acknowledged_version into current_ack
    from public.devices as device_row
    where device_row.user_id = request_user
      and device_row.installation_id = acknowledge_device_version.installation_id;

    if current_ack is null then
        raise exception 'device is not registered' using errcode = '22023';
    end if;
    raise exception 'acknowledged_version cannot decrease' using errcode = '22023';
end;
$$;

-- v2 등록 게임 mutation batch (spec §4.7).
-- payload_version=2만 허용, score_after 제거, play_context_id 문맥 검증.
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
        'op', 'id', 'expected_change_version', 'payload', 'client_version'
    ];
    allowed_payload_keys constant text[] := array[
        'played_at', 'result', 'turn_order', 'my_deck', 'opp_deck',
        'turns', 'end_reason', 'note', 'play_context_id',
        'standing_kind', 'rank_tier_before', 'rank_tier_after',
        'rank_division_before', 'rank_division_after',
        'rating_before', 'rating_after',
        'event_points_before', 'event_points_after',
        'timezone_offset_minutes', 'environment_version_id'
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
    if payload_version is distinct from 2 then
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
            -- 모드 필수 (spec §2.5-7): standing_kind와 play_context_id 둘 다 필요.
            if not (requested_payload ? 'standing_kind')
               or requested_payload ->> 'standing_kind' is null then
                raise exception 'create requires standing_kind'
                    using errcode = '22023';
            end if;
            if not (requested_payload ? 'play_context_id')
               or requested_payload ->> 'play_context_id' is null then
                raise exception 'create requires play_context_id'
                    using errcode = '22023';
            end if;
            -- 문맥이 존재·활성·kind 일치인지 검증 (spec §4.7).
            if not public.game_mode_context_valid(
                requested_payload ->> 'play_context_id',
                requested_payload ->> 'standing_kind'
            ) then
                raise exception 'unknown, inactive, or mismatched play_context_id'
                    using errcode = '22023';
            end if;

            perform pg_advisory_xact_lock(hashtextextended(game_id::text, 0));
            applied_game := null;
            if not exists (
                select 1 from public.games as existing_game
                where existing_game.id = game_id
            ) then
                insert into public.games (
                id, user_id, played_at, result, turn_order,
                my_deck, opp_deck, turns, end_reason, note,
                play_context_id, standing_kind,
                rank_tier_before, rank_tier_after,
                rank_division_before, rank_division_after,
                rating_before, rating_after,
                event_points_before, event_points_after,
                timezone_offset_minutes, environment_version_id, client_version,
                payload_version, source_kind
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
                requested_payload ->> 'environment_version_id',
                change_item ->> 'client_version',
                2, 'native'
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
            -- update/restore는 항상 양수 CAS 버전이 필요하다. delete는
            -- expected_change_version 없이도 delete-if-exists로 허용한다(P0-1,
            -- 0018 계약 유지).
            if operation <> 'delete'
                or (change_item ? 'expected_change_version'
                    and change_item -> 'expected_change_version' <> 'null'::jsonb) then
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
            end if;

            applied_game := null;
            if operation = 'delete' then
                if requested_payload <> '{}'::jsonb then
                    raise exception 'delete payload must be empty'
                        using errcode = '22023';
                end if;
                update public.games as game_row
                set deleted_at = now(), payload_version = 2
                where game_row.id = game_id
                  and game_row.user_id = request_user
                  and (expected_version is null or game_row.change_version = expected_version)
                  and game_row.deleted_at is null
                returning game_row.* into applied_game;
                if applied_game.id is null and expected_version is null then
                    -- delete-if-exists: 대상이 없거나 이미 삭제된 경우 멱등 성공.
                    results := results || jsonb_build_array(jsonb_build_object(
                        'id', game_id,
                        'status', 'applied'
                    ));
                    continue;
                end if;
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
                    environment_version_id = case
                        when requested_payload ? 'environment_version_id'
                        then requested_payload ->> 'environment_version_id'
                        else game_row.environment_version_id end,
                    client_version = case
                        when change_item ? 'client_version'
                        then change_item ->> 'client_version'
                        else game_row.client_version end,
                    deleted_at = case
                        when operation = 'restore' then null
                        else game_row.deleted_at end,
                    payload_version = 2
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

-- 릴리스 정책 v2 (spec §4.9): v0.2.0, payload_version 2, sync_schema_version 1.
update public.release_policies
set latest_version = '0.2.0',
    minimum_supported_version = '0.2.0',
    payload_version_min = 2,
    payload_version_max = 2,
    sync_schema_version_min = 1,
    sync_schema_version_max = 1,
    effective_at = now()
where platform in ('windows', 'macos', 'linux');
