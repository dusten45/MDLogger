-- 0018_game_delete_if_exists.sql
-- P0-1 forward-fix — 등록 games mutation RPC에 "delete-if-exists"를 추가한다.
--
-- 배경: 사용자가 "최초 동기화 전"에 기록을 생성→삭제하면 outbox 압축이 삭제 항목
-- 하나만 남기고, remote_version이 없어(==null) 기존 build_game_change는 이 삭제를
-- create로 잘못 변환해 서버에 살아있는 신규 기록을 만들었다(검토 게이트 R7/R8 §9.3).
--
-- 이전 계약상 delete는 양수 expected_change_version(CAS)과 빈 payload만 허용해,
-- 서버에 존재하지 않는(remote_version 없음) 삭제를 표현할 수 없었다. 이 migration은
-- `expected_change_version`이 없거나 null인 delete를 **delete-if-exists**로 허용한다:
--   - 대상(uuid)이 존재하면 soft delete를 적용하고,
--   - 존재하지 않으면(처음부터 없음 또는 이미 삭제됨) 멱등 성공으로 처리한다.
--     이 경우 기록이 없는 상태이므로 `change_version`은 null로 응답한다.
-- CAS delete(양수 버전 포함)와 update/restore 동작은 그대로 유지한다.
--
-- 전제: 클라이언트 `apply_changes`는 delete의 null change_version applied를
-- 받아들이도록 함께 변경되어야 한다(P0-1, src/mdlogger/remote/games.py).

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
        'turns', 'end_reason', 'score_after', 'note', 'play_context_id',
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
                requested_payload ->> 'environment_version_id',
                change_item ->> 'client_version',
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
            -- update/restore는 항상 양수 CAS 버전이 필요하다. delete는
            -- expected_change_version 없이도 delete-if-exists로 허용한다(P0-1).
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
                set deleted_at = now(), payload_version = 1
                where game_row.id = game_id
                  and game_row.user_id = request_user
                  and (expected_version is null or game_row.change_version = expected_version)
                  and game_row.deleted_at is null
                returning game_row.* into applied_game;
                if applied_game.id is not null then
                    results := results || jsonb_build_array(jsonb_build_object(
                        'id', game_id,
                        'status', 'applied',
                        'change_version', applied_game.change_version
                    ));
                    continue;
                end if;
                if expected_version is null then
                    -- delete-if-exists: 대상이 없거나 이미 삭제된 경우 멱등 성공으로
                    -- 처리한다. 서버에 기록이 없으므로 change_version은 null이다.
                    -- (jsonb_build_object의 null은 JSON null이 되어 `-> 'x' is null`이
                    --  거짓이므로, 키 자체를 생략해 SQL NULL로 응답한다 — pgTAP 05:33·34.)
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
