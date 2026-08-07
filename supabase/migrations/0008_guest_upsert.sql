-- 0008_guest_upsert.sql
-- 이미 ingest된 게스트 기록의 수정값을 같은 sync_id observation에 반영한다.
-- 등록 계정 observation과 UUID가 충돌하면 수정하지 않고 skipped로 처리한다.

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

    -- batch idempotency: 같은 batch 재전송은 기록된 요약을 그대로 돌려준다.
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
            -- 허용 필드 allowlist 검사: note, 이메일, 표시 이름 등
            -- private 필드가 포함된 payload는 거부한다.
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

        if reject_reason is null then
            op := coalesce(observation ->> 'op', 'create');
            if op = 'withdraw' then
                -- 이미 업로드된 게스트 기록의 철회(로드맵 9.3). idempotent.
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
                    -- create 중복 또는 등록 observation UUID 충돌은 건너뛴다.
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
