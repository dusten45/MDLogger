-- 0013_environment_version.sql
-- 하드닝 H4 — 환경 버전 최소 도입(결정 H-2), 로드맵 §7.5/L2.6.
--
-- - `public.environment_versions` 기준정보(불변 id, 표시 이름, effective 기간).
--   RLS 활성 + 읽기 전용(anon/authenticated SELECT). production 값은 소유자.
-- - `public.games.environment_version_id` 추가 + 기준정보 FK(미등록 환경 차단).
-- - `public.games.client_version` 추가(등록 관측치의 진단용, 로드맵 7.4).
-- - 등록 projection INSERT/SET에 `environment_version_id`·`client_version` 추가
--   (0005:137-159에서 누락이었다, M2 근거).
-- - guest ingest가 미등록 `environment_version_id`를 거부한다.
-- - 기존 행의 환경은 추측하지 않고 NULL로 유지한다(로드맵 7.6).

-- ============================================================================
-- 1) 기준정보 테이블 + RLS + 시드
-- ============================================================================

create table public.environment_versions (
    id text primary key,
    display_name text,
    effective_from timestamptz not null,
    effective_to timestamptz,
    -- 끝이 난(과거) 환경을 클라이언트가 현재로 잘못 선택하지 않도록 검사.
    constraint environment_version_period check (
        effective_to is null or effective_to >= effective_from
    )
);

comment on table public.environment_versions is
    '월별 게임 환경 기준정보. 불변 id, 읽기 전용 공개 조회.';

alter table public.environment_versions enable row level security;
revoke all on table public.environment_versions from anon, authenticated;
grant select on table public.environment_versions to anon, authenticated;

create policy environment_versions_select_public
    on public.environment_versions
    for select
    to anon, authenticated
    using (true);

-- 로컬 개발용 시드(결정 D-8 명명 규칙: md-YYYY-MM). production 값은 소유자.
insert into public.environment_versions (id, display_name, effective_from, effective_to)
values (
    'md-2026-08',
    '2026년 8월 WCQ 환경',
    '2026-08-01 00:00:00+09',
    '2026-09-01 00:00:00+09'
);

-- ============================================================================
-- 2) games 에 환경/버전 컬럼 추가
-- ============================================================================

alter table public.games
    add column environment_version_id text,
    add column client_version text;

alter table public.games
    add constraint fk_games_environment_version
    foreign key (environment_version_id)
    references public.environment_versions (id);

-- ============================================================================
-- 3) 등록 games mutation RPC(batch)에 환경/버전 필드 배선
--    기존 0009의 apply_game_changes 본문에 다음을 추가한다:
--      - change envelope `client_version` 허용(단일 버전 출처, N-1)
--      - payload `environment_version_id` 허용
--      - create/update 양쪽에서 저장
-- ============================================================================

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

-- ============================================================================
-- 4) 등록 projection에 환경·버전 컬럼 배선(M3 가드 유지, 0011)
--    출처가 게스트/철회된 행의 withdrawn_at은 절대 지우지 않는다.
-- ============================================================================

create or replace function analytics.project_registered_game()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.deleted_at is not null then
        update analytics.duel_observations
        set withdrawn_at = coalesce(withdrawn_at, now()),
            withdrawal_source = coalesce(withdrawal_source, 'registered')
        where source_game_id = new.id;
        return null;
    end if;

    insert into analytics.duel_observations (
        source_game_id,
        contributor_key,
        played_at_local,
        result,
        turn_order,
        my_deck,
        opp_deck,
        turns,
        end_reason,
        play_context_id,
        standing_kind,
        rank_tier_before,
        rank_tier_after,
        rank_division_before,
        rank_division_after,
        rating_before,
        rating_after,
        event_points_before,
        event_points_after,
        environment_version_id,
        client_version,
        payload_version,
        source_kind,
        quality_flags
    )
    values (
        new.id,
        analytics.pseudonym_for(new.user_id::text),
        new.played_at,
        new.result,
        new.turn_order,
        new.my_deck,
        new.opp_deck,
        new.turns,
        new.end_reason,
        new.play_context_id,
        new.standing_kind,
        new.rank_tier_before,
        new.rank_tier_after,
        new.rank_division_before,
        new.rank_division_after,
        new.rating_before,
        new.rating_after,
        new.event_points_before,
        new.event_points_after,
        new.environment_version_id,
        new.client_version,
        new.payload_version,
        case when new.source_kind = 'native' then 'registered'
             else new.source_kind end,
        case when new.source_kind = 'import' then array['import']
             else '{}'::text[] end
    )
    on conflict (source_game_id) do update set
        played_at_local = excluded.played_at_local,
        result = excluded.result,
        turn_order = excluded.turn_order,
        my_deck = excluded.my_deck,
        opp_deck = excluded.opp_deck,
        turns = excluded.turns,
        end_reason = excluded.end_reason,
        play_context_id = excluded.play_context_id,
        standing_kind = excluded.standing_kind,
        rank_tier_before = excluded.rank_tier_before,
        rank_tier_after = excluded.rank_tier_after,
        rank_division_before = excluded.rank_division_before,
        rank_division_after = excluded.rank_division_after,
        rating_before = excluded.rating_before,
        rating_after = excluded.rating_after,
        event_points_before = excluded.event_points_before,
        event_points_after = excluded.event_points_after,
        environment_version_id = excluded.environment_version_id,
        client_version = excluded.client_version,
        payload_version = excluded.payload_version;
        -- M3 가드: `withdrawn_at`/`withdrawal_source`는 SET 하지 않는다.
    return null;
end;
$$;

revoke all on function analytics.project_registered_game() from public;

-- ============================================================================
-- 5) guest ingest가 미등록 environment_version_id를 거부한다(0008 재생성)
-- ============================================================================

create or replace function analytics.ingest_guest_batch(
    batch_id uuid,
    installation_id uuid,
    client_version text,
    payload_version integer,
    observations jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    allowed_keys constant text[] := array[
        'op', 'sync_id', 'played_at_local', 'timezone_offset_minutes',
        'result', 'turn_order', 'my_deck', 'opp_deck', 'turns', 'end_reason',
        'play_context_id', 'standing_kind',
        'rank_tier_before', 'rank_tier_after',
        'rank_division_before', 'rank_division_after',
        'rating_before', 'rating_after',
        'event_points_before', 'event_points_after',
        'event_id', 'event_stage_id',
        'environment_version_id', 'deck_catalog_version_id'
    ];
    max_batch_size constant integer := 200;
    installation_key text;
    existing analytics.ingestion_batches%rowtype;
    observation jsonb;
    op text;
    sync_id uuid;
    disallowed text;
    reject_reason text;
    accepted integer := 0;
    skipped integer := 0;
    rejected integer := 0;
    inserted_game uuid;
begin
    if batch_id is null or installation_id is null then
        raise exception 'batch_id and installation_id are required'
            using errcode = '22023';
    end if;
    if payload_version is distinct from 1 then
        raise exception 'unsupported payload_version'
            using errcode = '22023';
    end if;
    if observations is null or jsonb_typeof(observations) <> 'array' then
        raise exception 'observations must be a JSON array'
            using errcode = '22023';
    end if;
    if jsonb_array_length(observations) < 1
        or jsonb_array_length(observations) > max_batch_size then
        raise exception 'batch size must be between 1 and %', max_batch_size
            using errcode = '22023';
    end if;

    select * into existing
    from analytics.ingestion_batches b
    where b.batch_id = ingest_guest_batch.batch_id;
    if found then
        return jsonb_build_object(
            'batch_id', existing.batch_id,
            'accepted', existing.accepted_count,
            'skipped', existing.skipped_count,
            'rejected', existing.rejected_count,
            'replayed', true
        );
    end if;

    installation_key := analytics.pseudonym_for(installation_id::text);

    for observation in select * from jsonb_array_elements(observations)
    loop
        reject_reason := null;
        sync_id := null;

        if jsonb_typeof(observation) <> 'object' then
            reject_reason := 'observation_not_object';
        else
            select key into disallowed
            from jsonb_object_keys(observation) as t(key)
            where key <> all (allowed_keys)
            limit 1;
            if disallowed is not null then
                reject_reason := 'disallowed_field:' || disallowed;
            end if;
        end if;

        if reject_reason is null then
            begin
                sync_id := (observation ->> 'sync_id')::uuid;
            exception when others then
                reject_reason := 'invalid_sync_id';
            end;
        end if;

        -- 하드닝 H4: 미등록 환경 version 식별자는 분석 dataset 탐지를 막는다.
        if reject_reason is null and observation ? 'environment_version_id' then
            if not exists (
                select 1 from public.environment_versions as environment_row
                where environment_row.id = observation ->> 'environment_version_id'
            ) then
                reject_reason := 'unregistered_environment_version';
            end if;
        end if;

        if reject_reason is null then
            op := coalesce(observation ->> 'op', 'create');
            if op = 'withdraw' then
                update analytics.duel_observations
                set withdrawn_at = coalesce(withdrawn_at, now()),
                    withdrawal_source = coalesce(withdrawal_source, 'guest')
                where source_game_id = sync_id
                  and source_kind = 'guest';
                if found then
                    accepted := accepted + 1;
                else
                    skipped := skipped + 1;
                end if;
                continue;
            elsif op not in ('create', 'upsert') then
                reject_reason := 'invalid_op';
            end if;
        end if;

        if reject_reason is null then
            begin
                insert into analytics.duel_observations (
                    source_game_id,
                    contributor_key,
                    played_at_local,
                    timezone_offset_minutes,
                    result,
                    turn_order,
                    my_deck,
                    opp_deck,
                    turns,
                    end_reason,
                    play_context_id,
                    standing_kind,
                    rank_tier_before,
                    rank_tier_after,
                    rank_division_before,
                    rank_division_after,
                    rating_before,
                    rating_after,
                    event_points_before,
                    event_points_after,
                    event_id,
                    event_stage_id,
                    environment_version_id,
                    deck_catalog_version_id,
                    client_version,
                    payload_version,
                    source_kind
                )
                values (
                    sync_id,
                    installation_key,
                    observation ->> 'played_at_local',
                    (observation ->> 'timezone_offset_minutes')::integer,
                    observation ->> 'result',
                    observation ->> 'turn_order',
                    observation ->> 'my_deck',
                    observation ->> 'opp_deck',
                    (observation ->> 'turns')::integer,
                    observation ->> 'end_reason',
                    observation ->> 'play_context_id',
                    observation ->> 'standing_kind',
                    observation ->> 'rank_tier_before',
                    observation ->> 'rank_tier_after',
                    (observation ->> 'rank_division_before')::integer,
                    (observation ->> 'rank_division_after')::integer,
                    (observation ->> 'rating_before')::integer,
                    (observation ->> 'rating_after')::integer,
                    (observation ->> 'event_points_before')::integer,
                    (observation ->> 'event_points_after')::integer,
                    observation ->> 'event_id',
                    observation ->> 'event_stage_id',
                    observation ->> 'environment_version_id',
                    observation ->> 'deck_catalog_version_id',
                    ingest_guest_batch.client_version,
                    ingest_guest_batch.payload_version,
                    'guest'
                )
                on conflict (source_game_id) do update set
                    played_at_local = excluded.played_at_local,
                    timezone_offset_minutes = excluded.timezone_offset_minutes,
                    result = excluded.result,
                    turn_order = excluded.turn_order,
                    my_deck = excluded.my_deck,
                    opp_deck = excluded.opp_deck,
                    turns = excluded.turns,
                    end_reason = excluded.end_reason,
                    play_context_id = excluded.play_context_id,
                    standing_kind = excluded.standing_kind,
                    rank_tier_before = excluded.rank_tier_before,
                    rank_tier_after = excluded.rank_tier_after,
                    rank_division_before = excluded.rank_division_before,
                    rank_division_after = excluded.rank_division_after,
                    rating_before = excluded.rating_before,
                    rating_after = excluded.rating_after,
                    event_points_before = excluded.event_points_before,
                    event_points_after = excluded.event_points_after,
                    event_id = excluded.event_id,
                    event_stage_id = excluded.event_stage_id,
                    environment_version_id = excluded.environment_version_id,
                    deck_catalog_version_id = excluded.deck_catalog_version_id,
                    client_version = excluded.client_version,
                    payload_version = excluded.payload_version,
                    withdrawn_at = null,
                    withdrawal_source = null
                where analytics.duel_observations.source_kind = 'guest'
                  and op = 'upsert'
                returning source_game_id into inserted_game;

                if inserted_game is null then
                    skipped := skipped + 1;
                else
                    accepted := accepted + 1;
                end if;
            exception when check_violation or invalid_text_representation
                or numeric_value_out_of_range or not_null_violation then
                reject_reason := 'invalid_value';
            end;
        end if;

        if reject_reason is not null then
            rejected := rejected + 1;
            insert into analytics.rejected_observations
                (batch_id, source_game_id, reason)
            values (ingest_guest_batch.batch_id, sync_id, reject_reason);
        end if;
    end loop;

    insert into analytics.ingestion_batches (
        batch_id, source_kind, installation_key, client_version,
        payload_version, accepted_count, skipped_count, rejected_count
    )
    values (
        ingest_guest_batch.batch_id, 'guest', installation_key,
        ingest_guest_batch.client_version, ingest_guest_batch.payload_version,
        accepted, skipped, rejected
    );

    return jsonb_build_object(
        'batch_id', ingest_guest_batch.batch_id,
        'accepted', accepted,
        'skipped', skipped,
        'rejected', rejected,
        'replayed', false
    );
end;
$$;

revoke all on function analytics.ingest_guest_batch(uuid, uuid, text, integer, jsonb)
    from public;
